"""Stream OR3's two frozen trend rules over the already-used OR2 development set."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
import heapq
from itertools import groupby
import json
from pathlib import Path
import resource
import time

from custody.dataset import sha256_file
from .context_replay import SYMBOLS, iter_days, verify_inputs
from .context_stats import summarize_days
from .trend_signals import trend_trades


CANDIDATES = ('O30_VWAP', 'N30_TRAIL')
PREREG_SHA256 = 'f83d8710f7ae9e1ebe57887f3427dd54746e6148325e3a86537403edee467a12'


def replay(root):
    started = time.monotonic()
    root = Path(root)
    prereg = Path(__file__).with_name('notes') / 'OR3_PREREG.md'
    if sha256_file(prereg) != PREREG_SHA256:
        raise ValueError('OR3 preregistration changed; do not rerun under an altered rule')
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
                trades = trend_trades(bars, list(history[symbol]))
                if set(trades) != set(CANDIDATES):
                    raise ValueError('unexpected OR3 candidate set')
                for name in CANDIDATES:
                    days[name][day]['n_sessions'] += 1
                    if trades[name] is not None:
                        days[name][day]['returns'].append(trades[name]['gross_return'])
                        coverage[symbol][name + '_trades'] += 1
            history[symbol].append(bars)
    results = {name: summarize_days(values) for name, values in days.items()}
    eligible = [name for name in CANDIDATES if results[name]['selected_eligible']]
    selected = max(eligible, key=lambda name: (results[name]['net_mean_lower_95_bp'],
                                              name == 'O30_VWAP')) if eligible else None
    repo = Path(__file__).resolve().parents[2]
    code_paths = [Path(__file__), *(Path(__file__).with_name(name) for name in (
        'trend_signals.py', 'context_replay.py', 'context_signals.py', 'context_stats.py')),
        *(repo / 'custody' / name for name in ('__init__.py', 'dataset.py', 'marketdata.py', 'models.py'))]
    return {
        'round': 'OR3', 'verdict': 'DEVELOPMENT_ONLY', 'selected_for_further_testing': selected,
        'created_at': datetime.now(timezone.utc).isoformat(), 'inputs': inputs,
        'preregistration_sha256': PREREG_SHA256,
        'code_sha256': {str(path.relative_to(repo)): sha256_file(path) for path in code_paths},
        'candidates': results, 'coverage_by_symbol': coverage,
        'by_day': {name: dict(values) for name, values in days.items()},
        'limitations': [
            'OR2失败后提出的新开发轮；已用数据，非独立验证，未校正历年研究搜索或跨日依赖。',
            '当前存活标的池；历史0DTE挂牌身份未经验证，只有正股代理而非真实期权收益。',
            '完整全日检查会事后排除数据缺口；半日排除，未以外部交易日历核验共同缺失日期。',
            '本地manifest将09:35首根记为收盘；旧SDK导出转换缺少独立溯源。',
            '下一根5m收盘和固定bp成本不等于历史bid/ask成交，也不保证比实际撮合保守。',
            '无OR中点止损、2R止盈或60分钟时限；延长持有可能扩大损失暴露，不建议直接实盘。',
            '未读取新ETF或期权留出；开发入选仅是后续另行登记检验的候选，不代表发现Alpha。',
        ],
        'resources': {'elapsed_seconds': time.monotonic() - started,
                      'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                      'history_days_per_symbol': 14, 'bars_per_complete_day': 78},
    }


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
