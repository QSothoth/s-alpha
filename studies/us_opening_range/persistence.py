"""Descriptive fixed-event 30m/60m/RTH-close audit; no new signal selection."""
import argparse
from collections import Counter
from datetime import datetime, time, timedelta, timezone
import heapq
import json
from math import fsum, isfinite
from pathlib import Path
import resource
import time as clock

from custody.dataset import sha256_file
from custody.models import ET
from .context_replay import SYMBOLS, verify_inputs
from .daily_replay import CALENDAR_PATH, CALENDAR_SHA256, INPUT_SHA256, iter_sessions, read_calendar
from .daily_signals import _valid_bar, evaluate_signal_quality
from .event_replay import verify_small
from .event_signals import prefix_at_checkpoint


REPO = Path(__file__).resolve().parents[2]
PREREG_SHA256 = 'b297fb6d5876e57a9e291990a5ac79fedd4b3115db6a7299efa3889b798c4f29'
DS1_SHA256 = 'a56fb5d964daf9954ef7fbd1f1af457fcbb8b0065289bbc1d6ae873bf8ec1004'
DS2_SHA256 = '6d9c4b5b7bdb97627d02f921ea01d0a9bf6c67e7dcafd4e1371de15549f5b2ec'
DS2_REPORT_SHA256 = '458314927ad18ca9645a72799a1050d4c183f2463c171905c13a77d9a0535e0e'
DS2_PREREG_SHA256 = '1ebb0641738f688cba538e6b35b69a25e6da9379121423cbf9414385956cb19b'
SOURCE_PINS = {
    'studies/us_opening_range/event_signals.py': 'c891d118a5fa8995f8ac77825d33c286ee3c5d9686f373b6a672037880c81d44',
    'studies/us_opening_range/event_replay.py': 'ac7e99c5779b297f52d27267303339031416e72f8f0acdeeb0a732226bee33ac'}
CLASSES = ('PD_BREAK', 'B20_BREAK', 'G20_HOLD', 'F20_FAIL')
HORIZONS = ('30m', '60m', 'close')
DS1_EVENTS = REPO / 'data/ds1-development-signals-20260925.jsonl'
DS2_EVENTS = REPO / 'data/ds2-development-signals-20260926.jsonl'
DS2_REPORT = REPO / 'studies/us_opening_range/reports/ds2_development.json'


def load_inputs(root, small_root, calendar_path, ds1_events, ds2_events, ds2_report):
    checks = {Path(__file__).with_name('notes') / 'PERSISTENCE_PREREG.md': PREREG_SHA256,
              Path(__file__).with_name('notes') / 'DS2_PREREG.md': DS2_PREREG_SHA256,
              Path(root) / 'CHECKSUMS.sha256': INPUT_SHA256,
              Path(ds1_events): DS1_SHA256, Path(ds2_events): DS2_SHA256,
              Path(ds2_report): DS2_REPORT_SHA256}
    for path, digest in checks.items():
        if sha256_file(path) != digest:
            raise ValueError('persistence input fingerprint mismatch: ' + str(path))
    report = json.loads(Path(ds2_report).read_text(encoding='utf-8'))
    artifact, source_code = report['signals_artifact'], report['code_sha256']
    if (report['study'] != 'DS2' or report['preregistration_sha256'] != DS2_PREREG_SHA256
            or artifact['sha256'] != DS2_SHA256 or Path(artifact['path']).resolve() != Path(ds2_events).resolve()
            or any(source_code.get(name) != digest for name, digest in SOURCE_PINS.items())):
        raise ValueError('DS2 source run identity mismatch')
    for name, digest in source_code.items():
        path = (REPO / name).resolve()
        if not path.is_relative_to(REPO) or sha256_file(path) != digest:
            raise ValueError('DS2 reported source code changed: ' + name)
    small, small_input = verify_small(small_root)
    inputs = {'large': verify_inputs(root), 'smallmid': small_input,
              'calendar_metadata_sha256': CALENDAR_SHA256}
    if inputs != report['inputs']:
        raise ValueError('source tapes differ from the frozen DS2 run')
    calendar = read_calendar(calendar_path)
    return tuple(SYMBOLS) + tuple(small), calendar, dict(inputs, ds1_events_sha256=DS1_SHA256,
        ds2_events_sha256=DS2_SHA256, ds2_report_sha256=DS2_REPORT_SHA256), source_code


