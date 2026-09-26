"""OM1: fixed DS1 observations versus real 0DTE trade-close marks, not fills."""
from __future__ import annotations

import argparse
from collections import Counter, deque
import csv
from datetime import date, datetime, timedelta, timezone
from itertools import groupby
import json
from pathlib import Path
import resource
import time

from custody.dataset import Dataset, DatasetError, sha256_file
from custody.marketdata import Bar
from custody.models import ET, instant
from .daily_replay import aggregate_daily, complete_session, metrics, CALENDAR_PATH, CALENDAR_SHA256
from .daily_signals import CANDIDATES, daily_levels, detect_signals, evaluate_signal_quality
from .replay import paired_sessions


PREREG_SHA256 = '56e539f8012091eb9985af498908df579f4b9f4a80dee437909309a6b3e5408b'
START, END = '2026-07-21', '2026-09-18'
SYMBOLS = ('AAPL', 'AMD', 'AMZN', 'AVGO', 'GOOGL', 'INTC', 'IWM', 'META',
           'MSFT', 'MU', 'NVDA', 'QQQ', 'SNDK', 'SPY', 'TSLA')
PINS = {
    'custody-0dte-v5': {
        'CHECKSUMS.sha256': '35875e44318c78ab5b09cd53cac3b22ce26a8a12cb468aeed5efd72e43e97c69',
        'manifest.json': 'c97c7baeee4f69b1fb7c44e454734ae5355c187efc04e359320ddf0ce7cb806d',
        'cases.json': '8871b611e28a94ed1b4348031ae720c658b7b50b7c57620448f20a0b10b1fd81'},
    'custody-eval-2026-09-18-v2': {
        'CHECKSUMS.sha256': 'fba36ab960189e6fe80660629455774627915d1b8982361a324ec203892fc2c0',
        'manifest.json': 'ac1091d4eddf18505668b1651709b1c9a4a7aa248fda495de272bfaf7a363736',
        'cases.json': '5e341b917c29e646d1686b1ee0a7190f25e742c8e3eb60ffa68751b5a9db838a'},
    'preopen-us-k5-valid-v1': {
        'CHECKSUMS.sha256': '992ad5f444b9eb36de05a15cd882e28e68466eca1769f5917e9704e673f73da0',
        'manifest.json': '7e424e4d78024fcfd1c0f6769c40646dfbc616d30d3ea3e8881fd8d3b1e88528'}}
ENGINE_PINS = {
    'daily_signals.py': '1568d3ac0f4cc65270be73ceec9e157789f5a4577fcc99882e8b3511963ef91a',
    'daily_replay.py': '80ebf94b35e99ef8f28af172e01c4f00bc2389c3341b07e875a4b5954241955d'}


