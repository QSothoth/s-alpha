"""AH1's frozen attention-background diagnostic; no fills or option returns."""
from __future__ import annotations

import argparse
from collections import Counter, deque
import csv
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
import heapq
from itertools import groupby
import json
from math import fsum, isfinite
from pathlib import Path
import random
import resource
import time as clock

from custody.dataset import sha256_file
from custody.models import ET
from .daily_replay import CALENDAR_PATH, CALENDAR_SHA256, iter_sessions, metrics
from .daily_signals import _valid_bar
from .event_replay import quantile
from .event_signals import prefix_at_checkpoint


SYMBOLS = ('AAPL', 'MSFT', 'NVDA', 'TSLA', 'META', 'AMZN', 'GOOGL', 'AMD', 'MU', 'INTC', 'AVGO')
CANDIDATES = ('Q2_BASE_945', 'Q2_DOWN_945')
START, END, HISTORY_START = '2020-01-02', '2024-05-31', '2019-11-01'
LAST_HISTORY = '2024-05-30'
PREREG_SHA256 = '9893cd96bc4f465cfde339c9ba8d16d7ff495ddda70591113677828f7c4d900c'
SEED, DRAWS = 20260926, 2000
# tag, subdirectory, checksum-list hash, manifest hash
SOURCES = (
    ('preopen-us-holdout-2016-v1', 'daily', '64383dc75c60e3bf8eef6c87b96a319e86b67e32d61849f9e82d4742225912d7',
     'dca4b7eaa84fd3f967ae75096c68f4cefe54619805e39b0d08c06be6ef9816d4'),
    ('preopen-us-train-v1', 'daily', 'dca1d6241507d48a1bf917af483acee6ca130afac72895f1c319955458d5f3bb',
     'c2d56e438bc2b10b23d02a0f9194f4ae3842f1ef7abfe18605e78a1418972ddc'),
    ('preopen-us-ext30-holdout-v1', 'ext30', '990ce3293d24dda71eb9ea82668c39f5aa4fa071445e2846cdf6b57d6450ce2c',
     'ebe73306bc7510e65cdc6f3b24a65f38596bd606fc84c6b03028d6c33b84c133'),
    ('preopen-us-ext30-select-v1', 'ext30', '2360ff1584010aeede834a8d011a72944e129338190803fef0738fbb27b63df7',
     'ea9d16bf2ba73469e24cba14763c75b01e824b03cb6b036a37f7c5386c40d141'),
    ('preopen-us-k5-select-v1', 'k5', '5531f0ccff46be6135b9c87457bebf79fd2ad1703182918ea2dbcb784bc6468d',
     '5f3fcd678b225502f8b096e93078145eed461147b4181da9fafc606879e82675'),
)
FIELDS = ('open', 'high', 'low', 'close', 'volume', 'turnover')
LABEL_KEYS = ('returns', 'paired', 'close_returns', 'close_paired')


def verify_sources(root, calendar_path):
    """Hash only the 55 registered CSVs and their provenance, never other assets."""
    root, inputs = Path(root).resolve(), {}
    for tag, folder, checksum, manifest in SOURCES:
        base = root / tag
        for name, expected in (('CHECKSUMS.sha256', checksum), ('manifest.json', manifest)):
            path = base / name
            if sha256_file(path) != expected:
                raise ValueError('AH1 provenance checksum mismatch: ' + str(path))
            inputs[str(path)] = expected
        pins = {}
        for line in (base / 'CHECKSUMS.sha256').read_text(encoding='utf-8').splitlines():
            if line.strip():
                digest, name = line.split(maxsplit=1)
                name = name.strip().lstrip('*')
                if name in pins:
                    raise ValueError('duplicate checksum entry: ' + name)
                pins[name] = digest
        for symbol in SYMBOLS:
            name = folder + '/' + symbol + '.csv'
            path = (base / name).resolve()
            if not path.is_relative_to(base.resolve()):
                raise ValueError('AH1 raw path outside its source: ' + str(path))
            digest = sha256_file(path)
            if pins.get(name) != digest:
                raise ValueError('AH1 raw checksum mismatch: ' + str(path))
            inputs[str(path)] = digest
    if sha256_file(calendar_path) != CALENDAR_SHA256:
        raise ValueError('AH1 calendar metadata checksum mismatch')
    inputs[str(Path(calendar_path).resolve())] = CALENDAR_SHA256
    return inputs