def iter_events(path, study, symbols):
    previous, seen = None, set()
    with Path(path).open(encoding='utf-8') as handle:
        for line in handle:
            event = json.loads(line)
            stamp = datetime.fromisoformat(event['time'])
            if stamp.tzinfo is None:
                raise ValueError('event timestamp must be timezone-aware')
            local, name = stamp.astimezone(ET), event['candidate']
            day = local.date().isoformat()
            if previous is not None and day < previous:
                raise ValueError('unordered event dates')
            if day != previous:
                seen.clear()
            previous = day
            allowed = ('PD_BREAK', 'NR7_BREAK', 'INSIDE_BREAK') if study == 'DS1' else CLASSES[1:]
            if name not in allowed:
                raise ValueError('unregistered event candidate')
            if study == 'DS1' and name != 'PD_BREAK':
                continue
            minutes = event['snapshot_minutes']
            key = (name, event['symbol'])
            if (not '2020-01-02' <= day <= '2024-05-31' or key in seen
                    or event['symbol'] not in {'US.' + symbol for symbol in symbols}
                    or event['direction'] not in ('LONG', 'SHORT') or minutes not in (15, 20, 30)
                    or local != datetime.combine(local.date(), time(9, 30), ET) + timedelta(minutes=minutes)
                    or any(not isfinite(event[field]) or event[field] <= 0 for field in ('reference', 'atr', 'risk'))):
                raise ValueError('invalid fixed event identity or reference')
            seen.add(key)
            if study == 'DS2':
                peers = event['peers']
                if (not isinstance(peers, list) or len(set(peers)) != len(peers)
                        or any(peer not in symbols or 'US.' + peer == event['symbol'] for peer in peers)
                        or len(event['peer_returns']) != len(peers)):
                    raise ValueError('invalid frozen peer list')
            yield day, dict(event, origin_study=study)


def path_label(bars, event, end):
    start = datetime.fromisoformat(event['time'])
    future = [bar for bar in bars if start < bar.close_time <= end]
    result = dict.fromkeys(('return', 'return_atr', 'mfe_atr', 'mae_atr', 'direction_efficiency',
                           'end_price', 'zero_volume_bars'))
    result.update(status='missing_future', end_time=end.isoformat(), minutes=(end - start).total_seconds() / 60)
    count = int((end - start).total_seconds() / 300)
    if (count <= 0 or len(future) != count or start + timedelta(minutes=5 * count) != end
            or any(not _valid_bar(bar, '5m', event['symbol'])
                   or bar.close_time != start + timedelta(minutes=5 * index)
                   for index, bar in enumerate(future, 1))):
        return result
    sign, reference, atr = (1 if event['direction'] == 'LONG' else -1), event['reference'], event['atr']
    closes = [reference] + [bar.close for bar in future]
    variation = fsum(abs(after - before) for before, after in zip(closes, closes[1:]))
    displacement = sign * (closes[-1] - reference)
    return result | {'status': 'complete', 'return': sign * (closes[-1] / reference - 1),
        'return_atr': displacement / atr, 'end_price': closes[-1],
        'mfe_atr': max(0, *(sign * ((bar.high if sign == 1 else bar.low) - reference) for bar in future)) / atr,
        'mae_atr': max(0, *(-sign * ((bar.low if sign == 1 else bar.high) - reference) for bar in future)) / atr,
        'direction_efficiency': displacement / variation if variation else None,
        'zero_volume_bars': sum(bar.volume == 0 for bar in future)}


def _same(actual, expected):
    if actual is None or expected is None or isinstance(actual, str) or isinstance(expected, str):
        return actual == expected
    return isfinite(actual) and isfinite(expected) and abs(actual - expected) <= 1e-12


