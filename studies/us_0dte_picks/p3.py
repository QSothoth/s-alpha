"""P3: in-play + opening direction (P3a) and opening option flow (P3b) -> 10:00 directional signals.

Pre-registered in notes/P3_PREREG.md.  Offline and standard library only.  Run from the
repository root:

    python3 -m studies.us_0dte_picks.p3 select --round a --out <new.json>
    python3 -m studies.us_0dte_picks.p3 validate --round a --select-report <select.json> --out <new.json>
"""
from __future__ import annotations

import argparse
from bisect import bisect_left
from collections import defaultdict
import csv
from datetime import date, timedelta
import hashlib
import json
from math import erf, exp, log, sqrt
from pathlib import Path
import random
from statistics import mean

from . import daily_k

HERE = Path(__file__).resolve().parent
PREREG = HERE / 'notes' / 'P3_PREREG.md'
PREREG_SHA256 = '03df30e9f57de8e3c5d33b4e59bd2c8e08d2ceab40391b118996d2ee39aa6163'
GRID = tuple('%02d:%02d:00' % divmod(570 + 5 * i, 60) for i in range(1, 79))
ENTRY_BAR, TARGET, STOP, CHOP = 6, 1.0, 0.5, 0.3
REMAINING = 360
TOP, DRAWS, SEED, IV_SCALE = 5, 2000, 20260926, 0.68
EVENT_START = '2025-09-29'
SELECT_K5 = {'core': ('data/preopen-us-k5-select-v1/k5', 'data/preopen-us-k5-valid-v1/k5'),
             's20': ('data/preopen-s20-select-v1/k5', 'data/preopen-s20-valid-v1/k5')}
CORE_STOCKS = ('AAPL', 'MSFT', 'NVDA', 'TSLA', 'META', 'AMZN', 'GOOGL', 'AMD', 'MU', 'INTC', 'AVGO', 'SNDK', 'SKHY')
VALIDATION_K5 = 'data/p3-k5-validation-raw/k5'
SIDE_DIRS = ('data/preopen-s24-select-v1', 'data/preopen-s24-valid-v1', 'data/preopen-s27-holdout-v1',
             'data/preopen-s23-select-v1', 'data/preopen-s23-valid-v1', 'data/preopen-s21-select-v1',
             'data/preopen-s21-valid-v1', 'data/preopen-s20-select-v1', 'data/preopen-s20-valid-v1',
             'data/p2-601-900-raw')
EVENTS = Path('data/p3-option-events-raw')
ROUNDS = {'a': (('A1_ORB', 'A2_DRIVE_TREND', 'A3_GAP_GO', 'A4_THRUST_FOLLOW', 'A5_CONFLUENCE'),
                ('2023-06-26', '2026-09-25'), '2025-02-01', (150, 60), 60),
          'b': (('B1_FLOW_NET', 'B2_FLOW_OTM_BUY', 'B3_FLOW_CONFIRM', 'B4_FLOW_IN_PLAY', 'B5_FLOW_PRIOR_DAY'),
                (EVENT_START, '2026-09-25'), '2026-04-01', (100, 40), 40)}


# ---------- loading ----------

def sessions(paths, since='2023-03-01'):
    """({day: [(clock, o, h, l, c, v), ...]} for complete 78-bar RTH sessions, every day seen incl. half days)."""
    raw = defaultdict(list)
    for path in paths:
        try:
            handle = open(path, newline='', encoding='utf-8')
        except FileNotFoundError:
            continue
        with handle:
            for row in csv.DictReader(handle):
                stamp = row['time_key']
                if stamp[:10] < since:
                    continue
                raw[stamp[:10]].append((stamp[11:19], float(row['open']), float(row['high']), float(row['low']),
                                        float(row['close']), float(row['volume'])))
    out = {}
    for day, bars in raw.items():
        bars = sorted(dict((bar[0], bar) for bar in bars).values())
        if tuple(bar[0] for bar in bars) == GRID and all(0 < b[3] <= min(b[1], b[4]) <= max(b[1], b[4]) <= b[2] for b in bars):
            out[day] = bars
    return out, set(raw)


def side_tables(symbol):
    """Nominal closes, option volume and IV series merged across every known daily dataset."""
    nominal, option_volume, iv = {}, {}, {}
    for folder in SIDE_DIRS:
        for table, key, target, field in (('daily_none', 'date', nominal, 'close'),
                                          ('option_stats', 'time', option_volume, 'option_volume'),
                                          ('iv', 'time', iv, 'iv')):
            for day, row in daily_k.read_csv(Path(folder) / table / (symbol + '.csv'), key).items():
                value = daily_k.number(row.get(field))
                if value is not None:
                    target.setdefault(day, value)
    days = sorted(day for day, value in iv.items() if value > 0)
    return nominal, option_volume, {'iv_days': days, 'iv': [iv[day] for day in days]}


