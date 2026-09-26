"""Stream the fixed OR2 development sample without loading full minute tables."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
import csv
from datetime import datetime, timedelta, timezone
import heapq
from itertools import groupby
import json
from pathlib import Path
import resource
import time

from custody.dataset import sha256_file
from custody.marketdata import Bar
from custody.models import ET
from .context_signals import context_trades, validate_day
from .context_stats import summarize_days


SYMBOLS = ('SPY', 'QQQ', 'IWM', 'AAPL', 'MSFT', 'NVDA', 'TSLA', 'META',
           'AMZN', 'GOOGL', 'AMD', 'MU', 'INTC', 'AVGO')
CANDIDATES = ('B30', 'N30', 'R30', 'C30')
PREREG_SHA256 = '0eb641c1e5aa25374f1af49f971de665640e8005ee5b9f4f0f5bcfba564a9a8b'


def verify_inputs(root):
    """Pin exactly the registered dataset and bounded file set before computing returns."""
    root = Path(root).resolve()
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    if (manifest.get('name') != 'preopen-us-k5-select-v1'
            or manifest.get('window') != ['2020-01-02', '2024-05-31']
            or manifest.get('role') != 'train/preopen-k5'):
        raise ValueError('OR2 permits only the preregistered development dataset')
    pins = {}
    for line in (root / 'CHECKSUMS.sha256').read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        digest, name = line.split(maxsplit=1)
        name = name.strip().lstrip('*')
        target = (root / name).resolve()
        if name in pins or not target.is_relative_to(root) or not target.is_file():
            raise ValueError('invalid checksum entry: ' + name)
        if sha256_file(target) != digest:
            raise ValueError('checksum mismatch: ' + name)
        pins[name] = digest
    required = ['manifest.json'] + ['k5/' + symbol + '.csv' for symbol in SYMBOLS]
    if any(name not in pins for name in required):
        raise ValueError('missing checksum for a required input')
    return {'dataset': manifest['name'], 'role': manifest['role'],
            'checksums_sha256': sha256_file(root / 'CHECKSUMS.sha256'),
            'files_sha256': {name: pins[name] for name in required}}


def iter_days(path, symbol):
    """Keep at most 78 bars; malformed ordering is fatal, incomplete days are recorded."""
    previous = None
    with Path(path).open(newline='', encoding='utf-8') as handle:
        for day, rows in groupby(csv.DictReader(handle), key=lambda row: row['time_key'][:10]):
            bars, reason, count = [], None, 0
            for row in rows:
                stamp = datetime.fromisoformat(row['time_key'])
                if stamp.tzinfo is not None:
                    raise ValueError('expected OpenD local ET timestamp: ' + row['time_key'])
                stamp = stamp.replace(tzinfo=ET)
                if previous is not None and stamp <= previous:
                    raise ValueError('duplicate or unordered bar: ' + row['time_key'])
                previous = stamp
                count += 1
                if count > 78:
                    reason = 'too_many_bars'
                    continue
                try:
                    bar = Bar('US.' + symbol, stamp, *(float(row[field]) for field in
                              ('open', 'high', 'low', 'close', 'volume')), interval='5m', source='frozen')
                    if min(bar.open, bar.high, bar.low, bar.close) <= 0:
                        raise ValueError('nonpositive price')
                    bars.append(bar)
                except (KeyError, TypeError, ValueError):
                    reason = 'invalid_ohlcv'
            if reason is None:
                if count == 42 and all(
                        bar.close_time == bars[0].close_time.replace(hour=9, minute=30, second=0,
                                                                    microsecond=0) +
                        timedelta(minutes=5 * index)
                        for index, bar in enumerate(bars, 1)):
                    reason = 'short_session'
                elif count != 78:
                    reason = 'incomplete_session'
                else:
                    try:
                        validate_day(bars)
                    except ValueError:
                        reason = 'invalid_session_grid'
            yield day, symbol, bars if reason is None else None, reason


def replay(root):
    started = time.monotonic()
    root = Path(root)
    prereg = Path(__file__).with_name('notes') / 'OR2_PREREG.md'
    if sha256_file(prereg) != PREREG_SHA256:
        raise ValueError('OR2 preregistration changed; do not rerun under an altered rule')
    inputs = verify_inputs(root)
    history = {symbol: deque(maxlen=14) for symbol in SYMBOLS}
    days = {name: defaultdict(lambda: {'n_sessions': 0, 'returns': []}) for name in CANDIDATES}
    coverage = {symbol: Counter() for symbol in SYMBOLS}
    streams = [iter_days(root / 'k5' / (symbol + '.csv'), symbol) for symbol in SYMBOLS]
    merged = heapq.merge(*streams, key=lambda item: (item[0], item[1]))
    for day, group in groupby(merged, key=lambda item: item[0]):
        if not '2020-01-02' <= day <= '2024-05-31':
            raise ValueError('date outside preregistered sample: ' + day)
        current = {symbol: (bars, reason) for _, symbol, bars, reason in group}
        market = current.get('SPY', (None, None))[0]
        for symbol in SYMBOLS:
            if symbol not in current:
                coverage[symbol]['missing_day'] += 1
                continue
            bars, reason = current[symbol]
            coverage[symbol]['observed_days'] += 1
            if reason:
                coverage[symbol][reason] += 1
                continue
            if len(history[symbol]) < 14:
                coverage[symbol]['warmup_days'] += 1
            else:
                coverage[symbol]['eligible_days'] += 1
                if market is None:
                    coverage[symbol]['market_unavailable_days'] += 1
                trades = context_trades(bars, list(history[symbol]), market)
                if set(trades) != set(CANDIDATES):
                    raise ValueError('unexpected candidate set')
                for name, trade in trades.items():
                    days[name][day]['n_sessions'] += 1
                    if trade is not None:
                        days[name][day]['returns'].append(trade['gross_return'])
                        coverage[symbol][name + '_trades'] += 1
            history[symbol].append(bars)
    results = {name: summarize_days(values) for name, values in days.items()}
    eligible = [name for name in ('N30', 'R30', 'C30') if results[name]['selected_eligible']]
    selected = max(eligible, key=lambda name: results[name]['net_mean_lower_95_bp']) if eligible else None
    repo = Path(__file__).resolve().parents[2]
    code_paths = [Path(__file__), Path(__file__).with_name('context_signals.py'),
                  Path(__file__).with_name('context_stats.py'), repo / 'custody' / 'marketdata.py',
                  repo / 'custody' / 'models.py', repo / 'custody' / 'dataset.py']
    return {'verdict': 'DEVELOPMENT_ONLY', 'selected_for_further_testing': selected,
            'created_at': datetime.now(timezone.utc).isoformat(), 'inputs': inputs,
            'preregistration_sha256': PREREG_SHA256,
            'code_sha256': {str(path.relative_to(repo)): sha256_file(path) for path in code_paths},
            'candidates': results, 'coverage_by_symbol': coverage,
            'by_day': {name: dict(values) for name, values in days.items()},
            'limitations': ['已用开发数据；非独立验证，未校正历年全部研究搜索。',
                            '当前存活标的池，历史0DTE挂牌身份未经验证；仅正股方向代理。',
                            '完整全日检查会事后排除数据缺口，不等于实时可执行样本。',
                            '5m下一根收盘及固定bp成本不是历史bid/ask或真实期权收益。'],
            'resources': {'elapsed_seconds': time.monotonic() - started,
                          'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=Path('data/preopen-us-k5-select-v1'))
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error('refusing to overwrite report: ' + str(args.out))
    report = replay(args.dataset)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps({key: report[key] for key in
                      ('verdict', 'selected_for_further_testing', 'resources')}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