def label_event(event, current, session_bars):
    if session_bars not in (42, 78):
        raise ValueError('RTH close must come from the frozen full/half-day calendar')
    stamp = datetime.fromisoformat(event['time'])
    ends = (stamp + timedelta(minutes=30), stamp + timedelta(minutes=60),
            datetime.combine(stamp.astimezone(ET).date(), time(13 if session_bars == 42 else 16), ET))
    rows = current.get(event['symbol'].removeprefix('US.'), [])
    prefix = prefix_at_checkpoint(rows, {'symbol': event['symbol'], 'trade_date': stamp.astimezone(ET).date().isoformat()}, event['snapshot_minutes'])
    if prefix is None or not _same(prefix[-1].close, event['reference']):
        raise ValueError('frozen event reference does not match the source prefix')
    original = evaluate_signal_quality(rows, event)
    if any(not _same(original[key], event.get(key)) for key in original):
        raise ValueError('original 30-minute label does not reconcile')
    labels = {name: path_label(rows, event, end) for name, end in zip(HORIZONS, ends)}
    if not _same(labels['30m']['return'], event['return_30m']):
        raise ValueError('audit 30-minute return does not reconcile')
    for key, original_key, scale in (('return_atr', 'return_atr', 1),
                                     ('mfe_atr', 'mfe_r', event['atr'] / event['risk']),
                                     ('mae_atr', 'mae_r', event['atr'] / event['risk'])):
        value = labels['30m'][key]
        if not _same(value * scale if value is not None else None, event[original_key]):
            raise ValueError('audit 30-minute excursion does not reconcile')
    for name, end in zip(HORIZONS, ends):
        label = labels[name]
        peer_returns = []
        for peer in event['peers'] if event['origin_study'] == 'DS2' else []:
            peer_rows = current.get(peer, [])
            prefix = prefix_at_checkpoint(peer_rows, {'symbol': 'US.' + peer,
                'trade_date': stamp.astimezone(ET).date().isoformat()}, event['snapshot_minutes'])
            peer_event = event | {'symbol': 'US.' + peer, 'reference': prefix[-1].close if prefix else 1}
            peer_returns.append(path_label(peer_rows, peer_event, end)['return'] if prefix else None)
        paired_ok = label['status'] == 'complete' and bool(peer_returns) and all(value is not None for value in peer_returns)
        label.update(peer_returns=peer_returns, paired_status=('not_applicable' if event['origin_study'] == 'DS1'
                     else 'complete' if paired_ok else 'missing'),
                     paired_lift=label['return'] - fsum(peer_returns) / len(peer_returns) if paired_ok else None)
    if event['origin_study'] == 'DS2' and (labels['30m']['paired_status'] != event['paired_status']
            or not _same(labels['30m']['paired_lift'], event['paired_lift'])
            or any(not _same(actual, expected) for actual, expected in zip(labels['30m']['peer_returns'], event['peer_returns']))):
        raise ValueError('original 30-minute frozen-peer labels do not reconcile')
    common = all(label['status'] == 'complete' for label in labels.values())
    increments = {}
    if common:
        sign = 1 if event['direction'] == 'LONG' else -1
        for name, before, after in (('30_to_60', '30m', '60m'), ('60_to_close', '60m', 'close')):
            delta = sign * (labels[after]['end_price'] - labels[before]['end_price'])
            increments[name] = {'return': delta / event['reference'], 'return_atr': delta / event['atr']}
    return dict(event, horizons=labels, common_complete=common, increments=increments)


def add(tally, label):
    tally['signals'] += 1
    if label['status'] != 'complete':
        return
    tally['valid'] += 1
    value = label['return']
    tally['wins'] += value > 0
    tally['losses'] += value < 0
    tally['profit'] += max(0, value)
    tally['loss'] += max(0, -value)
    for key in ('return', 'return_atr', 'mfe_atr', 'mae_atr', 'direction_efficiency', 'paired_lift', 'zero_volume_bars'):
        if label[key] is not None:
            tally[key + '_sum'] += label[key]
            tally[key + '_count'] += 1


def summary(tally):
    n, wins, losses = tally['valid'], tally['wins'], tally['losses']
    result = dict(tally, signals=tally['signals'], valid=n, missing=tally['signals'] - n,
                  wins=wins, losses=losses, zeros=n - wins - losses,
                  win_rate=wins / n if n else None,
                  average_win_bp=10000 * tally['profit'] / wins if wins else None,
                  average_loss_bp=10000 * tally['loss'] / losses if losses else None,
                  payoff_ratio=(tally['profit'] / wins) / (tally['loss'] / losses) if wins and losses else None,
                  profit_factor=tally['profit'] / tally['loss'] if tally['loss'] else None)
    for key in ('return', 'return_atr', 'mfe_atr', 'mae_atr', 'direction_efficiency', 'paired_lift'):
        result['mean_' + key] = tally[key + '_sum'] / tally[key + '_count'] if tally[key + '_count'] else None
    result['mean_bp'] = result['mean_return'] * 10000 if n else None
    return result