def load_inputs(data_root):
    root, cases, inputs = Path(data_root), {}, {}
    prereg = Path(__file__).with_name('notes') / 'OM1_PREREG.md'
    if sha256_file(prereg) != PREREG_SHA256:
        raise ValueError('OM1 preregistration changed')
    for name, digest in ENGINE_PINS.items():
        if sha256_file(Path(__file__).with_name(name)) != digest:
            raise ValueError('DS1 engine changed: ' + name)
    for name, pins in PINS.items():
        for relative, digest in pins.items():
            path = root / name / relative
            if path.is_symlink() or sha256_file(path) != digest:
                raise ValueError('OM1 input mismatch: ' + str(path))
        inputs[name] = dict(pins)
        if name == 'preopen-us-k5-valid-v1':
            continue
        dataset = Dataset(root / name)
        for key, pair in paired_sessions(dataset):
            if key in cases:
                raise ValueError('duplicate symbol/session')
            cases[key] = (dataset, pair)
    if (len(cases) != 77 or len({day for _, day in cases}) != 21
            or {symbol.removeprefix('US.') for symbol, _ in cases} != set(SYMBOLS)
            or min(day for _, day in cases) != '2026-08-18' or max(day for _, day in cases) != END):
        raise ValueError('OM1 requires the fixed 77 sessions / 21 dates / 15 symbols')
    history = root / 'preopen-us-k5-valid-v1'
    pins = {}
    for line in (history / 'CHECKSUMS.sha256').read_text().splitlines():
        digest, relative = line.split('  ', 1)
        if relative in pins:
            raise ValueError('duplicate history pin')
        pins[relative] = digest
    for symbol in SYMBOLS:
        relative = 'k5/' + symbol + '.csv'
        path = history / relative
        if path.is_symlink() or pins.get(relative) != sha256_file(path):
            raise ValueError('OM1 history mismatch: ' + relative)
        inputs['preopen-us-k5-valid-v1'][relative] = pins[relative]
    calendar_path = root / CALENDAR_PATH.relative_to('data')
    if sha256_file(calendar_path) != CALENDAR_SHA256:
        raise ValueError('OM1 calendar changed')
    calendar = {}
    with calendar_path.open(newline='', encoding='utf-8') as handle:
        for row in csv.DictReader(handle):
            day, count = row['date'], int(row['rows'])
            if not START <= day <= END:
                continue
            if (day in calendar or calendar and day <= next(reversed(calendar))
                    or count not in (42, 78) or row['first_close'] != '09:35:00'
                    or row['last_close'] != ('13:00:00' if count == 42 else '16:00:00')
                    or int(row['missing_before_or_between']) != 0):
                raise ValueError('invalid OM1 calendar')
            calendar[day] = count
    if (not calendar or min(calendar) != START or max(calendar) != END
            or sum(day < '2026-08-18' for day in calendar) != 20
            or any(day not in calendar for _, day in cases)):
        raise ValueError('OM1 calendar coverage mismatch')
    inputs['calendar'] = {'path': str(calendar_path), 'sha256': CALENDAR_SHA256}
    return cases, calendar, inputs


def history_sessions(path, symbol, calendar):
    """Read a bounded date range; later bad rows cannot erase an earlier prefix."""
    previous_day = None
    with Path(path).open(newline='', encoding='utf-8') as handle:
        reader = csv.DictReader(handle)
        if not {'time_key', 'open', 'high', 'low', 'close', 'volume'} <= set(reader.fieldnames or ()):
            raise ValueError('missing required history columns')
        for day, rows in groupby(reader, key=lambda row: row['time_key'][:10]):
            if day > END:
                break  # No price conversion outside the fixed range.
            if day < START:
                continue
            if day not in calendar or previous_day is not None and day <= previous_day:
                raise ValueError('invalid history date order or calendar')
            previous_day, bars, valid, count, previous = day, [], True, 0, None
            for row in rows:
                count += 1
                stamp = datetime.fromisoformat(row['time_key'])
                if (stamp.tzinfo is not None or 'code' in row and row['code'] != 'US.' + symbol
                        or previous is not None and stamp <= previous):
                    raise ValueError('unexpected symbol, timezone or duplicate/unordered history time')
                previous = stamp
                if count > 78:
                    valid = False
                    continue
                try:
                    bar = Bar('US.' + symbol, stamp.replace(tzinfo=ET),
                              *(float(row[key]) for key in ('open', 'high', 'low', 'close', 'volume')),
                              interval='5m', source='opend_qfq_5m')
                    if min(bar.open, bar.high, bar.low, bar.close) <= 0:
                        raise ValueError('nonpositive price')
                    bars.append(bar)
                except (KeyError, TypeError, ValueError):
                    valid = False
            yield day, bars, valid and complete_session(bars, calendar[day])


def endpoint_bars(dataset, kind, code, at):
    """Read only two pinned 1m marks; non-endpoint gaps are irrelevant here."""
    path = (dataset.root / kind / (code + '.csv')).resolve()
    if path not in dataset._pinned:
        raise DatasetError('unpinned bridge series')
    end, found = at + timedelta(minutes=30), {}
    with path.open(newline='', encoding='utf-8') as handle:
        for row in csv.DictReader(handle):
            stamp = instant(row['close_time'])
            if stamp > end:
                break
            if stamp not in (at, end):
                continue
            if stamp in found or row['code'] != code or row['interval'] != '1m':
                raise DatasetError('duplicate or invalid bridge endpoint')
            found[stamp] = Bar(code, stamp, *(float(row[key]) for key in
                                ('open', 'high', 'low', 'close', 'volume')), source='frozen')
    return list(found.values())


