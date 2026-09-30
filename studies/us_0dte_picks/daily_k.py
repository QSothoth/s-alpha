"""P2: daily-K patterns and earnings -> same-day 0DTE opportunity on Mon/Wed/Fri single stocks.

Pre-registered in notes/P2_PREREG.md.  Offline and standard library only; reads local
daily, option-statistics, IV, earnings and expiry files.  Run from the repository root:

    python3 -m studies.us_0dte_picks.daily_k select --out <new.json>
    python3 -m studies.us_0dte_picks.daily_k validate --select-report <select.json> --out <new.json>
    python3 -m studies.us_0dte_picks.daily_k describe --out <new.json>
"""
from __future__ import annotations

import argparse
from bisect import bisect_left
from collections import defaultdict
import csv
from datetime import date, timedelta
import hashlib
import json
from math import sqrt
from pathlib import Path
import random
from statistics import mean

HERE = Path(__file__).resolve().parent
ARCHIVE_NOTES = HERE.parent / 'archive' / 'us_preopen_bias' / 'notes'
PREREG = HERE / 'notes' / 'P2_PREREG.md'
PREREG_SHA256 = '1efa50a0f0c9be2739c6bc20f70205d62eb2f6ba140fb9f823cd70f7e90e8d0d'
ADDENDUM = HERE / 'notes' / 'P2_ADDENDUM.md'
ADDENDUM_SHA256 = 'a71ce350fd6cc69da63abcb11ded495c197e2ac167fe0c8eff69cf3ebd7d2f20'
EVENTS = Path('data/p2-events-raw')
PHASES = {  # name -> (universe file, data dirs merged by date, window)
    'select': (ARCHIVE_NOTES / 'universe_stocks300.json', ('data/preopen-s24-select-v1',), ('2023-06-26', '2024-12-31')),
    'validate': (HERE / 'notes' / 'universe_stocks601_900.json', ('data/p2-601-900-raw',), ('2023-06-26', '2026-09-25')),
    'describe_300': (ARCHIVE_NOTES / 'universe_stocks300.json',
                     ('data/preopen-s24-select-v1', 'data/preopen-s24-valid-v1'), ('2025-01-02', '2026-09-24')),
    'describe_301_600': (ARCHIVE_NOTES / 'universe_stocks301_600.json', ('data/preopen-s27-holdout-v1',),
                         ('2023-06-26', '2026-09-24')),
}
CANDIDATES = ('K1_EARN', 'K2_NR7', 'K3_52W', 'K4_THRUST', 'K5_EXHAUST')
POST_HOC = ('K4B_THRUST_ANY',)  # notes/P2_ADDENDUM.md: registered after selection, validation only
BOTH, LONG, SHORT = 0, 1, -1
K_MAIN, K_ALT = 1.0, 0.5
LOOKBACK, IV_MAX_AGE, MIN_POOL, HALF = 252, 7, 5, '2024-04-01'
DRAWS, SEED = 2000, 20260926
FRIDAYS_WEEKLY = ('2026-10-02', '2026-10-09')
SCHEDULE_FROM, SCHEDULE_TO = '2026-09-27', '2026-10-26'


def read_csv(path, key):
    try:
        with open(path, newline='', encoding='utf-8') as handle:
            return {row[key]: row for row in csv.DictReader(handle)}
    except FileNotFoundError:
        return {}


def number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def load_symbol(symbol, dirs):
    """Merge each table across dirs by date; later dirs never overwrite earlier dates."""
    tables = {}
    for table, key in (('daily', 'date'), ('daily_none', 'date'), ('option_stats', 'time'), ('iv', 'time')):
        merged = {}
        for folder in dirs:
            for day, row in read_csv(Path(folder) / table / (symbol + '.csv'), key).items():
                merged.setdefault(day, row)
        tables[table] = merged
    bars = []
    for day in sorted(tables['daily']):
        row = tables['daily'][day]
        values = [number(row.get(field)) for field in ('open', 'high', 'low', 'close', 'volume', 'turnover')]
        if None in values[:4] or min(values[:4]) <= 0 or values[1] < values[2]:
            continue
        bars.append((day, *values))
    ivs = sorted((day, number(row.get('iv')), number(row.get('hv'))) for day, row in tables['iv'].items()
                 if (number(row.get('iv')) or 0) > 0)
    return {'bars': bars, 'nominal': {day: number(row.get('close')) for day, row in tables['daily_none'].items()},
            'option_volume': {day: number(row.get('option_volume')) for day, row in tables['option_stats'].items()},
            'iv_days': [row[0] for row in ivs], 'iv': [row[1] for row in ivs]}