def replay(root, small_root, calendar_path=CALENDAR_PATH, ds1_events=DS1_EVENTS,
           ds2_events=DS2_EVENTS, ds2_report=DS2_REPORT, emit=None):
    started = clock.monotonic()
    symbols, calendar, inputs, source_code = load_inputs(root, small_root, calendar_path, ds1_events, ds2_events, ds2_report)
    events = iter(heapq.merge(iter_events(ds1_events, 'DS1', SYMBOLS), iter_events(ds2_events, 'DS2', symbols), key=lambda row: row[0]))
    pending = next(events, None)
    streams = {symbol: iter(iter_sessions(Path(root if symbol in SYMBOLS else small_root) / 'k5' / (symbol + '.csv'), symbol, calendar)) for symbol in symbols}
    heads = dict.fromkeys(symbols)
    totals = {name: {horizon: Counter() for horizon in HORIZONS} for name in CLASSES}
    common = {name: {'signals': 0, 'increments': {part: Counter() for part in ('30_to_60', '60_to_close')}, 'endpoint_sign_patterns': Counter()} for name in CLASSES}
    by_day = {}
    for day in sorted(calendar):
        current = {}
        for symbol in symbols:
            head = heads[symbol] or next(streams[symbol], None)
            while head is not None and head[0] < day:
                if head[0] >= '2020-01-02' and head[0] not in calendar:
                    raise ValueError('price date outside frozen calendar')
                head = next(streams[symbol], None)
            if head is not None and head[0] == day:
                current[symbol], heads[symbol] = head[2], None
            else:
                heads[symbol] = head
        by_day[day] = {name: {h: Counter(signals=0, valid=0, return_sum=0.0) for h in HORIZONS} for name in CLASSES}
        if pending is not None and pending[0] < day:
            raise ValueError('event date outside frozen calendar')
        while pending is not None and pending[0] == day:
            labeled = label_event(pending[1], current, calendar[day])
            name = labeled['candidate']
            for horizon, label in labeled['horizons'].items():
                add(totals[name][horizon], label)
                add(by_day[day][name][horizon], label)
            if labeled['common_complete']:
                cohort = common[name]
                cohort['signals'] += 1
                pattern = ''.join('+' if row['return'] > 0 else '-' if row['return'] < 0 else '0' for row in labeled['horizons'].values())
                cohort['endpoint_sign_patterns'][pattern] += 1
                for part, values in labeled['increments'].items():
                    counter = cohort['increments'][part]
                    counter['return_sum'] += values['return']
                    counter['atr_sum'] += values['return_atr']
                    counter['positive' if values['return'] > 0 else 'negative' if values['return'] < 0 else 'zero'] += 1
            if emit is not None:
                emit(labeled)
            pending = next(events, None)
        current.clear()
    if pending is not None:
        raise ValueError('unconsumed events outside calendar')
    for cohort in common.values():
        n = cohort['signals']
        cohort['same_endpoint_sign'] = sum(count for pattern, count in cohort['endpoint_sign_patterns'].items() if len(set(pattern)) == 1)
        cohort['both_positive_negative_endpoints'] = sum(count for pattern, count in cohort['endpoint_sign_patterns'].items() if '+' in pattern and '-' in pattern)
        for counter in cohort['increments'].values():
            counter['mean_bp'] = 10000 * counter['return_sum'] / n if n else None
            counter['mean_atr'] = counter['atr_sum'] / n if n else None
    return {'study': 'PERSISTENCE', 'status': 'DESCRIPTIVE_ONLY_NO_SELECTION', 'inputs': inputs,
            'preregistration_sha256': PREREG_SHA256, 'source_code_sha256': source_code,
            'code_sha256': dict(source_code, **{str(Path(__file__).relative_to(REPO)): sha256_file(__file__)}),
            'classes': {name: {h: summary(tally) for h, tally in rows.items()} for name, rows in totals.items()},
            'common_complete': common, 'by_day': by_day, 'created_at': datetime.now(timezone.utc).isoformat(),
            'resources': {'elapsed_seconds': clock.monotonic() - started, 'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss},
            'limitations': ['Fixed exposed-development events; original 30-minute decisions unchanged.',
                            'No selection, bootstrap, fills or option profitability inference.',
                            'Endpoint signs are not continuous trend survival; bar extremes are not executable prices.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name, default in (('root', 'data/preopen-us-k5-select-v1'), ('small-root', 'data/preopen-s20-select-v1'),
                          ('calendar', CALENDAR_PATH), ('ds1-events', DS1_EVENTS), ('ds2-events', DS2_EVENTS), ('ds2-report', DS2_REPORT)):
        parser.add_argument('--' + name, type=Path, default=Path(default))
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--labels-out', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists() or args.labels_out.exists() or args.out.resolve() == args.labels_out.resolve():
        parser.error('outputs must be distinct new paths')
    with args.labels_out.open('x', encoding='utf-8') as handle:
        result = replay(args.root, args.small_root, args.calendar, args.ds1_events, args.ds2_events, args.ds2_report,
                        emit=lambda row: handle.write(json.dumps(row, sort_keys=True, allow_nan=False) + '\n'))
    result['labels_artifact'] = {'path': str(args.labels_out), 'sha256': sha256_file(args.labels_out)}
    with args.out.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps({'study': result['study'], 'status': result['status'], 'resources': result['resources']}))


if __name__ == '__main__':
    main()