def complete_prefix(bars, day, symbol):
    opening = datetime.fromisoformat(day).replace(hour=9, minute=30, tzinfo=ET)
    prefix = [bar for bar in bars if bar.close_time <= opening + timedelta(minutes=30)]
    return len(prefix) == 6 and all(bar.code == 'US.' + symbol and bar.interval == '5m'
        and bar.close_time == opening + timedelta(minutes=5 * index)
        for index, bar in enumerate(prefix, 1))


def fixed_marks(bars, at, *, require_volume=True):
    """Two exact traded closes, never fills; do not search nearby minutes."""
    end = at + timedelta(minutes=30)
    points = []
    missing = []
    for name, stamp in (('reference', at), ('future', end)):
        matches = [bar for bar in bars if bar.close_time == stamp]
        point = matches[0] if len(matches) == 1 else None
        if point is None or point.close <= 0 or require_volume and point.volume <= 0:
            missing.append(name)
            points.append(None)
        else:
            points.append(point.close)
    return {'status': 'missing' if missing else 'complete', 'missing': missing,
            'reference_time': at.isoformat(), 'future_time': end.isoformat(),
            'reference_close': points[0], 'future_close': points[1],
            'mark_return_30m': None if missing else points[1] / points[0] - 1}


def summarize(records):
    result = {}
    for name in CANDIDATES:
        rows = [row for row in records if row['candidate'] == name]
        signals = [row for row in rows if row['signal'] is not None]
        underlying = [row['underlying']['return_30m'] for row in signals
                      if row['underlying']['return_30m'] is not None]
        option = [row['option']['mark_return_30m'] for row in signals
                  if row['option']['mark_return_30m'] is not None]
        joint, paths = Counter(), Counter()
        for row in signals:
            u, o = row['underlying']['return_30m'], row['option']['mark_return_30m']
            paths[row['underlying']['path_status'] or 'missing'] += 1
            if u is not None and o is not None:
                sign = lambda value: 'positive' if value > 0 else 'negative' if value < 0 else 'zero'
                joint[sign(u) + '_underlying__' + sign(o) + '_option'] += 1
        result[name] = {
            'sessions': len(rows), 'history_eligible_sessions': sum(row['history_eligible'] for row in rows),
            'current_prefix_incomplete_sessions': sum(not row['current_prefix_complete'] for row in rows),
            'signals': len(signals), 'active_dates': len({row['trade_date'] for row in signals}),
            'underlying': metrics(underlying), 'option_gross_marks': metrics(option),
            'underlying_missing_labels': len(signals) - len(underlying),
            'option_missing_labels': len(signals) - len(option),
            'option_mark_coverage': len(option) / len(signals) if signals else None,
            'joint_label_counts': dict(joint), 'underlying_path_counts': dict(paths)}
    return result


