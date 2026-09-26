"""RG1: one post-hoc reversal hypothesis, tested once on three held-out assets."""
from __future__ import annotations

import argparse
from collections import Counter, deque
import csv
from datetime import date, datetime, timezone
import heapq
from itertools import groupby
import json
from math import fsum
from pathlib import Path
import random
import resource
import time

from custody.dataset import sha256_file
from custody.marketdata import Bar
from custody.models import ET
from .daily_replay import aggregate_daily, complete_session, metrics
from .daily_signals import evaluate_signal_quality
from .event_replay import day_record, measurement_signal, quality_flags, quantile
from .event_signals import activity_at, context, detect_events, prefix_at_checkpoint


SYMBOLS = ('XLV', 'XLI', 'XLY')
CANDIDATE = 'G20_REVERSE'
START, END, SPLIT = '2018-09-20', '2026-09-24', '2023-01-01'
ROOT = Path('data/or-context-etf-k5-2018-2026-retry1-work')
PREREG_SHA256 = 'ea4c155d698d853e6cfbe91444134c8ddd665ecf186a3fbaa95a232f3f853d54'
INPUT_SHA256 = '5ac28d322f91c5877349a2d1021bfabecce98c74e09f83cb45192d1f35cc66ee'
CALENDAR_SHA256 = '501c508b69124b1da76c0b986c997ae3a89106eb59e865847637043f21eb72b8'
PRICE_SHA256 = {
    'XLV': 'dd536bbcbca454b9c01a409c73648bf87d78482a6c040ba662dd26e014036f17',
    'XLI': '4773b661dc964a78982f23866e56f4667086e228f7e4c765892d035bd1b58168',
    'XLY': 'c59db79b67d17171ccd6cbcfc77bb5a35e607d0b762bde75c80b441b1bc66107'}
SEED, DRAWS = 20260926, 2000


def load_inputs(root):
    """Hash only the three authorized price files; all other pins are metadata."""
    root = Path(root).resolve()
    prereg = Path(__file__).with_name('notes') / 'RG1_PREREG.md'
    if sha256_file(prereg) != PREREG_SHA256:
        raise ValueError('RG1 preregistration checksum mismatch')
    checksum = root / 'CHECKSUMS.sha256'
    if checksum.is_symlink() or sha256_file(checksum) != INPUT_SHA256:
        raise ValueError('RG1 input checksum mismatch')
    pins = {}
    for line in checksum.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        digest, name = line.split(maxsplit=1)
        name = name.strip().lstrip('*')
        if name in pins:
            raise ValueError('duplicate checksum entry')
        pins[name] = digest
    wanted = {'US.' + symbol + '.csv': PRICE_SHA256[symbol] for symbol in SYMBOLS}
    wanted.update({'US.' + symbol + '.coverage.csv': CALENDAR_SHA256 for symbol in (*SYMBOLS, 'DIA')})
    for name, digest in wanted.items():
        path = root / name
        if pins.get(name) != digest or path.is_symlink() or sha256_file(path) != digest:
            raise ValueError('RG1 authorized input mismatch: ' + name)
    calendar = {}
    with (root / 'US.DIA.coverage.csv').open(newline='', encoding='utf-8') as handle:
        for row in csv.DictReader(handle):
            day = row['date']
            if not START <= day <= END:
                continue
            date.fromisoformat(day)
            count = int(row['rows'])
            if (day in calendar or calendar and day <= next(reversed(calendar))
                    or count not in (42, 78) or row['first_close'] != '09:35:00'
                    or row['last_close'] != ('13:00:00' if count == 42 else '16:00:00')
                    or int(row['missing_before_or_between']) != 0):
                raise ValueError('invalid RG1 calendar metadata')
            calendar[day] = count
    if not calendar or min(calendar) != START or max(calendar) != END:
        raise ValueError('RG1 calendar does not cover its fixed date range')
    return calendar, {'root': str(root), 'checksums_sha256': INPUT_SHA256,
                      'files_sha256': wanted, 'symbols': list(SYMBOLS), 'source': 'OpenD',
                      'adjustment': 'QFQ', 'session': 'RTH', 'interval': '5m',
                      'start': START, 'end': END, 'excluded_from': '2026-09-25',
                      'full_file_hash_includes_sealed_bytes_without_price_parsing': True}