def read_calendar(path):
    calendar = {}
    with Path(path).open(newline='', encoding='utf-8') as handle:
        for row in csv.DictReader(handle):
            day = row['date']
            if not HISTORY_START <= day <= END:
                continue
            count = int(row['rows'])
            if (day != date.fromisoformat(day).isoformat() or day in calendar
                    or count not in (42, 78) or row['first_close'] != '09:35:00'
                    or row['last_close'] != ('13:00:00' if count == 42 else '16:00:00')
                    or int(row['missing_before_or_between']) != 0):
                raise ValueError('invalid AH1 calendar metadata')
            calendar[day] = count
    if not calendar:
        raise ValueError('empty AH1 calendar')
    return calendar


def numeric_rows(path, kind):
    """Keep original timestamps and six Decimal fields; malformed prices stay unknown."""
    previous = None
    with Path(path).open(newline='', encoding='utf-8') as handle:
        for row in csv.DictReader(handle):
            key = row['date' if kind == 'daily' else 'time_key']
            day = key[:10]
            if day > LAST_HISTORY:
                break
            if day < HISTORY_START:
                continue
            if kind == 'daily':
                if date.fromisoformat(key).isoformat() != key:
                    raise ValueError('invalid daily date')
            else:
                stamp = datetime.fromisoformat(key)
                if (stamp.tzinfo is not None or stamp.strftime('%Y-%m-%d %H:%M:%S') != key
                        or not time(4) <= stamp.time() <= time(20)
                        or stamp.minute not in (0, 30) or stamp.second):
                    raise ValueError('ext30 timestamp outside the registered time domain: ' + key)
            if previous is not None and key < previous:
                raise ValueError('unordered source: ' + str(path))
            previous = key
            values = []
            for field in FIELDS:
                try:
                    value = Decimal(row[field])
                except (InvalidOperation, KeyError):
                    value = Decimal('NaN')
                # Preserve invalid tokens for equality checks; they never become prices.
                values.append(value if value.is_finite() else ('invalid', row.get(field)))
            yield key, tuple(values), (str(path),)


def joined_rows(paths, kind, counts=None):
    streams = [numeric_rows(path, kind) for path in paths]
    for key, rows in groupby(heapq.merge(*streams, key=lambda row: row[0]), key=lambda row: row[0]):
        first = next(rows)
        sources = set(first[2])
        if counts is not None:
            counts['input_rows'] += 1
            counts['unique_rows'] += 1
        for duplicate in rows:
            if counts is not None:
                counts['input_rows'] += 1
                counts['duplicates_removed'] += 1
            if duplicate[1] != first[1]:
                raise ValueError('conflicting ' + kind + ' row ' + key + ': ' + ', '.join(sources | set(duplicate[2])))
            sources.update(duplicate[2])
        yield key, first[1], tuple(sorted(sources))


def source_paths(root, symbol, kind):
    return [Path(root) / tag / folder / (symbol + '.csv') for tag, folder, _, _ in SOURCES if folder == kind]


def preflight(root, calendar):
    """Finish every join/conflict check before any Q2 detection or future labels."""
    result = {}
    for kind in ('daily', 'ext30'):
        result[kind] = {}
        for symbol in SYMBOLS:
            counts = Counter(conflicts=0, duplicates_removed=0)
            for key, _, _ in joined_rows(source_paths(root, symbol, kind), kind, counts):
                if key[:10] not in calendar:
                    raise ValueError('source date absent from AH1 calendar: ' + key)
            result[kind][symbol] = dict(counts)
    return result


def valid_values(values):
    if values is None or any(not isinstance(value, Decimal) or not value.is_finite() for value in values[:4]):
        return False
    opening, high, low, close = values[:4]
    return (min(opening, high, low, close) > 0
            and low <= min(opening, close) <= max(opening, close) <= high
            and all(isfinite(float(value)) for value in values[:4]))


