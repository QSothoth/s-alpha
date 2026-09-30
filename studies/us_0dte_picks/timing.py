"""P1: which decision time best picks 0DTE underlyings by remaining move / implied move.

Pre-registered in notes/P1_PREREG.md.  Offline and standard library only: reads local
5m and IV files, never requests market data.  Run from the repository root:

    python3 -m studies.us_0dte_picks.timing select --out <new.json>
    python3 -m studies.us_0dte_picks.timing validate --select-report <select.json> --out <new.json>
    python3 -m studies.us_0dte_picks.timing straddle --out <new.json>
"""
from __future__ import annotations

import argparse
from bisect import bisect_left
from collections import Counter, defaultdict
import csv
from datetime import date, timedelta
import hashlib
import json
from math import sqrt
from pathlib import Path
import random
from statistics import mean

CORE = ('SPY', 'QQQ', 'IWM', 'AAPL', 'MSFT', 'NVDA', 'TSLA', 'META', 'AMZN', 'GOOGL', 'AMD', 'MU', 'INTC', 'AVGO')
ETFS = ('DIA', 'EEM', 'GLD', 'SLV', 'SMH', 'TLT', 'XLE', 'XLF', 'XLU')
# decision point -> (5m bars completed at that time, remaining RTH minutes)
TIMES = {'open': (0, 390), '09:45': (3, 375), '10:00': (6, 360), '10:30': (12, 330)}
CANDIDATES = {'P0': 'open', 'O0': 'open', 'O15': '09:45', 'O30': '10:00', 'O60': '10:30'}  # earliest first
SELECT, VALIDATE, HALF = ('2023-06-26', '2024-05-31'), ('2024-06-03', '2026-09-24'), '2024-01-01'
TOP_N, MIN_POOL, DRAWS, SEED, IV_MAX_AGE = 3, 10, 2000, 20260926, 7
GRID = tuple('%02d:%02d:00' % divmod(570 + 5 * i, 60) for i in range(1, 79))
PREREG = Path(__file__).with_name('notes') / 'P1_PREREG.md'
PREREG_SHA256 = '1ddd91a11f0c0814f19f98c69ec5445e12b3623d12ea86a2321d1af13390a5b7'
K5 = {'select': 'data/preopen-us-k5-select-v1/k5', 'validate': 'data/preopen-us-k5-valid-v1/k5'}
ETF_K5 = 'data/or-context-etf-k5-2018-2026-retry1-work'
IV_DIRS = ('data/preopen-s23-select-v1/iv', 'data/preopen-s23-valid-v1/iv')
STRADDLE = ('data/custody-0dte-v5', 'data/custody-eval-2026-09-18-v2')


def summarize(bars):
    """One complete RTH session -> prices at each decision point; None if incomplete."""
    if tuple(bar[0] for bar in bars) != GRID:
        return None
    if any(not 0 < low <= min(o, c) <= max(o, c) <= high for _, o, high, low, c in bars):
        return None
    points = {}
    for label, (done, _) in TIMES.items():
        seen, rest = bars[:done], bars[done:]
        points[label] = {'price': seen[-1][4] if seen else bars[0][1],
                         'high': max(bar[2] for bar in seen) if seen else bars[0][1],
                         'low': min(bar[3] for bar in seen) if seen else bars[0][1],
                         'after_high': max(bar[2] for bar in rest),
                         'after_low': min(bar[3] for bar in rest)}
    return {'open': bars[0][1], 'close': bars[-1][4], 'at': points}


def load_sessions(path, since):
    """Stream one 5m file into {day: summary or None}; days before `since` are skipped."""
    out, day, bars = {}, None, []
    with open(path, newline='', encoding='utf-8') as handle:
        for row in csv.DictReader(handle):
            stamp = row['time_key']
            if stamp[:10] < since:
                continue
            if stamp[:10] != day:
                if day is not None:
                    out[day] = summarize(bars)
                day, bars = stamp[:10], []
            bars.append((stamp[11:19], float(row['open']), float(row['high']),
                         float(row['low']), float(row['close'])))
    if day is not None:
        out[day] = summarize(bars)
    return out


def load_iv(symbol, dirs=IV_DIRS):
    rows = {}
    for folder in dirs:
        with open(Path(folder) / (symbol + '.csv'), newline='', encoding='utf-8') as handle:
            for row in csv.DictReader(handle):
                try:
                    iv, hv = float(row['iv']), float(row['hv'])
                except (TypeError, ValueError):
                    continue
                if iv > 0 and hv > 0:
                    rows[row['time']] = (iv, hv)
    days = sorted(rows)
    return days, [rows[day] for day in days]


def iv_before(series, day):
    """Latest (iv, hv) strictly before `day` and at most IV_MAX_AGE calendar days old."""
    days, values = series
    index = bisect_left(days, day) - 1
    if index < 0:
        return None
    oldest = (date.fromisoformat(day) - timedelta(days=IV_MAX_AGE)).isoformat()
    return values[index] if days[index] >= oldest else None