def iter_sessions(path, symbol, calendar):
    """Bound a day; stop at the first excluded date before parsing any prices."""
    if symbol not in SYMBOLS:
        raise ValueError('RG1 permits only XLV, XLI and XLY')
    previous = None
    with Path(path).open(newline='', encoding='utf-8') as handle:
        reader = csv.DictReader(handle)
        required = {'code', 'time_key', 'open', 'high', 'low', 'close', 'volume'}
        if not required.issubset(reader.fieldnames or ()):
            raise ValueError('invalid RG1 CSV header')
        for day, rows in groupby(reader, key=lambda row: row['time_key'][:10]):
            if day > END:
                break
            if day < START:
                continue
            if day not in calendar:
                raise ValueError('price date outside RG1 calendar: ' + day)
            bars, invalid, count = [], False, 0
            for row in rows:
                stamp = datetime.fromisoformat(row['time_key'])
                if stamp.tzinfo is not None or row['code'] != 'US.' + symbol:
                    raise ValueError('wrong code or non-local OpenD timestamp')
                stamp = stamp.replace(tzinfo=ET)
                if previous is not None and stamp <= previous:
                    raise ValueError('duplicate or unordered RG1 timestamp')
                previous = stamp
                count += 1
                if count > 78:
                    raise ValueError('more than 78 RTH bars in one day')
                try:
                    bars.append(Bar('US.' + symbol, stamp, *(float(row[key]) for key in
                                    ('open', 'high', 'low', 'close', 'volume')), interval='5m',
                                    source='opend_qfq_5m'))
                except (KeyError, TypeError, ValueError):
                    invalid = True
            yield day, symbol, bars, not invalid and complete_session(bars, calendar[day])


def reverse_event(original):
    if original['candidate'] != 'G20_HOLD' or original['direction'] not in ('LONG', 'SHORT'):
        raise ValueError('only original G20 events may be reversed')
    direction = 'SHORT' if original['direction'] == 'LONG' else 'LONG'
    sign = 1 if direction == 'LONG' else -1
    return original | {'candidate': CANDIDATE, 'original_direction': original['direction'],
                       'original_candidate': 'G20_HOLD', 'direction': direction,
                       'risk': .25 * original['atr'],
                       'invalidation': original['reference'] - sign * .25 * original['atr'],
                       'target': original['reference'] + sign * .5 * original['atr']}


def peer_names(event, contexts, current):
    sign = 1 if event['original_direction'] == 'LONG' else -1
    peers = []
    for other in SYMBOLS:
        if other == event['symbol'].removeprefix('US.') or other not in contexts:
            continue
        levels, minutes = contexts[other], event['snapshot_minutes']
        prefix = prefix_at_checkpoint(current[other][0], levels, minutes)
        if (prefix is not None and activity_at(prefix, levels, minutes)['status'] == 'pass'
                and sign * (prefix[-1].close - prefix[0].open) > 0):
            peers.append(other)
    return peers


def evaluate_event(event, contexts, current):
    peers = peer_names(event, contexts, current)  # Membership precedes every label.
    own = evaluate_signal_quality(current[event['symbol'].removeprefix('US.')][0], event)
    values = []
    for other in peers:
        prefix = prefix_at_checkpoint(current[other][0], contexts[other], event['snapshot_minutes'])
        signal = measurement_signal(prefix, contexts[other], event['direction'])
        values.append(evaluate_signal_quality(current[other][0], signal)['return_30m'])
    complete = own['label_status'] == 'complete' and peers and all(value is not None for value in values)
    return own | {'peers': peers, 'peer_returns': values,
                  'paired_status': 'complete' if complete else 'missing',
                  'paired_lift': own['return_30m'] - fsum(values) / len(values) if complete else None}