def history_context(history, today):
    """Only the original independent daily percentage-TR formula, with 21 days."""
    if len(history) != 21:
        return None
    if (any(not valid_values(values) or day >= today for day, values in history)
            or any(left[0] >= right[0] for left, right in zip(history, history[1:]))):
        raise ValueError('AH1 history must be ordered valid prior days')
    ranges = [(max(current[1][1], previous[1][3]) - min(current[1][2], previous[1][3]))
              / previous[1][3] for previous, current in zip(history, history[1:])]
    atr = float(sum(ranges) / Decimal(20))
    return {'atr20_pct': atr, 'previous_close': float(history[-1][1][3]),
            'history_first_date': history[0][0], 'previous_date': history[-1][0]}


def ah_background(rows, context, previous_half_day):
    rows = [row for row in rows if row[0][11:] > '16:00:00']
    expected = {'%02d:%02d:00' % (16 + index // 2, 30 * (index % 2)) for index in range(1, 9)}
    times = {row[0][11:] for row in rows}
    last = rows[-1] if rows else None
    zero = [isinstance(row[1][4], Decimal) and row[1][4] == 0 for row in rows]
    flags = {'ah_last_time': last[0] if last else None, 'ah_endpoint_2000': bool(last and last[0][11:] == '20:00:00'),
             'ah_grid_complete_8': times == expected, 'ah_missing_expected_bars': sorted(expected - times),
             'ah_last_zero_volume': zero[-1] if zero else None,
             'ah_any_zero_volume': any(zero), 'ah_all_zero_volume': bool(zero) and all(zero),
             'ah_last_flat_zero_volume': bool(last and zero[-1] and len(set(last[1][:4])) == 1),
             'previous_session_half_day': previous_half_day,
             'ah_last_sources': list(last[2]) if last else []}
    result = {'status': 'unknown', 'ah_return': None, 'ah_z': None, 'ah_last_close': None, 'quality': flags}
    if context is None or last is None or not valid_values(last[1]):
        return result
    atr = context['atr20_pct']
    if not isfinite(atr) or atr <= 0:
        return result
    change = float(last[1][3]) / context['previous_close'] - 1
    z = change / atr
    return result | {'status': 'pass' if abs(z) >= 1 else 'fail', 'ah_return': change,
                     'ah_z': z, 'ah_last_close': float(last[1][3])}


def freeze_events(day, contexts, backgrounds, current):
    """All candidates and peer lists use only history/AH and the 09:45 prefix."""
    prefixes = {symbol: prefix_at_checkpoint(current.get(symbol, []),
                 {'symbol': 'US.' + symbol, 'trade_date': day}, 15) for symbol in contexts}
    opening_down = sorted(symbol for symbol, prefix in prefixes.items()
                          if prefix is not None and prefix[-1].close < prefix[0].open)
    pending = []
    for symbol, context in contexts.items():
        background, prefix = backgrounds[symbol], prefixes[symbol]
        if background['status'] != 'pass':
            continue
        reference = prefix[-1].close if prefix else None
        common = {'symbol': 'US.' + symbol, 'trade_date': day, 'direction': 'SHORT',
                  'reference_time': datetime.combine(date.fromisoformat(day), time(9, 45), ET).isoformat(),
                  'reference': reference, 'reference_status': 'complete' if prefix else 'missing_reference',
                  'down_confirmation': ('pass' if symbol in opening_down else 'fail') if prefix else 'unknown',
                  'open_to_0945_descriptive': 1 - reference / prefix[0].open if prefix else None,
                  'prefix_zero_volume_bars': sum(bar.volume == 0 for bar in prefix) if prefix else None,
                  'reference_zero_volume': prefix[-1].volume == 0 if prefix else None,
                  'peers': [other for other in opening_down if other != symbol],
                  **context, **background}
        for candidate in CANDIDATES:
            if candidate == 'Q2_DOWN_945' and symbol not in opening_down:
                continue
            known = time(9) if candidate == 'Q2_BASE_945' else time(9, 45)
            pending.append(common | {'candidate': candidate,
                                     'known_at': datetime.combine(date.fromisoformat(day), known, ET).isoformat()})
    return pending


def terminal_label(bars, symbol, day, end_count):
    prefix = prefix_at_checkpoint(bars, {'symbol': 'US.' + symbol, 'trade_date': day}, 15)
    if prefix is None:
        return {'status': 'missing_reference', 'return': None}
    opening = datetime.combine(date.fromisoformat(day), time(9, 30), ET)
    cutoff = opening + timedelta(minutes=end_count * 5)
    future = [bar for bar in bars if prefix[-1].close_time < bar.close_time <= cutoff]
    if (len(future) != end_count - 3 or any(not _valid_bar(bar, '5m', 'US.' + symbol)
            or bar.close_time != opening + timedelta(minutes=5 * index)
            for index, bar in enumerate(future, 4))):
        return {'status': 'missing_future', 'return': None}
    return {'status': 'complete', 'return': 1 - future[-1].close / prefix[-1].close}


def evaluate_event(event, labels):
    own = labels[event['symbol'].removeprefix('US.')]
    result = {}
    for window in ('30m', 'to_close'):
        raw = own[window]
        peers = {symbol: labels[symbol][window] for symbol in event['peers']}
        reason = ('missing_event' if raw['return'] is None else 'no_peers' if not peers else
                  'missing_peer' if any(row['return'] is None for row in peers.values()) else 'complete')
        result[window] = dict(raw, peer_labels=peers, paired_status=reason,
                             paired_lift=(raw['return'] - fsum(row['return'] for row in peers.values()) / len(peers)
                                          if reason == 'complete' else None))
    return result


def day_record():
    return {'n_sessions': 0, 'signals': 0, **{key: [] for key in LABEL_KEYS}, 'open_to_0945': []}


def summarize(days, draws=DRAWS):
    keys, distributions = sorted(days), [[] for _ in LABEL_KEYS]
    rows = [tuple((fsum(days[day][key]), len(days[day][key])) for key in LABEL_KEYS) for day in keys]
    rng = random.Random(SEED)
    for _ in range(draws if rows else 0):
        sums, counts = [0.0] * 4, [0] * 4
        for _ in rows:
            for index, (total, count) in enumerate(rng.choice(rows)):
                sums[index] += total
                counts[index] += count
        for index in range(4):
            if counts[index]:
                distributions[index].append(10000 * sums[index] / counts[index])
    signals = sum(days[day]['signals'] for day in keys)
    active = sum(days[day]['signals'] > 0 for day in keys)
    result = {'n_dates': len(keys), 'signals': signals, 'active_dates': active,
              'eligible_history_sessions': sum(days[day]['n_sessions'] for day in keys)}
    for index, window in ((0, 'primary'), (2, 'to_close_descriptive')):
        raw_key, paired_key = LABEL_KEYS[index:index + 2]
        raw = metrics([value for day in keys for value in days[day][raw_key]])
        paired = metrics([value for day in keys for value in days[day][paired_key]])
        raw_q = .05 / 2 if index == 0 else .05
        raw['mean_lower_bp'] = quantile(distributions[index], raw_q)
        paired['mean_lower_bp'] = quantile(distributions[index + 1], .05)
        halves = {}
        for name, first in (('before_2022_06_01', True), ('from_2022_06_01', False)):
            selected = [day for day in keys if (day < '2022-06-01') == first]
            halves[name] = {'raw': metrics([v for day in selected for v in days[day][raw_key]]),
                            'paired': metrics([v for day in selected for v in days[day][paired_key]])}
        result[window] = {'signals': signals, 'raw': raw, 'paired': paired,
                          'missing_labels': signals - raw['labeled_signals'],
                          'paired_coverage': paired['labeled_signals'] / signals if signals else 0.0,
                          'missing_paired_labels': signals - paired['labeled_signals'], 'halves': halves,
                          'bootstrap': {'draws': draws if rows else 0, 'seed': SEED, 'unit': 'date',
                                        'raw_quantile': raw_q, 'paired_quantile': .05,
                                        'quantile_method': 'linear_(n-1)*q', 'shared_all_window_draws': True,
                                        'zero_signal_dates_included': True,
                                        'undefined_raw_draws': draws - len(distributions[index]) if rows else 0,
                                        'undefined_paired_draws': draws - len(distributions[index + 1]) if rows else 0}}
    main, positive = result['primary'], lambda value: value is not None and value > 0
    raw, paired = main['raw'], main['paired']
    pf = raw['profit_factor']
    result['gates'] = {'100_labeled_signals': raw['labeled_signals'] >= 100,
                       '60_active_dates': active >= 60,
                       'mean_at_least_5bp': raw['mean_bp'] is not None and raw['mean_bp'] >= 5,
                       'raw_adjusted_lower_positive': positive(raw['mean_lower_bp']),
                       'profit_factor_at_least_1_2': pf >= 1.2 if pf is not None else raw['wins'] > 0 and raw['losses'] == 0,
                       'both_halves_positive': all(positive(half['raw']['mean_bp']) for half in main['halves'].values()),
                       'paired_coverage_at_least_80pct': main['paired_coverage'] >= .8,
                       'paired_lower_positive': positive(paired['mean_lower_bp'])}
    result['development_eligible'] = all(result['gates'].values())
    result['open_to_0945_descriptive_only'] = metrics([v for day in keys for v in days[day]['open_to_0945']])
    return result


def _take_day(stream, pending, day):
    while pending is not None and pending[0] < day:
        pending = next(stream, None)
    value = pending[1] if pending is not None and pending[0] == day else None
    return value, pending


def _history_days(root, symbol, kind):
    for day, rows in groupby(joined_rows(source_paths(root, symbol, kind), kind), key=lambda row: row[0][:10]):
        yield day, list(rows)


def replay(root=Path('data'), calendar_path=CALENDAR_PATH, emit=None):
    started, root = clock.monotonic(), Path(root)
    prereg = Path(__file__).with_name('notes') / 'AH1_PREREG.md'
    if sha256_file(prereg) != PREREG_SHA256:
        raise ValueError('AH1 preregistration checksum mismatch')
    inputs = verify_sources(root, calendar_path)
    calendar = read_calendar(calendar_path)
    joins = preflight(root, calendar)
    streams, heads = {}, {}
    for symbol in SYMBOLS:
        for kind in ('daily', 'ext30', 'k5'):
            stream = (_history_days(root, symbol, kind) if kind != 'k5' else
                      ((day, bars) for day, _, bars, _ in iter_sessions(source_paths(root, symbol, kind)[0], symbol, calendar)))
            streams[symbol, kind] = stream
            heads[symbol, kind] = next(stream, None)
    history = {symbol: deque(maxlen=21) for symbol in SYMBOLS}
    previous_ah = {symbol: [] for symbol in SYMBOLS}
    days = {name: {day: day_record() for day in sorted(calendar) if START <= day <= END} for name in CANDIDATES}
    coverage, overlap = {symbol: Counter() for symbol in SYMBOLS}, 0
    previous_day = None
    for day in sorted(calendar):
        if day >= START:
            contexts, backgrounds, current = {}, {}, {}
            for symbol in SYMBOLS:
                key = symbol, 'k5'
                current[symbol], heads[key] = _take_day(streams[key], heads[key], day)
                current[symbol] = current[symbol] or []
                context = history_context(list(history[symbol]), day)
                if context is not None:
                    contexts[symbol] = context
                    backgrounds[symbol] = ah_background(previous_ah[symbol], context, calendar[previous_day] == 42)
                    coverage[symbol]['background_' + backgrounds[symbol]['status']] += 1
                    for candidate in CANDIDATES:
                        days[candidate][day]['n_sessions'] += 1
                else:
                    coverage[symbol]['missing_history'] += 1
            pending = freeze_events(day, contexts, backgrounds, current)
            # All candidate and peer memberships are now fixed, before any labels.
            needed = {event['symbol'].removeprefix('US.') for event in pending}
            needed.update(peer for event in pending for peer in event['peers'])
            labels = {symbol: {'30m': terminal_label(current[symbol], symbol, day, 9),
                               'to_close': terminal_label(current[symbol], symbol, day, calendar[day])}
                      for symbol in needed}
            overlap += sum(event['candidate'] == 'Q2_DOWN_945' for event in pending)
            for event in pending:
                name, symbol = event['candidate'], event['symbol'].removeprefix('US.')
                record, quality = days[name][day], evaluate_event(event, labels)
                record['signals'] += 1
                coverage[symbol][name] += 1
                for window, raw_key, paired_key in (('30m', 'returns', 'paired'), ('to_close', 'close_returns', 'close_paired')):
                    row = quality[window]
                    if row['return'] is not None:
                        record[raw_key].append(row['return'])
                    if row['paired_lift'] is not None:
                        record[paired_key].append(row['paired_lift'])
                if event['open_to_0945_descriptive'] is not None:
                    record['open_to_0945'].append(event['open_to_0945_descriptive'])
                if emit is not None:
                    emit(event | {'labels': quality, 'source_equivalence': 'unverified'})
        # Original daily/AH from this date become available only to the next date.
        for symbol in SYMBOLS:
            for kind in ('daily', 'ext30'):
                key = symbol, kind
                rows, heads[key] = _take_day(streams[key], heads[key], day)
                if kind == 'daily':
                    if rows and valid_values(rows[0][1]):
                        history[symbol].append((day, rows[0][1]))
                    else:
                        history[symbol].clear()
                else:
                    previous_ah[symbol] = rows or []
        previous_day = day
    results = {name: summarize(days[name]) for name in CANDIDATES}
    eligible = [name for name in CANDIDATES if results[name]['development_eligible']]
    selected = min(eligible, key=lambda name: (-results[name]['primary']['paired']['mean_lower_bp'],
                   -results[name]['primary']['raw']['mean_lower_bp'], name)) if eligible else None
    repo = Path(__file__).resolve().parents[2]
    names = ('ah_replay.py', 'daily_replay.py', 'daily_signals.py', 'event_replay.py', 'event_signals.py',
             'context_replay.py', 'context_signals.py', 'context_stats.py')
    files = [Path(__file__).with_name(name) for name in names] + [repo / 'custody' / (name + '.py') for name in ('dataset', 'marketdata', 'models')]
    return {'study': 'AH1', 'status': 'EXPOSED_DEVELOPMENT_SIGNAL_QUALITY_ONLY',
            'created_at': datetime.now(timezone.utc).isoformat(), 'selected_for_migration': selected,
            'preregistration_sha256': PREREG_SHA256, 'inputs': inputs,
            'code_sha256': {str(path.relative_to(repo)): sha256_file(path) for path in files},
            'join_quality': joins, 'source_equivalence': 'unverified', 'candidates': results,
            'coverage_by_symbol': coverage, 'overlapping_base_down_signals': overlap, 'by_day': days,
            'limitations': ['已暴露开发段，不是独立验证或首次发现。', '仅正股方向标签，无费用、成交或期权购买收益。',
                            '历史逐日0DTE资格未知，不能用星期代替挂牌。', 'BASE与opening-down对照的差值不是纯注意力因果效应。',
                            '原独立日线与K5未认证全部价格基准；旧AH最后可见端点不等于完整盘后。',
                            '到收盘与开盘至09:45仅描述，不能救活30分钟主口径。'],
            'resources': {'elapsed_seconds': clock.monotonic() - started,
                          'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--calendar', type=Path, default=CALENDAR_PATH)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--signals-out', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists() or args.signals_out.exists() or args.out.resolve() == args.signals_out.resolve():
        parser.error('outputs must be separate new files; refusing to overwrite')
    args.signals_out.parent.mkdir(parents=True, exist_ok=True)
    with args.signals_out.open('x', encoding='utf-8') as events:
        result = replay(args.data_root, args.calendar,
                        lambda event: events.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + '\n'))
    result['signal_events'] = {'path': str(args.signals_out), 'sha256': sha256_file(args.signals_out)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write('\n')


if __name__ == '__main__':
    main()