def name_day(symbol, today, previous, iv):
    """Scores and targets for one symbol-day, or None when the entry rules fail."""
    if today is None or previous is None or iv is None:
        return None
    sigma, prev_close = iv[0] / 100 / sqrt(252), previous['close']
    record = {'symbol': symbol, 'score': {'P0': iv[1] / iv[0]}, 'y': {}, 'reach': {}, 'move': {}}
    for candidate, label in CANDIDATES.items():
        point = today['at'][label]
        if candidate != 'P0':
            span = max(prev_close, point['high']) - min(prev_close, point['low'])
            record['score'][candidate] = span / prev_close / sigma
    for label, (_, remaining) in TIMES.items():
        point = today['at'][label]
        price, scale = point['price'], sigma * sqrt(remaining / 390)
        move = abs(today['close'] / price - 1)
        record['move'][label] = move
        record['y'][label] = move / scale
        record['reach'][label] = max(point['after_high'] / price - 1, 1 - point['after_low'] / price) / scale
    return record


def build(phase, root=Path('.')):
    """{day: [name-day records]} for the phase window, pool >= MIN_POOL days only."""
    start, end = SELECT if phase == 'select' else VALIDATE
    since = (date.fromisoformat(start) - timedelta(days=20)).isoformat()
    sessions = {symbol: load_sessions(root / K5[phase] / (symbol + '.csv'), since) for symbol in CORE}
    calendar = sorted({day for days in sessions.values() for day in days})
    sessions.update({symbol: load_sessions(root / ETF_K5 / ('US.%s.csv' % symbol), since) for symbol in ETFS})
    ivs = {symbol: load_iv(symbol, [root / folder for folder in IV_DIRS]) for symbol in CORE + ETFS}
    days = {}
    for previous, day in zip(calendar, calendar[1:]):
        if not start <= day <= end:
            continue
        records = [record for symbol in CORE + ETFS
                   if (record := name_day(symbol, sessions[symbol].get(day), sessions[symbol].get(previous),
                                          iv_before(ivs[symbol], day))) is not None]
        if len(records) >= MIN_POOL:
            days[day] = records
    return days


def picks(records, candidate, top=TOP_N):
    return sorted(records, key=lambda record: (-record['score'][candidate], record['symbol']))[:top]


def lift(rows, pick, pool):
    return mean(row[pick] for row in rows) / mean(row[pool] for row in rows)


def evaluate(days, candidate, half=None):
    label, by_day = CANDIDATES[candidate], {}
    for day, records in sorted(days.items()):
        pool = {key: mean(record[key][label] for record in records) for key in ('y', 'reach', 'move')}
        by_day[day] = [(record['y'][label], pool['y'], record['reach'][label], pool['reach'],
                        record['move'][label], pool['move'], record['symbol'])
                       for record in picks(records, candidate)]
    rows = [row for day in by_day for row in by_day[day]]
    order, rng = sorted(by_day), random.Random(SEED)
    boots = sorted(lift([row for _ in order for row in by_day[order[rng.randrange(len(order))]]], 0, 1)
                   for _ in range(DRAWS))
    result = {'picks': len(rows), 'days': len(by_day), 'lift': lift(rows, 0, 1),
              'ci95': [boots[int(.025 * DRAWS)], boots[int(.975 * DRAWS) - 1]], 'lo90': boots[int(.05 * DRAWS)],
              'pick_y': mean(row[0] for row in rows), 'pool_y': mean(row[1] for row in rows),
              'pick_y_gt1': mean(row[0] > 1 for row in rows),
              'reach_lift': lift(rows, 2, 3), 'pick_reach': mean(row[2] for row in rows),
              'move_lift': lift(rows, 4, 5), 'pick_move_bp': 1e4 * mean(row[4] for row in rows),
              'pool_move_bp': 1e4 * mean(row[5] for row in rows),
              'picked': dict(Counter(row[6] for row in rows).most_common())}
    if half:
        result['halves'] = [lift([row for day in by_day if (day < half) == first for row in by_day[day]], 0, 1)
                            for first in (True, False)]
    years = sorted({day[:4] for day in by_day})
    result['by_year'] = {year: lift([row for day in by_day if day[:4] == year for row in by_day[day]], 0, 1)
                         for year in years}
    return result


def select_gates(result):
    return {'picks>=300': result['picks'] >= 300, 'lift>=1.2': result['lift'] >= 1.2,
            'ci95_low>1': result['ci95'][0] > 1.0, 'halves>1': all(value > 1.0 for value in result['halves'])}


def choose(results):
    """Highest 95% lower bound among passers; within 0.02 of it, the earliest decision."""
    passed = [name for name in CANDIDATES if all(results[name]['gates'].values())]
    if not passed:
        return None
    best = max(results[name]['ci95'][0] for name in passed)
    return next(name for name in CANDIDATES if name in passed and results[name]['ci95'][0] >= best - 0.02)


def option_price(path, cutoff, at_open):
    """Last traded 1m close at or before cutoff; the 09:31 bar's open for the open decision."""
    price = None
    with open(path, newline='', encoding='utf-8') as handle:
        for row in csv.DictReader(handle):
            clock = row['close_time'][11:16]
            if at_open:
                return float(row['open']) if clock == '09:31' and float(row['volume']) > 0 else None
            if clock > cutoff:
                break
            if float(row['volume']) > 0:
                price = float(row['close'])
    return price


