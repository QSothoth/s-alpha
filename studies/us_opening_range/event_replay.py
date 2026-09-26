"""DS2 development-only, date-streamed event study; no fills or option returns."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
import heapq
from itertools import groupby
import json
from math import floor, fsum
from pathlib import Path
import random
import resource
import time

from custody.dataset import sha256_file
from .context_replay import SYMBOLS, verify_inputs
from .daily_replay import (CALENDAR_PATH, CALENDAR_SHA256, INPUT_SHA256,
                           aggregate_daily, iter_sessions, metrics, read_calendar)
from .daily_signals import evaluate_signal_quality
from .event_signals import CANDIDATES, activity_at, context, detect_events, prefix_at_checkpoint


PREREG_SHA256 = '1ebb0641738f688cba538e6b35b69a25e6da9379121423cbf9414385956cb19b'
SMALL_INPUT_SHA256 = '9a310566039ff271c56312f5772a90ab7f2d243b1326024d131c9bc932c21c21'
UNIVERSE_SHA256 = '891277ab17f755938b33eb3251fb700bc42b7a3670124f885f34e8477ac572d0'
UNIVERSE_PATH = Path('studies/archive/us_preopen_bias/notes/universe_smallmid.json')
SEED, DRAWS = 20260926, 2000


def asset_group(symbol):
    return 'ETF' if symbol in ('SPY', 'QQQ', 'IWM') else 'LARGE' if symbol in SYMBOLS else 'SMALLMID'


def quantile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * q
    left = floor(index)
    return ordered[left] + (index - left) * (ordered[min(left + 1, len(ordered) - 1)] - ordered[left])


def summarize(days, draws=DRAWS):
    keys = sorted(days)
    values = [value for day in keys for value in days[day]['returns']]
    paired = [value for day in keys for value in days[day]['paired']]
    result = metrics(values)
    result.update(n_dates=len(keys), signals=sum(days[day]['signals'] for day in keys),
                  eligible_sessions=sum(days[day]['n_sessions'] for day in keys),
                  active_dates=sum(days[day]['signals'] > 0 for day in keys),
                  paired_labels=len(paired), paired_mean_bp=10000 * fsum(paired) / len(paired) if paired else None)
    result['missing_labels'] = result['signals'] - len(values)
    result['paired_coverage'] = len(paired) / result['signals'] if result['signals'] else 0.0
    result['signals_per_100_sessions'] = 100 * result['signals'] / result['eligible_sessions'] if result['eligible_sessions'] else 0.0
    result['halves'] = {name: metrics([value for day in keys if test(day) for value in days[day]['returns']])
                        for name, test in (('before_2022_06_01', lambda day: day < '2022-06-01'),
                                           ('from_2022_06_01', lambda day: day >= '2022-06-01'))}
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
    result['raw_simultaneous_lower_bp'] = quantile(raw_boot, .05 / 3)
    result['paired_lower_95_bp'] = quantile(paired_boot, .05)
    result['bootstrap'] = {'draws': draws if rows else 0, 'seed': SEED, 'unit': 'date',
                           'raw_quantile': .05 / 3, 'paired_quantile': .05,
                           'quantile_method': 'linear_(n-1)*q', 'shared_raw_paired_draws': True,
                           'zero_signal_dates_included': True,
                           'undefined_raw_draws': draws - len(raw_boot) if rows else 0,
                           'undefined_paired_draws': draws - len(paired_boot) if rows else 0}
    positive = lambda value: value is not None and value > 0
    pf = result['profit_factor']
    result['gates'] = {
        '100_labeled_signals': len(values) >= 100,
        '60_active_dates': result['active_dates'] >= 60,
        'mean_at_least_5bp': result['mean_bp'] is not None and result['mean_bp'] >= 5,
        'raw_simultaneous_lower_positive': positive(result['raw_simultaneous_lower_bp']),
        'profit_factor_at_least_1_2': pf >= 1.2 if pf is not None else result['wins'] > 0 and not result['losses'],
        'both_halves_positive': all(positive(row['mean_bp']) for row in result['halves'].values()),
        'paired_coverage_at_least_80pct': result['paired_coverage'] >= .8,
        'paired_lower_positive': positive(result['paired_lower_95_bp'])}
    result['development_eligible'] = all(result['gates'].values())
    return result


def measurement_signal(prefix, levels, direction):
    reference, atr = prefix[-1].close, levels['atr']
    sign = 1 if direction == 'LONG' else -1
    return {'symbol': levels['symbol'], 'time': prefix[-1].close_time.isoformat(),
            'direction': direction, 'reference': reference, 'atr': atr, 'risk': .25 * atr,
            'target': reference + sign * .5 * atr, 'invalidation': reference - sign * .25 * atr}


def peer_names(event, contexts, current):
    """Freeze the peer list using history and reached prefix only, never labels."""
    symbol, minutes = event['symbol'].removeprefix('US.'), event['snapshot_minutes']
    sign = 1 if event['direction'] == 'LONG' else -1
    peers = []
    for other, levels in sorted(contexts.items()):
        if other == symbol or asset_group(other) != asset_group(symbol):
            continue
        prefix = prefix_at_checkpoint(current[other][0], levels, minutes)
        if (prefix is not None and activity_at(prefix, levels, minutes)['status'] == 'pass'
                and sign * (prefix[-1].close - prefix[0].open) > 0):
            peers.append(other)
    return peers


def evaluate_event(event, contexts, current):
    peers = peer_names(event, contexts, current)
    symbol, minutes = event['symbol'].removeprefix('US.'), event['snapshot_minutes']
    quality = evaluate_signal_quality(current[symbol][0], event)
    peer_values = []
    for other in peers:
        levels = contexts[other]
        prefix = prefix_at_checkpoint(current[other][0], levels, minutes)
        label = evaluate_signal_quality(current[other][0], measurement_signal(prefix, levels, event['direction']))
        peer_values.append(label['return_30m'])
    paired_ok = quality['label_status'] == 'complete' and peers and all(value is not None for value in peer_values)
    paired = quality['return_30m'] - fsum(peer_values) / len(peers) if paired_ok else None
    spy_return = None
    if symbol != 'SPY' and 'SPY' in current:
        # SPY is a descriptive clock-matched benchmark, not activity-selected.
        spy_levels = {'symbol': 'US.SPY', 'trade_date': event['time'][:10], 'atr': event['atr']}
        prefix = prefix_at_checkpoint(current['SPY'][0], spy_levels, minutes)
        if prefix is not None:
            spy_return = evaluate_signal_quality(current['SPY'][0], measurement_signal(prefix, spy_levels, event['direction']))['return_30m']
    return dict(quality, peers=peers, peer_returns=peer_values,
                paired_status='complete' if paired_ok else 'missing', paired_lift=paired,
                spy_signed_return=spy_return,
                spy_beta1_difference=(quality['return_30m'] - spy_return
                                      if quality['return_30m'] is not None and spy_return is not None else None))


def verify_small(root, universe_path=UNIVERSE_PATH):
    root = Path(root).resolve()
    if sha256_file(root / 'CHECKSUMS.sha256') != SMALL_INPUT_SHA256 or sha256_file(universe_path) != UNIVERSE_SHA256:
        raise ValueError('DS2 small/mid input or universe checksum mismatch')
    universe = json.loads(Path(universe_path).read_text(encoding='utf-8'))
    intended = sorted(item['code'].removeprefix('US.') for group in universe['themes'].values()
                      for item in group if item['code'] not in ('US.KOD', 'US.AVTX'))
    if len(intended) != 34 or len(set(intended)) != 34:
        raise ValueError('unexpected fixed small/mid universe')
    pins = {}
    for line in (root / 'CHECKSUMS.sha256').read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        digest, name = line.split(maxsplit=1)
        name = name.strip().lstrip('*')
        path = (root / name).resolve()
        if name in pins or not path.is_relative_to(root) or not path.is_file() or sha256_file(path) != digest:
            raise ValueError('invalid small/mid checksum entry: ' + name)
        pins[name] = digest
    present = [symbol for symbol in intended if (root / 'k5' / (symbol + '.csv')).is_file()]
    missing = sorted(set(intended) - set(present))
    if missing != ['TEM'] or any('k5/' + symbol + '.csv' not in pins for symbol in present):
        raise ValueError('unexpected missing or unpinned small/mid K5 input')
    return present, {'checksums_sha256': SMALL_INPUT_SHA256, 'universe_sha256': UNIVERSE_SHA256,
                     'intended': intended, 'missing': missing, 'files_sha256': pins}


def day_record():
    return {'n_sessions': 0, 'signals': 0, 'returns': [], 'paired': []}


def quality_flags(event, bars, history):
    """Coverage flags only: no post-hoc removal of halted or inactive sessions."""
    cutoff = datetime.fromisoformat(event['time'])
    prefix = [bar for bar in bars if bar.close_time <= cutoff]
    return {'zero_volume_prefix_bars': sum(bar.volume == 0 for bar in prefix),
            'flat_zero_volume_prefix_bars': sum(bar.volume == 0 and bar.open == bar.high == bar.low == bar.close
                                               for bar in prefix),
            'reference_zero_volume': prefix[-1].volume == 0,
            'historical_opening_zero_volume_bars': sum(bar.volume == 0 for rows in history for bar in rows)}


def replay(root, small_root, calendar_path=CALENDAR_PATH, emit=None):
    started = time.monotonic()
    root, small_root = Path(root), Path(small_root)
    prereg = Path(__file__).with_name('notes') / 'DS2_PREREG.md'
    if sha256_file(prereg) != PREREG_SHA256 or sha256_file(root / 'CHECKSUMS.sha256') != INPUT_SHA256:
        raise ValueError('DS2 preregistration or large-cap input checksum mismatch')
    inputs = {'large': verify_inputs(root)}
    small, inputs['smallmid'] = verify_small(small_root)
    calendar = read_calendar(calendar_path)
    inputs['calendar_metadata_sha256'] = CALENDAR_SHA256
    symbols = tuple(SYMBOLS) + tuple(small)
    daily = {symbol: deque(maxlen=20) for symbol in symbols}
    opening = {symbol: deque(maxlen=20) for symbol in symbols}
    days = {name: {day: day_record() for day in sorted(calendar)} for name in CANDIDATES}
    coverage = {symbol: Counter() for symbol in symbols}
    rejected, overlaps = Counter(), Counter()
    paths = {name: Counter() for name in CANDIDATES}
    quality_counts = {name: Counter() for name in CANDIDATES}
    auxiliary = {name: defaultdict(list) for name in CANDIDATES}
    groups = {name: defaultdict(list) for name in CANDIDATES}
    streams = [iter_sessions((root if symbol in SYMBOLS else small_root) / 'k5' / (symbol + '.csv'), symbol, calendar)
               for symbol in symbols]
    streams.append(((day, '', None, None) for day in sorted(calendar)))
    merged = heapq.merge(*streams, key=lambda row: (row[0], row[1]))
    for day, records in groupby(merged, key=lambda row: row[0]):
        if day < '2020-01-02':
            continue
        if day not in calendar:
            raise ValueError('date outside DS2 calendar: ' + day)
        current = {symbol: (bars, complete) for _, symbol, bars, complete in records if symbol}
        contexts, pending = {}, []
        for symbol in symbols:
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
            levels = context(list(daily[symbol]), list(opening[symbol]), datetime.fromisoformat(day).date())
            contexts[symbol] = levels
            events, blocked = detect_events(bars, levels)
            rejected.update(blocked)
            if events['G20_HOLD'] and events['F20_FAIL']:
                overlaps['same_symbol_day_G_and_F'] += 1
            for name in CANDIDATES:
                days[name][day]['n_sessions'] += 1
                if events[name] is not None:
                    pending.append(events[name])
        # All cross-sectional contexts and event-time peer membership precede labels.
        for event in pending:
            name, symbol = event['candidate'], event['symbol'].removeprefix('US.')
            quality = evaluate_event(event, contexts, current)
            flags = quality_flags(event, current[symbol][0], opening[symbol])
            for key, value in flags.items():
                quality_counts[name][key + '_signals'] += bool(value)
            record = days[name][day]
            record['signals'] += 1
            coverage[symbol][name + '_signals'] += 1
            if emit is not None:
                emit(dict(event, asset_group=asset_group(symbol), data_quality=flags, **quality))
            if quality['label_status'] != 'complete':
                paths[name]['missing_future'] += 1
                continue
            value = quality['return_30m']
            record['returns'].append(value)
            if quality['paired_lift'] is not None:
                record['paired'].append(quality['paired_lift'])
            groups[name][asset_group(symbol)].append(value)
            groups[name][event['direction']].append(value)
            paths[name][quality['path_status']] += 1
            for key in ('return_atr', 'mfe_r', 'mae_r', 'spy_beta1_difference'):
                if quality[key] is not None:
                    auxiliary[name][key].append(quality[key])
        # Today's full day is committed only after every event and peer list.
        for symbol, (bars, complete) in current.items():
            if complete:
                daily[symbol].append(aggregate_daily(bars, calendar[day]))
                opening[symbol].append(bars[:6])
            else:
                daily[symbol].clear()
                opening[symbol].clear()
    results = {name: summarize(days[name]) for name in CANDIDATES}
    for name, result in results.items():
        result['path_counts'] = dict(paths[name])
        result['quality_flag_counts'] = dict(quality_counts[name])
        result['mean_auxiliary'] = {key: fsum(values) / len(values) if values else None for key, values in auxiliary[name].items()}
        result['auxiliary_counts'] = {key: len(values) for key, values in auxiliary[name].items()}
        result['conservative_target_first_rate'] = paths[name]['target_first'] / result['signals'] if result['signals'] else None
        result['groups_descriptive_only'] = {key: metrics(values) for key, values in groups[name].items()}
    eligible = [name for name in CANDIDATES if results[name]['development_eligible']]
    selected = min(eligible, key=lambda name: (-results[name]['paired_lower_95_bp'], -results[name]['raw_simultaneous_lower_bp'], name)) if eligible else None
    repo = Path(__file__).resolve().parents[2]
    files = [Path(__file__), Path(__file__).with_name('event_signals.py'),
             Path(__file__).with_name('daily_signals.py'), Path(__file__).with_name('daily_replay.py'),
             Path(__file__).with_name('context_replay.py'), Path(__file__).with_name('context_stats.py'),
             Path(__file__).with_name('context_signals.py'), repo / 'custody' / 'marketdata.py',
             repo / 'custody' / 'models.py', repo / 'custody' / 'dataset.py']
    return {'study': 'DS2', 'status': 'DEVELOPMENT_SIGNAL_QUALITY_ONLY', 'selected_for_migration': selected,
            'created_at': datetime.now(timezone.utc).isoformat(), 'inputs': inputs,
            'preregistration_sha256': PREREG_SHA256,
            'code_sha256': {str(path.relative_to(repo)): sha256_file(path) for path in files},
            'candidates': results, 'coverage_by_symbol': coverage, 'checkpoint_rejections': rejected,
            'overlaps': overlaps, 'by_day': days, 'elapsed_seconds': time.monotonic() - started,
            'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'limitations': ['Previously exposed development dates; current-survivor universe.',
                            'Historical 0DTE availability unverified; no option P&L or fills.',
                            'Peers are observational; three-test bound does not correct earlier research.',
                            'Zero-volume bars are retained, not silently treated as actual trades.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('data/preopen-us-k5-select-v1'))
    parser.add_argument('--small-root', type=Path, default=Path('data/preopen-s20-select-v1'))
    parser.add_argument('--calendar', type=Path, default=CALENDAR_PATH)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--signals-out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists() or args.signals_out.exists() or args.out.resolve() == args.signals_out.resolve():
        parser.error('outputs must be distinct new paths; prior runs are never overwritten')
    with args.signals_out.open('x', encoding='utf-8') as handle:
        result = replay(args.root, args.small_root, args.calendar,
                        emit=lambda row: handle.write(json.dumps(row, sort_keys=True, allow_nan=False) + '\n'))
    result['signals_artifact'] = {'path': str(args.signals_out), 'sha256': sha256_file(args.signals_out)}
    with args.out.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write('\n')
    print(json.dumps({key: result[key] for key in ('study', 'selected_for_migration', 'elapsed_seconds', 'peak_rss_kib')}))


if __name__ == '__main__':
    main()