def replay(data_root=Path('data')):
    started = time.monotonic()
    cases, calendar, inputs = load_inputs(data_root)
    records, coverage = [], {}
    for symbol in SYMBOLS:
        history, counts = deque(maxlen=20), Counter()
        stream = iter(history_sessions(Path(data_root) / 'preopen-us-k5-valid-v1/k5' / (symbol + '.csv'), symbol, calendar))
        current = next(stream, None)
        for day in calendar:
            bars, complete = [], False
            if current is not None and current[0] == day:
                _, bars, complete = current
                current = next(stream, None)
            elif current is not None and current[0] < day:
                raise ValueError('history stream out of order')
            counts['complete_history_days' if complete else 'incomplete_history_days'] += 1
            key = ('US.' + symbol, day)
            if key in cases:
                dataset, pair = cases[key]
                eligible = len(history) == 20
                levels = daily_levels(list(history), date.fromisoformat(day)) if eligible else None
                signals, rejected = detect_signals(bars, levels) if eligible else (dict.fromkeys(CANDIDATES), {})
                prefix_complete = complete_prefix(bars, day, symbol)
                options, underlying_marks = {}, {}
                for name in CANDIDATES:
                    signal = signals[name]
                    row = {'candidate': name, 'symbol': 'US.' + symbol, 'trade_date': day,
                           'dataset': dataset.name, 'history_eligible': eligible, 'setup': levels,
                           'current_prefix_complete': prefix_complete,
                           'signal': signal, 'rejections': dict(rejected), 'underlying': None, 'option': None,
                           'alignment': None, 'status': 'MISSING_HISTORY' if not eligible else
                           'MISSING_CURRENT_DATA' if not prefix_complete else 'NO_SIGNAL'}
                    if signal is not None:
                        direction, at = signal['direction'], datetime.fromisoformat(signal['time'])
                        case = pair[direction]
                        if (direction, at) not in options:
                            options[direction, at] = endpoint_bars(dataset, 'option', case.contract, at)
                        marks = fixed_marks(options[direction, at], at)
                        marks.update(contract=case.contract, right='CALL' if direction == 'LONG' else 'PUT',
                                     strike=case.strike, selection=case.selection)
                        label = evaluate_signal_quality(bars, signal)
                        if at not in underlying_marks:
                            underlying_marks[at] = endpoint_bars(dataset, 'underlying', 'US.' + symbol, at)
                        alignment = fixed_marks(underlying_marks[at], at, require_volume=False)
                        value = alignment['mark_return_30m']
                        aligned = (1 if direction == 'LONG' else -1) * value if value is not None else None
                        alignment.update(directional_return_30m=aligned,
                            difference_from_k5=aligned - label['return_30m'] if aligned is not None and label['return_30m'] is not None else None)
                        row.update(status='OBSERVATION_RECORDED', underlying=label, option=marks, alignment=alignment)
                    records.append(row)
            if complete:
                history.append(aggregate_daily(bars, calendar[day]))
            else:
                history.clear()
        coverage[symbol] = dict(counts)
    records.sort(key=lambda row: (row['trade_date'], row['symbol'], row['candidate']))
    if len(records) != 77 * len(CANDIDATES):
        raise ValueError('missing OM1 session records')
    repo = Path(__file__).resolve().parents[2]
    files = [Path(__file__), *(Path(__file__).with_name(name + '.py') for name in
              ('daily_replay', 'daily_signals', 'replay', 'context_replay', 'context_signals', 'context_stats', 'signals')),
             *(repo / 'custody' / (name + '.py') for name in ('dataset', 'marketdata', 'models', 'evaluate'))]
    return {'study': 'OM1', 'status': 'DIAGNOSTIC_NOT_VALIDATION',
            'created_at': datetime.now(timezone.utc).isoformat(), 'inputs': inputs,
            'preregistration_sha256': PREREG_SHA256,
            'code_sha256': {str(path.relative_to(repo)): sha256_file(path) for path in files},
            'candidates': summarize(records), 'coverage': coverage,
            'resources': {'elapsed_seconds': time.monotonic() - started,
                          'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss},
            'limitations': ['已暴露77标的日／21日期，小样本诊断，不修改DS1判定或挑选候选。',
                            '同分钟期权成交收盘标价变化，不是买卖价、成交回放、净收益或购买建议。',
                            '开盘ATM声明不是信号时刻ATM；旧数据缺完整当时chain与标准乘数快照。',
                            '正股路径和期权标价各自分母；缺失不填零，候选重叠不能增加独立样本。']}, records


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--records-out', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists() or args.records_out.exists() or args.out.resolve() == args.records_out.resolve():
        parser.error('outputs must be distinct new files')
    result, records = replay(args.data_root)
    with args.records_out.open('x', encoding='utf-8') as handle:
        for row in records:
            handle.write(json.dumps(row, sort_keys=True, allow_nan=False) + '\n')
    result['records_artifact'] = {'path': str(args.records_out), 'sha256': sha256_file(args.records_out)}
    with args.out.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write('\n')
    print(json.dumps({key: result[key] for key in ('study', 'status', 'resources')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