def summarize(days, draws=DRAWS):
    keys = sorted(days)
    values = [value for day in keys for value in days[day]['returns']]
    paired = [value for day in keys for value in days[day]['paired']]
    result = metrics(values)
    result.update(n_dates=len(keys), signals=sum(days[day]['signals'] for day in keys),
                  eligible_sessions=sum(days[day]['n_sessions'] for day in keys),
                  active_dates=sum(days[day]['signals'] > 0 for day in keys),
                  labeled_dates=sum(bool(days[day]['returns']) for day in keys),
                  paired_labels=len(paired), paired_mean_bp=10000 * fsum(paired) / len(paired) if paired else None)
    result['missing_labels'] = result['signals'] - len(values)
    result['paired_coverage'] = len(paired) / result['signals'] if result['signals'] else 0.0
    result['signals_per_100_sessions'] = 100 * result['signals'] / result['eligible_sessions'] if result['eligible_sessions'] else 0.0
    result['halves'] = {name: metrics([value for day in keys if (day < SPLIT) == before
                                     for value in days[day]['returns']])
                        for name, before in (('before_2023_01_01', True), ('from_2023_01_01', False))}
    rows = [(fsum(days[day]['returns']), len(days[day]['returns']),
             fsum(days[day]['paired']), len(days[day]['paired'])) for day in keys]
    rng, raw_boot, paired_boot = random.Random(SEED), [], []
    for _ in range(draws if rows else 0):
        raw_sum = paired_sum = 0.0
        raw_count = paired_count = 0
        for _ in rows:
            rsum, rcount, psum, pcount = rng.choice(rows)
            raw_sum += rsum
            raw_count += rcount
            paired_sum += psum
            paired_count += pcount
        if raw_count:
            raw_boot.append(10000 * raw_sum / raw_count)
        if paired_count:
            paired_boot.append(10000 * paired_sum / paired_count)
    result['raw_lower_95_bp'], result['paired_lower_95_bp'] = quantile(raw_boot, .05), quantile(paired_boot, .05)
    result['bootstrap'] = {'draws': draws if rows else 0, 'seed': SEED, 'unit': 'date',
                           'raw_quantile': .05, 'paired_quantile': .05,
                           'quantile_method': 'linear_(n-1)*q', 'shared_raw_paired_draws': True,
                           'zero_signal_dates_included': True,
                           'undefined_raw_draws': draws - len(raw_boot) if rows else 0,
                           'undefined_paired_draws': draws - len(paired_boot) if rows else 0}
    positive = lambda value: value is not None and value > 0
    pf = result['profit_factor']
    result['gates'] = {
        '100_labeled_signals': len(values) >= 100, '60_active_dates': result['active_dates'] >= 60,
        'mean_at_least_5bp': result['mean_bp'] is not None and result['mean_bp'] >= 5,
        'raw_lower_positive': positive(result['raw_lower_95_bp']),
        'profit_factor_at_least_1_2': pf >= 1.2 if pf is not None else result['wins'] > 0 and not result['losses'],
        'both_halves_positive': all(positive(row['mean_bp']) for row in result['halves'].values()),
        'paired_coverage_at_least_80pct': result['paired_coverage'] >= .8,
        'paired_lower_positive': positive(result['paired_lower_95_bp'])}
    result['asset_transfer_eligible'] = all(result['gates'].values())
    return result