def straddle(root=Path('.')):
    """Descriptive only: real 0DTE ATM straddles held to expiry, picks vs same-day available names."""
    cases = defaultdict(dict)
    for folder in STRADDLE:
        payload = json.loads((root / folder / 'cases.json').read_text(encoding='utf-8'))
        for case in payload.get('cases', payload) if isinstance(payload, dict) else payload:
            symbol = case['symbol'][3:]
            if symbol in CORE + ETFS and case.get('selection') == 'both_sides_atm_at_open':
                cases[case['trade_date']][symbol] = (root / folder, case)
    days = build('validate', root)
    result = {}
    for candidate, label in CANDIDATES.items():
        cutoff, rows = label if label != 'open' else '09:31', []
        for day in sorted(cases):
            records = [record for record in days.get(day, []) if record['symbol'] in cases[day]]
            returns = {}
            for record in records:
                folder, case = cases[day][record['symbol']]
                legs = [option_price(folder / 'option' / (case[key] + '.csv'), cutoff, label == 'open')
                        for key in ('call_contract', 'put_contract')]
                if all(leg and leg > 0 for leg in legs):
                    underlying = close_price(root, record['symbol'], day)
                    returns[record['symbol']] = abs(underlying - case['strike']) / sum(legs) - 1
            usable = [record for record in records if record['symbol'] in returns]
            if not usable:
                continue
            chosen = picks(usable, candidate)
            rows.append({'day': day, 'available': len(usable), 'picks': [record['symbol'] for record in chosen],
                         'pick_return': mean(returns[record['symbol']] for record in chosen),
                         'pool_return': mean(returns.values())})
        informative = [row for row in rows if row['available'] > TOP_N]
        result[candidate] = {'days': len(rows), 'informative_days': len(informative),
                             'pick_return': mean(row['pick_return'] for row in informative) if informative else None,
                             'pool_return': mean(row['pool_return'] for row in informative) if informative else None,
                             'rows': rows}
    return result


def close_price(root, symbol, day):
    folder = root / K5['validate'] if symbol in CORE else root / ETF_K5
    name = symbol + '.csv' if symbol in CORE else 'US.%s.csv' % symbol
    with open(folder / name, newline='', encoding='utf-8') as handle:
        for row in csv.DictReader(handle):
            if row['time_key'] == day + ' 16:00:00':
                return float(row['close'])
    raise ValueError('missing 16:00 close for %s %s' % (symbol, day))


def check_prereg():
    if hashlib.sha256(PREREG.read_bytes()).hexdigest() != PREREG_SHA256:
        raise SystemExit('P1_PREREG.md changed after registration')


def table(results):
    lines = ['%-4s %-6s %6s %5s %6s %13s %6s %6s %7s %7s %9s' % (
        'cand', 'time', 'picks', 'days', 'lift', 'ci95', 'lo90', 'pickY', 'Y>1', 'reachL', 'move bp')]
    for name, result in results.items():
        lines.append('%-4s %-6s %6d %5d %6.3f %6.3f-%6.3f %6.3f %6.3f %6.1f%% %7.3f %4.0f/%4.0f' % (
            name, CANDIDATES[name], result['picks'], result['days'], result['lift'], result['ci95'][0],
            result['ci95'][1], result['lo90'], result['pick_y'], 100 * result['pick_y_gt1'],
            result['reach_lift'], result['pick_move_bp'], result['pool_move_bp']))
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('phase', choices=('select', 'validate', 'straddle'))
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--select-report', type=Path)
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error('refusing to overwrite ' + str(args.out))
    check_prereg()
    report = {'study': 'P1', 'phase': args.phase, 'preregistration_sha256': PREREG_SHA256,
              'code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    if args.phase == 'straddle':
        report['straddle'] = straddle()
    else:
        days = build(args.phase)
        pools = [len(records) for records in days.values()]
        report.update(window=SELECT if args.phase == 'select' else VALIDATE, days=len(days),
                      pool_size={'min': min(pools), 'mean': mean(pools), 'max': max(pools)})
        results = {name: evaluate(days, name, HALF if args.phase == 'select' else None) for name in CANDIDATES}
        if args.phase == 'select':
            for result in results.values():
                result['gates'] = select_gates(result)
            report['chosen'] = choose(results)
        else:
            if args.select_report is None:
                parser.error('validate needs --select-report')
            chosen = json.loads(args.select_report.read_text(encoding='utf-8'))['chosen']
            if chosen is None:
                parser.error('selection failed; the validation segment stays closed')
            report['chosen'] = chosen
            report['verdict'] = {'lift>=1.2': results[chosen]['lift'] >= 1.2, 'lo90>1': results[chosen]['lo90'] > 1.0}
            report['passed'] = all(report['verdict'].values())
        report['results'] = results
        print(table(results))
        print('chosen:', report['chosen'], report.get('verdict', ''))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=1)
        handle.write('\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