def schedule(symbol, root=EVENTS):
    """Current listing from the 2026-09-26 pull: (weekly Friday expiries, Monday/Wednesday expiries)."""
    try:
        rows = json.loads((root / 'expiry' / (symbol + '.json')).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return False, False
    dates = {str(row['strike_time'])[:10] for row in rows}
    weekly = all(day in dates for day in FRIDAYS_WEEKLY)
    mon_wed = any(SCHEDULE_FROM <= day <= SCHEDULE_TO and date.fromisoformat(day).weekday() in (0, 2) for day in dates)
    return weekly, mon_wed


def reaction_days(symbol, calendar, root=EVENTS):
    """First session trading on the news: T−1 after-market or T pre-market releases only."""
    try:
        rows = json.loads((root / 'earnings' / (symbol + '.json')).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return set()
    days = set()
    for published, kind in {(str(row['pub_trading_day_str'])[:10], row['pub_type']) for row in rows}:
        if kind == 'PRE_MARKET' and published in calendar:
            days.add(published)
        elif kind == 'AFTER_MARKET':
            index = bisect_left(calendar, published)
            if index < len(calendar) and calendar[index] == published:
                index += 1  # released after that session's close
            if index < len(calendar):
                days.add(calendar[index])
    return days


def iv_before(data, day):
    index = bisect_left(data['iv_days'], day) - 1
    if index < 0:
        return None
    oldest = (date.fromisoformat(day) - timedelta(days=IV_MAX_AGE)).isoformat()
    return data['iv'][index] if data['iv_days'][index] >= oldest else None


def true_range(bar, previous_close):
    return max(bar[2], previous_close) - min(bar[3], previous_close)


def signals(bars, i, earnings):
    """Candidate sides for T = bars[i] from bars[:i] only (earnings timing is known before the open)."""
    day, prev = bars[i][0], bars[i - 1]
    _, o, h, low, c, volume, _ = prev
    span = h - low
    out = {}
    if day in earnings:
        out['K1_EARN'] = BOTH
    ranges = [bar[2] - bar[3] for bar in bars[i - 7:i - 1]]
    if span > 0 and all(span < other for other in ranges):
        out['K2_NR7'] = BOTH
    closes = [bar[4] for bar in bars[i - LOOKBACK:i - 1]]
    if c > max(closes):
        out['K3_52W'] = LONG
    elif c < min(closes):
        out['K3_52W'] = SHORT
    window = bars[i - 21:i - 1]
    atr = mean(true_range(bar, bars[i - 22 + k][4]) for k, bar in enumerate(window))
    if span > 0 and volume >= 2 * mean(bar[5] for bar in window) and true_range(prev, bars[i - 2][4]) >= 1.5 * atr:
        location = (c - low) / span
        if location >= .75:
            out['K4_THRUST'] = LONG
        elif location <= .25:
            out['K4_THRUST'] = SHORT
        if 'K4_THRUST' in out:
            out['K4B_THRUST_ANY'] = BOTH
    if span > 0:
        c1, c2, c3, c4 = bars[i - 1][4], bars[i - 2][4], bars[i - 3][4], bars[i - 4][4]
        if c1 < c2 < c3 < c4 and min(o, c) - low >= .5 * span and c >= low + 2 * span / 3:
            out['K5_EXHAUST'] = LONG
        elif c1 > c2 > c3 > c4 and h - max(o, c) >= .5 * span and c <= low + span / 3:
            out['K5_EXHAUST'] = SHORT
    return out


def build(phase, root=Path('.')):
    """{day: [name-day records]} for Mon/Wed/Fri pools of the phase window."""
    universe, dirs, (start, end) = PHASES[phase]
    codes = [row['code'].split('.', 1)[1] for row in json.loads(universe.read_text(encoding='utf-8'))['symbols']]
    data = {code: load_symbol(code, [root / folder for folder in dirs]) for code in codes}
    calendar = sorted({bar[0] for item in data.values() for bar in item['bars']})
    previous_day = dict(zip(calendar[1:], calendar))
    days = defaultdict(list)
    for code, item in data.items():
        weekly, mon_wed = schedule(code, root / EVENTS)
        earnings = reaction_days(code, calendar, root / EVENTS)
        bars = item['bars']
        for i in range(LOOKBACK, len(bars)):
            day = bars[i][0]
            weekday = date.fromisoformat(day).weekday()
            if not start <= day <= end or bars[i - 1][0] != previous_day.get(day):
                continue
            if not (weekday == 4 and weekly or weekday in (0, 2) and mon_wed):
                continue
            yesterday = bars[i - 1][0]
            nominal, option_volume, iv = item['nominal'].get(yesterday), item['option_volume'].get(yesterday), iv_before(item, day)
            if (nominal is None or nominal < 3 or option_volume is None or option_volume < 1000 or iv is None
                    or mean(bar[6] or 0 for bar in bars[i - 20:i]) < 5e6):
                continue
            sigma = iv / 100 / sqrt(252)
            _, o, h, low, c = bars[i][:5]
            days[day].append({'symbol': code, 'up': (h - o) / o / sigma, 'dn': (o - low) / o / sigma,
                              'oc': (c - o) / o / sigma, 'signals': signals(bars, i, earnings)})
    return {day: records for day, records in sorted(days.items()) if len(records) >= MIN_POOL}


def outcomes(record, side, k):
    up, dn = record['up'] >= k, record['dn'] >= k
    if side == BOTH:
        return up or dn, None
    return (up, dn) if side == LONG else (dn, up)


def rows_for(days, candidate, k):
    """Per pick: (day, fav, adv, base_fav, base_adv, side, close_fav, base_close_fav)."""
    rows = []
    for day, records in days.items():
        rate = {key: mean(test(record) for record in records) for key, test in (
            ('up', lambda r: r['up'] >= k), ('dn', lambda r: r['dn'] >= k),
            ('any', lambda r: r['up'] >= k or r['dn'] >= k), ('oc_up', lambda r: r['oc'] > 0),
            ('oc_dn', lambda r: r['oc'] < 0))}
        for record in records:
            side = record['signals'].get(candidate)
            if side is None:
                continue
            fav, adv = outcomes(record, side, k)
            if side == BOTH:
                rows.append((day, fav, None, rate['any'], None, side, None, None))
            else:
                base_fav, base_adv = (rate['up'], rate['dn']) if side == LONG else (rate['dn'], rate['up'])
                close_fav = record['oc'] > 0 if side == LONG else record['oc'] < 0
                base_close = rate['oc_up'] if side == LONG else rate['oc_dn']
                rows.append((day, fav, adv, base_fav, base_adv, side, close_fav, base_close))
    return rows


def delta(rows):
    return mean(row[1] - row[3] for row in rows)


def tilt(rows):
    return mean((row[1] - row[2]) - (row[3] - row[4]) for row in rows)


def summarize(rows, directional, half=None):
    by_day = defaultdict(list)
    for row in rows:
        by_day[row[0]].append(row)
    order, rng = sorted(by_day), random.Random(SEED)
    boots = []
    for _ in range(DRAWS):
        sample = [row for _ in order for row in by_day[order[rng.randrange(len(order))]]]
        boots.append((delta(sample), tilt(sample) if directional else 0.0))
    quantile = lambda values, q: sorted(values)[int(q * DRAWS)]
    result = {'picks': len(rows), 'dates': len(by_day), 'fav_rate': mean(row[1] for row in rows),
              'base_fav_rate': mean(row[3] for row in rows), 'delta': delta(rows),
              'delta_ci95': [quantile([b[0] for b in boots], .025), quantile([b[0] for b in boots], .975)],
              'delta_lo90': quantile([b[0] for b in boots], .05)}
    if directional:
        result.update(adv_rate=mean(row[2] for row in rows), base_adv_rate=mean(row[4] for row in rows),
                      tilt=tilt(rows), tilt_ci95=[quantile([b[1] for b in boots], .025), quantile([b[1] for b in boots], .975)],
                      tilt_lo90=quantile([b[1] for b in boots], .05),
                      close_fav_rate=mean(row[6] for row in rows), base_close_fav_rate=mean(row[7] for row in rows),
                      sides={name: sum(row[5] == side for row in rows) for name, side in (('long', LONG), ('short', SHORT))})
    if half:
        parts = [[row for row in rows if (row[0] < half) == first] for first in (True, False)]
        result['halves'] = [{'delta': delta(part) if part else None,
                             'tilt': tilt(part) if part and directional else None} for part in parts]
    return result


def evaluate(days, half=None, split=None, candidates=CANDIDATES):
    results = {}
    for candidate in candidates:
        main = rows_for(days, candidate, K_MAIN)
        if not main:
            results[candidate] = {'picks': 0}
            continue
        directional = main[0][5] != BOTH
        result = summarize(main, directional, half)
        alt = rows_for(days, candidate, K_ALT)
        result['k0.5'] = {'fav_rate': mean(row[1] for row in alt), 'delta': delta(alt),
                          **({'tilt': tilt(alt)} if directional else {})}
        if split:
            result['by_period'] = {name: (lambda part: {'picks': len(part), 'delta': delta(part),
                                                        **({'tilt': tilt(part)} if directional else {})} if part else None)(
                [row for row in main if (row[0] < split) == first]) for name, first in (('before', True), ('after', False))}
        result['directional'] = directional
        results[candidate] = result
    return results


def select_gates(result):
    if not result.get('picks'):
        return {'enough': False}
    gates = {'picks>=200': result['picks'] >= 200, 'dates>=60': result['dates'] >= 60,
             'delta>=5pp': result['delta'] >= .05, 'delta_ci95_low>0': result['delta_ci95'][0] > 0,
             'halves_delta>0': all(part['delta'] is not None and part['delta'] > 0 for part in result['halves'])}
    if result['directional']:
        gates.update({'tilt>=5pp': result['tilt'] >= .05, 'tilt_ci95_low>0': result['tilt_ci95'][0] > 0,
                      'halves_tilt>0': all(part['tilt'] is not None and part['tilt'] > 0 for part in result['halves'])})
    return gates


def validate_gates(result):
    if result.get('picks', 0) < 100:
        return {'picks>=100': False}
    gates = {'picks>=100': True, 'delta_lo90>0': result['delta_lo90'] > 0}
    if result['directional']:
        gates['tilt_lo90>0'] = result['tilt_lo90'] > 0
    return gates


def pool_stats(days):
    sizes = defaultdict(list)
    for day, records in days.items():
        sizes[date.fromisoformat(day).strftime('%a')].append(len(records))
    return {'days': len(days), 'by_weekday': {name: {'days': len(v), 'mean_pool': mean(v)} for name, v in sizes.items()},
            'base_up_k1': mean(r['up'] >= 1 for recs in days.values() for r in recs),
            'base_dn_k1': mean(r['dn'] >= 1 for recs in days.values() for r in recs)}


def table(results):
    lines = ['%-11s %6s %5s %7s %7s %8s %15s %8s %15s' % ('candidate', 'picks', 'dates', 'fav', 'base', 'delta',
                                                          'delta ci95', 'tilt', 'tilt ci95')]
    for name, r in results.items():
        if not r.get('picks'):
            lines.append('%-11s no picks' % name)
            continue
        tilt_text = ('%+7.1f%% %+6.1f..%+6.1f' % (100 * r['tilt'], 100 * r['tilt_ci95'][0], 100 * r['tilt_ci95'][1])
                     if r['directional'] else '')
        lines.append('%-11s %6d %5d %6.1f%% %6.1f%% %+7.1f%% %+6.1f..%+6.1f %s' % (
            name, r['picks'], r['dates'], 100 * r['fav_rate'], 100 * r['base_fav_rate'], 100 * r['delta'],
            100 * r['delta_ci95'][0], 100 * r['delta_ci95'][1], tilt_text))
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('phase', choices=('select', 'validate', 'describe'))
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--select-report', type=Path)
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error('refusing to overwrite ' + str(args.out))
    if hashlib.sha256(PREREG.read_bytes()).hexdigest() != PREREG_SHA256:
        raise SystemExit('P2_PREREG.md changed after registration')
    report = {'study': 'P2', 'phase': args.phase, 'preregistration_sha256': PREREG_SHA256,
              'code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    if args.phase == 'select':
        days = build('select')
        results = evaluate(days, HALF)
        for result in results.values():
            result['gates'] = select_gates(result)
        report.update(pool=pool_stats(days), results=results,
                      passed=[name for name, r in results.items() if all(r['gates'].values())])
        print(table(results))
    elif args.phase == 'validate':
        if args.select_report is None:
            parser.error('validate needs --select-report')
        passed = json.loads(args.select_report.read_text(encoding='utf-8'))['passed']
        if not passed:
            parser.error('no candidate passed selection; the validation names stay closed')
        if hashlib.sha256(ADDENDUM.read_bytes()).hexdigest() != ADDENDUM_SHA256:
            raise SystemExit('P2_ADDENDUM.md changed after registration')
        days = build('validate')
        results = evaluate(days, split='2025-01-01', candidates=CANDIDATES + POST_HOC)
        judged = passed + list(POST_HOC)
        for name in judged:
            results[name]['gates'] = validate_gates(results[name])
        report.update(pool=pool_stats(days), results=results, judged=judged, post_hoc=list(POST_HOC),
                      addendum_sha256=ADDENDUM_SHA256,
                      overlap_k1_k4b=sum('K1_EARN' in r['signals'] and 'K4B_THRUST_ANY' in r['signals']
                                         for records in days.values() for r in records),
                      validated=[name for name in judged if all(results[name]['gates'].values())])
        print(table(results))
    else:
        for phase in ('describe_300', 'describe_301_600'):
            days = build(phase)
            report[phase] = {'pool': pool_stats(days), 'results': evaluate(days)}
            print(phase)
            print(table(report[phase]['results']))
    print({key: report[key] for key in ('passed', 'judged', 'validated') if key in report})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=1)
        handle.write('\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