def replay(root=ROOT, emit=None):
    started, root = time.monotonic(), Path(root)
    calendar, inputs = load_inputs(root)
    daily, opening = ({symbol: deque(maxlen=20) for symbol in SYMBOLS} for _ in range(2))
    days = {day: day_record() for day in calendar}
    coverage = {symbol: Counter() for symbol in SYMBOLS}
    rejected, paths, flags_count, totals = Counter(), Counter(), Counter(), Counter()
    groups = {symbol: [] for symbol in SYMBOLS}
    streams = [iter_sessions(root / ('US.' + symbol + '.csv'), symbol, calendar) for symbol in SYMBOLS]
    streams.append(((day, '', None, None) for day in calendar))
    for day, records in groupby(heapq.merge(*streams, key=lambda row: (row[0], row[1])), key=lambda row: row[0]):
        if day not in calendar or not START <= day <= END:
            raise ValueError('date outside RG1 range')
        current = {symbol: (bars, complete) for _, symbol, bars, complete in records if symbol}
        contexts, pending = {}, []
        for symbol in SYMBOLS:
            if symbol not in current:
                coverage[symbol]['missing_day'] += 1
                daily[symbol].clear()
                opening[symbol].clear()
                continue
            bars, complete = current[symbol]
            coverage[symbol]['observed_days'] += 1
            coverage[symbol]['complete_days' if complete else 'incomplete_days'] += 1
            if len(daily[symbol]) != 20:
                coverage[symbol]['warmup_days'] += 1
                continue
            coverage[symbol]['history_eligible_days'] += 1
            contexts[symbol] = context(list(daily[symbol]), list(opening[symbol]), date.fromisoformat(day))
            events, blocked = detect_events(bars, contexts[symbol])
            rejected.update({key: value for key, value in blocked.items() if key != 'no_event'})
            days[day]['n_sessions'] += 1
            if events['G20_HOLD'] is not None:
                pending.append(reverse_event(events['G20_HOLD']))
            else:
                coverage[symbol]['no_G20_session'] += 1
        for event in pending:
            symbol = event['symbol'].removeprefix('US.')
            quality = evaluate_event(event, contexts, current)
            flags = quality_flags(event, current[symbol][0], opening[symbol])
            flags_count.update({key + '_signals': int(bool(value)) for key, value in flags.items()})
            days[day]['signals'] += 1
            coverage[symbol]['signals'] += 1
            if emit is not None:
                emit(event | quality | {'data_quality': flags})
            if quality['label_status'] != 'complete':
                paths['missing_future'] += 1
                continue
            value = quality['return_30m']
            days[day]['returns'].append(value)
            groups[symbol].append(value)
            if quality['paired_lift'] is not None:
                days[day]['paired'].append(quality['paired_lift'])
            paths[quality['path_status']] += 1
            totals['labels'] += 1
            for key in ('return_atr', 'mfe_r', 'mae_r'):
                totals[key] += quality[key]
        for symbol, (bars, complete) in current.items():
            if complete:
                daily[symbol].append(aggregate_daily(bars, calendar[day]))
                opening[symbol].append(bars[:6])
            else:
                daily[symbol].clear()
                opening[symbol].clear()
    result = summarize(days)
    result.update(path_counts=dict(paths), quality_flag_counts=dict(flags_count),
                  mean_auxiliary={key: totals[key] / totals['labels'] if totals['labels'] else None
                                  for key in ('return_atr', 'mfe_r', 'mae_r')},
                  conservative_target_first_rate=paths['target_first'] / result['signals'] if result['signals'] else None,
                  groups_descriptive_only={symbol: metrics(values) for symbol, values in groups.items()})
    repo = Path(__file__).resolve().parents[2]
    files = [Path(__file__), *(Path(__file__).with_name(name + '.py') for name in
              ('event_replay', 'event_signals', 'daily_replay', 'daily_signals', 'context_replay', 'context_signals', 'context_stats')),
             *(repo / 'custody' / (name + '.py') for name in ('dataset', 'marketdata', 'models'))]
    return {'study': 'RG1', 'status': 'ASSET_TRANSFER_THRESHOLD_PASSED' if result['asset_transfer_eligible'] else 'ASSET_TRANSFER_NOT_PASSED',
            'created_at': datetime.now(timezone.utc).isoformat(), 'inputs': inputs,
            'preregistration_sha256': PREREG_SHA256,
            'code_sha256': {str(path.relative_to(repo)): sha256_file(path) for path in files},
            'candidates': {CANDIDATE: result}, 'coverage_by_symbol': coverage,
            'common_checkpoint_rejections': rejected, 'by_day': days,
            'resources': {'elapsed_seconds': time.monotonic() - started,
                          'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss},
            'limitations': ['事后反转假设；不修改DS2未晋级结论，单候选区间未校正历史搜索。',
                            '未见资产迁移共享市场日期；不是独立时间验证，也不识别因果。',
                            '正股30分钟参考价标签；没有期权收益、成交、费用或逐日0DTE挂牌认证。',
                            '零量K线保留，不代表可成交；QFQ不是逐时点复权因子档案。',
                            '三只资产全部报告，不按分组挑赢家；09/25仍排除价格解析。']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--signals-out', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists() or args.signals_out.exists() or args.out.resolve() == args.signals_out.resolve():
        parser.error('outputs must be distinct new paths; prior runs are never overwritten')
    with args.signals_out.open('x', encoding='utf-8') as handle:
        result = replay(args.root, lambda row: handle.write(json.dumps(row, sort_keys=True, allow_nan=False) + '\n'))
    result['signals_artifact'] = {'path': str(args.signals_out), 'sha256': sha256_file(args.signals_out)}
    with args.out.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write('\n')
    print(json.dumps({key: result[key] for key in ('study', 'status', 'resources')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