def events_by_day(symbol):
    try:
        payload = json.loads((EVENTS / (symbol + '.json')).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None
    out = defaultdict(list)
    for row in payload['rows']:
        stamp = str(row['fill_time'])
        out[stamp[:10]].append((stamp[11:19], row.get('sentiment'), float(row.get('turnover') or 0),
                                row.get('ticker_type'), row.get('option_type'), row.get('dte'), row.get('otm')))
    return out


# ---------- per name-day features ----------

def daily_bar(bars):
    return (bars[0][1], max(b[2] for b in bars), min(b[3] for b in bars), bars[-1][4], sum(b[5] for b in bars))


def first_touch(bars, entry, sigma_rem, side):
    """(result in sigma_rem units, target_first, stop_first, max favourable in sigma_rem, exit bar index, exit price)."""
    target, stop = entry * (1 + side * TARGET * sigma_rem), entry * (1 - side * STOP * sigma_rem)
    best = 0.0
    for index in range(ENTRY_BAR, len(bars)):
        _, _, high, low, _, _ = bars[index]
        favourable = (high / entry - 1) if side > 0 else (1 - low / entry)
        hit_stop = low <= stop if side > 0 else high >= stop
        hit_target = high >= target if side > 0 else low <= target
        if hit_stop:
            return -STOP, False, True, max(best, 0.0) / sigma_rem, index, stop
        best = max(best, favourable)
        if hit_target:
            return TARGET, True, False, best / sigma_rem, index, target
    result = side * (bars[-1][4] / entry - 1) / sigma_rem
    return min(max(result, -STOP), TARGET), False, False, best / sigma_rem, len(bars) - 1, bars[-1][4]


def norm_cdf(x):
    return 0.5 * (1 + erf(x / sqrt(2)))


def bs_price(spot, strike, vol, years, side):
    if years <= 0 or vol <= 0:
        return max(0.0, side * (spot - strike))
    d1 = (log(spot / strike) + 0.5 * vol * vol * years) / (vol * sqrt(years))
    d2 = d1 - vol * sqrt(years)
    return spot * norm_cdf(side * d1) * side - strike * norm_cdf(side * d2) * side


def option_estimate(entry, exit_price, exit_index, iv, side):
    """Descriptive gross ATM 0DTE return, Black-Scholes with IV_SCALE x T-1 IV, trading-time years."""
    vol, year = IV_SCALE * iv / 100, 390 * 252
    start = bs_price(entry, entry, vol, REMAINING / year, side)
    left = 390 - 5 * (exit_index + 1)
    end = bs_price(exit_price, entry, vol, left / year, side)
    return end / start - 1 if start > 0 else None


def flow(events, day, start, end, only=None):
    bull = bear = 0.0
    for clock, sentiment, turnover, ticker, right, dte, otm in events.get(day, ()):
        if not start <= clock < end or (only and not only(ticker, right, dte, otm)):
            continue
        if sentiment == 'BULLISH':
            bull += turnover
        elif sentiment == 'BEARISH':
            bear += turnover
    return bull, bear


def near_otm_buy(ticker, right, dte, otm):
    try:
        return ticker == 'BUY' and 0 <= int(dte) <= 7 and float(otm) > 0
    except (TypeError, ValueError):
        return False


def near_dated(ticker, right, dte, otm):
    try:
        return 0 <= int(dte) <= 7
    except (TypeError, ValueError):
        return False


def event_baseline(events, calendar, index):
    """Mean daily event turnover over the previous 20 market days since EVENT_START; None if < 5 days observed."""
    days = [day for day in calendar[max(0, index - 20):index] if day >= EVENT_START]
    totals = [sum(e[2] for e in events.get(day, ())) for day in days]
    return mean(totals) if len(days) >= 5 and sum(total > 0 for total in totals) >= 5 else None


def features(symbol, bars_by_day, calendar, tables, weekly, mon_wed, earnings, events, window):
    nominal, option_volume, ivs = tables
    days = sorted(bars_by_day)
    daily = {day: daily_bar(bars_by_day[day]) for day in days}
    market_index = {day: i for i, day in enumerate(calendar)}
    out = []
    for position, day in enumerate(days):
        if not window[0] <= day <= window[1] or position < 25:
            continue
        index = market_index[day]
        previous = calendar[index - 1] if index else None
        if days[position - 1] != previous:
            continue
        weekday = date.fromisoformat(day).weekday()
        if not (weekday == 4 and weekly or weekday in (0, 2) and mon_wed):
            continue
        prior = days[position - 14:position]
        if market_index[prior[0]] < index - 20:
            continue
        iv = daily_k.iv_before(ivs, day)
        turnover20 = mean(daily[d][3] * daily[d][4] for d in days[position - 20:position])
        if (iv is None or (nominal.get(previous) or 0) < 3 or (option_volume.get(previous) or 0) < 1000
                or turnover20 < 5e6):
            continue
        bars = bars_by_day[day]
        sigma = iv / 100 / sqrt(252)
        sigma_rem = sigma * sqrt(REMAINING / 390)
        o, c1, p10 = bars[0][1], daily[previous][3], bars[ENTRY_BAR - 1][4]
        first = bars[0]
        closes = [daily[d][3] for d in days[position - 25:position]]
        ma20, ma20_old = mean(closes[-20:]), mean(closes[-25:-5])
        trend = 1 if c1 > ma20 and ma20 > ma20_old else -1 if c1 < ma20 and ma20 < ma20_old else 0
        record = {'symbol': symbol, 'day': day, 'iv': iv, 'sigma_rem': sigma_rem, 'p10': p10,
                  'gap_z': (o / c1 - 1) / sigma, 'drive_z': (p10 / o - 1) / sigma,
                  'rvol30': sum(b[5] for b in bars[:6]) / (mean(sum(b[5] for b in bars_by_day[d][:6]) for d in prior) or 1e-9),
                  'color': 1 if first[4] > first[1] else -1 if first[4] < first[1] else 0,
                  'beyond_or5': 1 if p10 > first[2] else -1 if p10 < first[3] else 0,
                  'trend': trend, 'above_c1': 1 if p10 > c1 else -1 if p10 < c1 else 0,
                  'earnings': day in earnings, 'thrust': thrust_side(daily, days, position)}
        for side in (1, -1):
            record['outcome', side] = first_touch(bars, p10, sigma_rem, side)
        if events is not None and day >= EVENT_START:
            base = event_baseline(events, calendar, index)
            if base:
                bull, bear = flow(events, day, '09:30:00', '10:00:00')
                call, put = flow(events, day, '09:30:00', '10:00:00', near_otm_buy)
                pbull, pbear = flow(events, previous, '14:00:00', '16:00:00', near_dated)
                record['flow'] = {'rel': (bull + bear) / base, 'net': (bull - bear) / (bull + bear) if bull + bear else 0.0,
                                  'otm_rel': (call + put) / base, 'otm_net': (call - put) / (call + put) if call + put else 0.0,
                                  'prior_rel': (pbull + pbear) / base,
                                  'prior_net': (pbull - pbear) / (pbull + pbear) if pbull + pbear else 0.0}
        out.append(record)
    return out


def thrust_side(daily, days, position):
    if position < 22:
        return 0
    o, h, low, c, volume = daily[days[position - 1]]
    span = h - low
    window = days[position - 21:position - 1]
    atr = mean(max(daily[d][1], daily[days[position - 22 + k]][3]) - min(daily[d][2], daily[days[position - 22 + k]][3])
               for k, d in enumerate(window))
    previous_close = daily[days[position - 2]][3]
    if span <= 0 or volume < 2 * mean(daily[d][4] for d in window) or max(h, previous_close) - min(low, previous_close) < 1.5 * atr:
        return 0
    location = (c - low) / span
    return 1 if location >= .75 else -1 if location <= .25 else 0


# ---------- candidates ----------

def signal(record, name):
    """(side, rank key) or None, from information available at 10:00 only."""
    r = record
    in_play = r['rvol30'] >= 2
    if name == 'A1_ORB':
        if in_play and r['color'] and r['beyond_or5'] == r['color']:
            return r['color'], r['rvol30']
    elif name == 'A2_DRIVE_TREND':
        side = 1 if r['drive_z'] > 0 else -1
        if (in_play or abs(r['gap_z']) >= 1) and abs(r['drive_z']) >= .5 and r['trend'] == side:
            return side, abs(r['drive_z'])
    elif name == 'A3_GAP_GO':
        side = 1 if r['gap_z'] > 0 else -1
        if abs(r['gap_z']) >= 1.5 and in_play and side * r['drive_z'] >= 0:
            return side, abs(r['gap_z'])
    elif name == 'A4_THRUST_FOLLOW':
        side = r['thrust']
        if side and r['above_c1'] == side and side * r['drive_z'] > 0 and r['rvol30'] >= 1.5:
            return side, r['rvol30']
    elif name == 'A5_CONFLUENCE':
        side = r['color']
        if in_play and side and r['beyond_or5'] == side and side * r['drive_z'] >= .5 and r['trend'] == side:
            return side, r['rvol30']
    elif 'flow' in r:
        f = r['flow']
        side = 1 if f['net'] > 0 else -1
        base = f['rel'] >= .5 and abs(f['net']) >= .5
        if name == 'B1_FLOW_NET' and base:
            return side, f['rel']
        if name == 'B2_FLOW_OTM_BUY' and f['otm_rel'] >= .25 and abs(f['otm_net']) >= .6:
            return (1 if f['otm_net'] > 0 else -1), f['otm_rel']
        if name == 'B3_FLOW_CONFIRM' and base and side * r['drive_z'] > 0:
            return side, f['rel']
        if name == 'B4_FLOW_IN_PLAY' and base and (in_play or abs(r['gap_z']) >= 1 or r['earnings']):
            return side, f['rel']
        if name == 'B5_FLOW_PRIOR_DAY' and f['prior_rel'] >= .3 and abs(f['prior_net']) >= .5:
            return (1 if f['prior_net'] > 0 else -1), f['prior_rel']
    return None


def picks(records, name):
    by_day = defaultdict(list)
    for record in records:
        hit = signal(record, name)
        if hit:
            by_day[record['day']].append((-hit[1], record['symbol'], hit[0], record))
    return {day: [(side, record) for _, _, side, record in sorted(rows)[:TOP]] for day, rows in by_day.items()}


def row_of(side, record):
    result, target_first, stop_first, best, index, price = record['outcome', side]
    return {'payoff': result, 'target': target_first, 'stop': stop_first, 'chop': best < CHOP,
            'edge': target_first - record['outcome', -side][1], 'side': side,
            'option': option_estimate(record['p10'], price, index, record['iv'], side)}


def summarize(by_day, half):
    rows = {day: [row_of(side, record) for side, record in items] for day, items in by_day.items()}
    flat = [row for day in rows for row in rows[day]]
    if not flat:
        return {'picks': 0}
    order, rng = sorted(rows), random.Random(SEED)
    boots = []
    for _ in range(DRAWS):
        sample = [row for _ in order for row in rows[order[rng.randrange(len(order))]]]
        boots.append((mean(r['payoff'] for r in sample), mean(r['edge'] for r in sample)))
    q = lambda k, p: sorted(b[k] for b in boots)[int(p * DRAWS)]
    options = [r['option'] for r in flat if r['option'] is not None]
    halves = [[r for day in rows if (day < half) == first for r in rows[day]] for first in (True, False)]
    return {'picks': len(flat), 'dates': len(rows), 'per_date': len(flat) / len(rows),
            'target_rate': mean(r['target'] for r in flat), 'stop_rate': mean(r['stop'] for r in flat),
            'chop_rate': mean(r['chop'] for r in flat), 'payoff': mean(r['payoff'] for r in flat),
            'payoff_ci95': [q(0, .025), q(0, .975)], 'payoff_lo90': q(0, .05),
            'edge': mean(r['edge'] for r in flat), 'edge_ci95': [q(1, .025), q(1, .975)], 'edge_lo90': q(1, .05),
            'halves_payoff': [mean(r['payoff'] for r in part) if part else None for part in halves],
            'long': sum(r['side'] > 0 for r in flat), 'short': sum(r['side'] < 0 for r in flat),
            'option_gross_mean': mean(options) if options else None,
            'option_gross_median': sorted(options)[len(options) // 2] if options else None,
            'option_doubled_rate': mean(o >= 1 for o in options) if options else None}


def select_gates(result, minimum):
    if not result.get('picks'):
        return {'picks': False}
    return {'picks>=%d' % minimum[0]: result['picks'] >= minimum[0], 'dates>=%d' % minimum[1]: result['dates'] >= minimum[1],
            'target_rate>=40%': result['target_rate'] >= .40, 'payoff>0': result['payoff'] > 0,
            'payoff_ci95_low>0': result['payoff_ci95'][0] > 0, 'edge>=10pp': result['edge'] >= .10,
            'edge_ci95_low>0': result['edge_ci95'][0] > 0,
            'halves_payoff>0': all(v is not None and v > 0 for v in result['halves_payoff'])}


def validate_gates(result, minimum):
    if result.get('picks', 0) < minimum:
        return {'picks>=%d' % minimum: False}
    return {'picks>=%d' % minimum: True, 'payoff_lo90>0': result['payoff_lo90'] > 0, 'edge_lo90>0': result['edge_lo90'] > 0}


# ---------- universe ----------

def universe(phase, round_name):
    if phase == 'select':
        items = [(s, [str(Path(d) / (s + '.csv')) for d in SELECT_K5['core']]) for s in CORE_STOCKS]
        s20 = sorted(p.stem for p in Path(SELECT_K5['s20'][0]).glob('*.csv'))
        items += [(s, [str(Path(d) / (s + '.csv')) for d in SELECT_K5['s20']]) for s in s20]
    else:
        codes = json.loads((HERE / 'notes' / 'p3_validation_names.json').read_text(encoding='utf-8'))['symbols']
        items = [(c.split('.', 1)[1], [str(Path(VALIDATION_K5) / (c.split('.', 1)[1] + '.csv'))]) for c in codes]
    return items


def build(phase, round_name):
    window = ROUNDS[round_name][1]
    loaded = [(symbol, *sessions(paths)) for symbol, paths in universe(phase, round_name)]
    _, reference = sessions([str(Path(folder) / 'AAPL.csv') for folder in SELECT_K5['core']])
    calendar = sorted(reference.union(*(seen for _, _, seen in loaded)))  # half days kept: they break C1 chains
    records = []
    for symbol, bars, _ in loaded:
        weekly, mon_wed = daily_k.schedule(symbol)
        earnings = daily_k.reaction_days(symbol, calendar)
        events = events_by_day(symbol) if round_name == 'b' else None
        if round_name == 'b' and events is None:
            continue
        records += features(symbol, bars, calendar, side_tables(symbol), weekly, mon_wed, earnings, events, window)
    return records


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('phase', choices=('select', 'validate'))
    parser.add_argument('--round', choices=('a', 'b'), required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--select-report', type=Path)
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error('refusing to overwrite ' + str(args.out))
    if hashlib.sha256(PREREG.read_bytes()).hexdigest() != PREREG_SHA256:
        raise SystemExit('P3_PREREG.md changed after registration')
    names, window, half, minimum, valid_min = ROUNDS[args.round]
    report = {'study': 'P3' + args.round, 'phase': args.phase, 'preregistration_sha256': PREREG_SHA256,
              'code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'window': window}
    if args.phase == 'validate':
        if args.select_report is None:
            parser.error('validate needs --select-report')
        judged = json.loads(args.select_report.read_text(encoding='utf-8'))['passed']
        if not judged:
            parser.error('no candidate passed selection; validation names stay closed')
    records = build(args.phase, args.round)
    report['name_days'] = len(records)
    report['names'] = len({r['symbol'] for r in records})
    results = {name: summarize(picks(records, name), half) for name in names}
    if args.phase == 'select':
        for result in results.values():
            result['gates'] = select_gates(result, minimum)
        report['passed'] = [name for name, r in results.items() if all(r['gates'].values())]
    else:
        for name in judged:
            results[name]['gates'] = validate_gates(results[name], valid_min)
        report.update(judged=judged, validated=[name for name in judged if all(results[name]['gates'].values())])
    report['results'] = results
    for name, r in results.items():
        if not r.get('picks'):
            print('%-18s no picks' % name)
            continue
        print('%-18s picks %4d dates %3d target %5.1f%% stop %5.1f%% chop %5.1f%% payoff %+.3f (%+.3f..%+.3f) edge %+5.1f%% (%+5.1f..%+5.1f) opt %s' % (
            name, r['picks'], r['dates'], 100 * r['target_rate'], 100 * r['stop_rate'], 100 * r['chop_rate'], r['payoff'],
            r['payoff_ci95'][0], r['payoff_ci95'][1], 100 * r['edge'], 100 * r['edge_ci95'][0], 100 * r['edge_ci95'][1],
            None if r['option_gross_mean'] is None else '%+.0f%%/%+.0f%%' % (100 * r['option_gross_mean'], 100 * r['option_gross_median'])))
    print({key: report[key] for key in ('name_days', 'names', 'passed', 'judged', 'validated') if key in report})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=1, default=str)
        handle.write('\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
