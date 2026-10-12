"""SV2: replay the session on years of real underlying 1m with the calibrated option proxy (notes/SV2_PREREG.md).

    python3 -m studies.us_0dte_picks.sv2 --raw data/sv2-stock-raw --out studies/us_0dte_picks/reports/sv2.json

Pass 1 (one symbol per worker): new flow N (v6.6, CALL and PUT on their own signals) for every
symbol-day, old flow O (open_hold_v3 on the opening-gap side) for the pool, and the selection
features. Pass 2: G13 random-entry replays for the pool. Then the pre-registered checks.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from collections import defaultdict
from datetime import date, datetime, timedelta
from itertools import groupby
from multiprocessing import Pool
from pathlib import Path
from statistics import mean

from custody.dataset import Case, CaseData
from custody.evaluate import ACCOUNT_BUDGET_USD, _force_entry, run_strategy, simulate
from custody.models import ET, Session
from custody.registry import Registry
from custody.strategy import build_strategy

from .fetch_sv1 import OUTSIDE, POOL, option_code
from .proxy import atm_strike, option_bars
from .sv1 import NEW, OLD

CALIBRATION = Path(__file__).parent / 'reports' / 'sv2_calibration.json'
FIRST_DAY, LAST_DAY = '2023-06-28', '2026-08-14'
SPLIT_GAP, SPLIT_COOLDOWN = 0.25, 20
SEGMENTS = (('2023H2', '2023-01-01', '2023-12-31'), ('2024', '2024-01-01', '2024-12-31'),
            ('2025', '2025-01-01', '2025-12-31'), ('2026', '2026-01-01', '2026-12-31'))
G13_DRAWS, G13_SEED, G13_MAX_P = 200, 20261002, 0.10
BOOT_DRAWS, PERM_DRAWS, MAX_P = 2000, 10000, 0.10
FLATTEN_MINUTE = 375
LABEL_BAND = 0.25


# ------------------------------------------------------------------ inputs
def _read(path):
    with open(path, newline='', encoding='utf-8') as fh:
        return list(csv.DictReader(fh))


def outside_strike(reference):
    step = 0.5 if reference < 25 else 1.0 if reference < 100 else 2.5
    low = (reference // step) * step
    return round(min((low, low + step), key=lambda k: (abs(k - reference), k)), 3)


def daily_context(raw, name):
    """Per trading day: prev close, ATR20 fraction, earnings reaction, K4B (wide-range high-volume prior day)."""
    rows = [{'day': r['time_key'][:10], **{k: float(r[k]) for k in ('open', 'high', 'low', 'close', 'volume')}}
            for r in _read(raw / 'kday' / (name + '.csv'))]
    days = [r['day'] for r in rows]
    tr = [None] + [max(r['high'], p['close']) - min(r['low'], p['close']) for p, r in zip(rows, rows[1:])]
    reactions = set()
    path = raw / 'earnings' / (name + '.json')
    for item in json.loads(path.read_text(encoding='utf-8')) if path.exists() else []:
        pub, kind = str(item.get('pub_trading_day_str', ''))[:10], str(item.get('pub_type', ''))
        if pub in days:
            idx = days.index(pub) + (1 if 'AFTER' in kind.upper() else 0)
            if idx < len(days):
                reactions.add(days[idx])
    out = {}
    for i in range(22, len(rows)):
        p = i - 1  # previous completed day
        atr = mean(tr[p - 19:p + 1])
        atr_before_prev = mean(tr[p - 20:p])
        avg_volume = mean(r['volume'] for r in rows[p - 20:p])
        prev = rows[p]
        span = prev['high'] - prev['low']
        at_end = span > 0 and min(prev['close'] - prev['low'], prev['high'] - prev['close']) <= 0.25 * span
        out[rows[i]['day']] = {'prev_close': prev['close'], 'atr_fraction': atr / prev['close'], 'index': i,
                               'earnings_reaction': rows[i]['day'] in reactions,
                               'k4b': prev['volume'] >= 2 * avg_volume and tr[p] >= 1.5 * atr_before_prev and at_end}
    return out, days


def volatility(raw, name):
    rows = [(r['time'][:10], float(r['iv']) / 100, float(r['hv']) / 100) for r in _read(raw / 'vol' / (name + '.csv'))
            if r['iv'] not in ('', 'nan') and r['hv'] not in ('', 'nan') and float(r['iv']) > 0]
    return sorted(rows)


def minute_days(raw, name, wanted):
    """Yield one complete regular session at a time from the chronological raw CSV."""
    from custody.marketdata import Bar
    previous = ''
    with (raw / 'k1m' / (name + '.csv')).open(newline='', encoding='utf-8') as fh:
        for day, rows in groupby(csv.DictReader(fh), key=lambda r: r['time_key'][:10]):
            if day <= previous:
                raise ValueError('minute CSV must be ordered by day: ' + name)
            previous = day
            if day not in wanted:
                continue
            bars = [Bar('US.' + name, datetime.fromisoformat(r['time_key']).replace(tzinfo=ET),
                        *(float(r[k]) for k in ('open', 'high', 'low', 'close', 'volume'))) for r in rows]
            bars = sorted({b.close_time: b for b in bars}.values(), key=lambda b: b.close_time)
            opens = datetime.fromisoformat(day + 'T09:30').replace(tzinfo=ET)
            if [b.close_time for b in bars] == [opens + timedelta(minutes=i) for i in range(1, 391)]:
                yield day, tuple(bars)


def session(day):
    opens = datetime.fromisoformat(day + 'T09:30').replace(tzinfo=ET)
    return Session(day, opens, opens.replace(hour=16, minute=0))


def case_data(symbol, day, bars, direction, prev_close, iv, k, w, pool):
    reference = bars[0].open
    strike = atm_strike(symbol, reference) if pool else outside_strike(reference)
    right = 'CALL' if direction == 'LONG' else 'PUT'
    contract = option_code(symbol, day, right, strike)
    sess = session(day)
    case = Case(symbol, contract, day, direction, strike, prev_close, sess.closes.isoformat(), 'both_sides_atm_at_open')
    return CaseData(case, sess, bars, option_bars(bars, sess, strike, right, iv, k, w, contract))


def symbol_days(raw, name):
    """The evaluated days of one symbol with their context, after the hygiene rules."""
    context, kdays = daily_context(raw, name)
    vols = volatility(raw, name)
    wanted = {d for d in context if FIRST_DAY <= d <= LAST_DAY}
    blocked = set()
    for d, bars in minute_days(raw, name, wanted):
        if abs(bars[0].open / context[d]['prev_close'] - 1) > SPLIT_GAP:
            i = context[d]['index']
            blocked |= set(kdays[i:i + SPLIT_COOLDOWN + 1])
        prior = [v for v in vols if v[0] < d]
        if d in blocked or not prior or date.fromisoformat(d).weekday() not in (0, 2, 4):
            continue
        _, iv, hv = prior[-1]
        yield d, dict(context[d], iv=iv, hv=hv, bars=bars)


# ------------------------------------------------------------------ pass 1
def _setup(raw, k, w):
    global RAW, K, W, ITEMS
    RAW, K, W = raw, k, w
    registry = Registry()
    ITEMS = {NEW: registry.get(NEW), OLD: registry.get(OLD)}


def pass1(symbol):
    name, pool = symbol[3:], symbol in POOL
    if not (RAW / 'k1m' / (name + '.csv')).exists():
        return symbol, None
    units = []
    for day, ctx in symbol_days(RAW, name):
        bars = ctx['bars']
        gap = bars[0].open / ctx['prev_close'] - 1
        unit = {'symbol': symbol, 'day': day, 'pool': pool, 'gap': gap,
                'gap_atr': abs(gap) / ctx['atr_fraction'] if ctx['atr_fraction'] > 0 else 0.0,
                'hv_iv': ctx['hv'] / ctx['iv'], 'earnings_reaction': ctx['earnings_reaction'], 'k4b': ctx['k4b'],
                'new': {}, 'old': None}
        for direction in ('LONG', 'SHORT'):
            data = case_data(symbol, day, bars, direction, ctx['prev_close'], ctx['iv'], K, W, pool)
            t = run_strategy(data, ITEMS[NEW])
            unit['new'][direction] = {'minute': t['entry']['minute'] if t['entry'] else None,
                                      'fill_minute': t['entry']['fill_minute'] if t['entry'] else None,
                                      'ret': t['net_return']}
            side = 'LONG' if gap > 0 else 'SHORT' if gap < 0 else None
            if pool and direction == side:
                o = run_strategy(data, ITEMS[OLD])
                unit['old'] = {'direction': side, 'ret': o['net_return'],
                               'fill_minute': o['entry']['fill_minute'] if o['entry'] else None}
        units.append(unit)
    return symbol, units


def spy_regimes(raw):
    out = {}
    for day, bars in minute_days(raw, 'SPY', _all_days(raw)):
        cut = bars[:FLATTEN_MINUTE]
        span = max(b.high for b in cut) - min(b.low for b in cut)
        net = (cut[-1].close - cut[0].open) / span if span > 0 else 0.0
        out[day] = 'up' if net >= LABEL_BAND else 'down' if net <= -LABEL_BAND else 'chop'
    return out


def _all_days(raw):
    return {r['time_key'][:10] for r in _read(raw / 'kday' / 'SPY.csv') if FIRST_DAY <= r['time_key'][:10] <= LAST_DAY}


# ------------------------------------------------------------------ pass 2 (G13)
def pass2(job):
    symbol, tasks = job  # tasks: list of (day, direction, minute)
    name = symbol[3:]
    item, params = ITEMS[NEW], ITEMS[NEW]['config']['params']
    out = {}
    by_day = {day: list(rows) for day, rows in groupby(tasks, key=lambda t: t[0])}
    for day, ctx in symbol_days(RAW, name):
        if day not in by_day:
            continue
        built = {}
        for _, direction, minute in by_day[day]:
            if direction not in built:
                built[direction] = case_data(symbol, day, ctx['bars'], direction, ctx['prev_close'], ctx['iv'], K, W, True)
            data = built[direction]
            engine = _force_entry(build_strategy(item, direction, data.session, data.case.strike), minute)
            out[day, direction, minute] = simulate(data, engine, params)['net_return'] or 0.0
    return symbol, out


# ------------------------------------------------------------------ scoring
def usd(x):
    return (x or 0.0) * ACCOUNT_BUDGET_USD


def account(trades):
    """trades: list of (day, fill_minute, usd). Same quantities as custody's account view."""
    trades = sorted(trades)
    pnl = [x for _, _, x in trades]
    wins, losses = [x for x in pnl if x > 0], [-x for x in pnl if x < 0]
    equity = peak = dd = 0.0
    streak = worst = 0
    by_day = defaultdict(float)
    for d, _, x in trades:
        equity += x
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
        streak = streak + 1 if x < 0 else 0
        worst = max(worst, streak)
        by_day[d] += x
    return {'trades': len(pnl), 'win_rate': len(wins) / len(pnl) if pnl else None,
            'average_win_usd': mean(wins) if wins else None, 'average_loss_usd': mean(losses) if losses else None,
            'payoff_ratio': mean(wins) / mean(losses) if wins and losses else None,
            'expectancy_usd': mean(pnl) if pnl else None, 'profit_factor': sum(wins) / sum(losses) if losses else None,
            'total_usd': sum(pnl), 'max_drawdown_usd': dd, 'max_consecutive_losses': worst,
            'worst_day_usd': min(by_day.values()) if by_day else None, 'best_day_usd': max(by_day.values()) if by_day else None}


def new_trades(units):
    return [(u['day'], s['fill_minute'], usd(s['ret'])) for u in units for s in u['new'].values() if s['ret'] is not None]


def old_trades(units):
    return [(u['day'], u['old']['fill_minute'], usd(u['old']['ret'])) for u in units if u['old'] and u['old']['ret'] is not None]


def unit_usd(u):
    return sum(usd(s['ret']) for s in u['new'].values())


def day_totals(trades, days):
    out = {d: 0.0 for d in days}
    for d, _, x in trades:
        out[d] += x
    return out


def boot_low(per_day, draws=BOOT_DRAWS, seed=20261002):
    values = list(per_day.values())
    rng = random.Random(seed)
    totals = sorted(sum(rng.choice(values) for _ in values) for _ in range(draws))
    return {'low_95': totals[int(0.025 * draws)], 'high_95': totals[int(0.975 * draws) - 1],
            'share_above_zero': sum(x > 0 for x in totals) / draws}


def first_two(units):
    by_day = defaultdict(list)
    for u in units:
        first = [s['fill_minute'] for s in u['new'].values() if s['fill_minute'] is not None]
        if first:
            by_day[u['day']].append((min(first), u['symbol'], u))
    kept = [u for rows in by_day.values() for _, _, u in sorted(rows, key=lambda r: r[:2])[:2]]
    return new_trades(kept)


def g13_tasks(cases):
    """The custody sampling order: per draw, per entered case, one of the strategy's own entry minutes."""
    entered = [c for c in cases if c['minute'] is not None]
    minutes = [c['minute'] for c in entered]
    rng = random.Random(G13_SEED)
    draws = [[rng.choice(minutes) for _ in entered] for _ in range(G13_DRAWS)]
    return entered, draws


def selection_s1(units, seed=20261002):
    by_day = defaultdict(list)
    for u in units:
        tier = 2 if u['earnings_reaction'] else 1 if u['k4b'] else 0
        by_day[u['day']].append(((-tier, -(u['gap_atr'] + u['hv_iv']), u['symbol']), unit_usd(u)))
    days = [d for d, rows in by_day.items() if len(rows) >= 3]
    if not days:
        return None
    top = [x for d in days for _, x in sorted(by_day[d])[:2]]
    everyone = [x for d in days for _, x in by_day[d]]
    observed = mean(top)
    rng = random.Random(seed)
    ge = sum(mean(x for d in days for x in rng.sample([v for _, v in by_day[d]], 2)) >= observed for _ in range(PERM_DRAWS))
    p = (ge + 1) / (PERM_DRAWS + 1)
    return {'days': len(days), 'top2_mean_usd': observed, 'pool_mean_usd': mean(everyone), 'p_vs_random_two': p,
            'passed': observed > mean(everyone) and p <= MAX_P}


def event_test(units, flag, seed=20261002):
    by_day = defaultdict(list)
    for u in units:
        by_day[u['day']].append((flag(u), unit_usd(u)))
    events = [x for rows in by_day.values() for f, x in rows if f]
    plain = [x for rows in by_day.values() for f, x in rows if not f]
    if not events or not plain:
        return None
    observed = mean(events) - mean(plain)
    total, n_event = sum(events) + sum(plain), len(events)
    n_plain = len(plain)
    mixed = [(sum(f for f, _ in rows), [x for _, x in rows]) for rows in by_day.values() if 0 < sum(f for f, _ in rows) < len(rows)]
    fixed_event = sum(x for rows in by_day.values() if all(f for f, _ in rows) for _, x in rows)
    rng = random.Random(seed)
    ge = 0
    for _ in range(PERM_DRAWS):
        s = fixed_event + sum(sum(rng.sample(values, k)) for k, values in mixed)
        ge += (s / n_event - (total - s) / n_plain) >= observed
    p = (ge + 1) / (PERM_DRAWS + 1)
    return {'event_units': n_event, 'plain_units': n_plain, 'event_mean_usd': mean(events), 'plain_mean_usd': mean(plain),
            'difference_usd': observed, 'p_stratified_by_date': p, 'passed': observed > 0 and p <= MAX_P}


def score(units, regimes, g13):
    pool = [u for u in units if u['pool']]
    days = sorted({u['day'] for u in pool})
    n, o = new_trades(pool), old_trades(pool)
    n_day, o_day = day_totals(n, days), day_totals(o, days)
    diff_day = {d: n_day[d] - o_day[d] for d in days}
    segments = {name: sum(v for d, v in n_day.items() if lo <= d <= hi) for name, lo, hi in SEGMENTS}
    n_boot, diff_boot = boot_low(n_day), boot_low(diff_day)
    checks = {'T1_new_total_and_boot_low_above_zero': sum(n_day.values()) > 0 and n_boot['low_95'] > 0,
              'T2_new_minus_old_and_boot_low_above_zero': sum(diff_day.values()) > 0 and diff_boot['low_95'] > 0,
              'T3_g13_p': g13['p_expectancy'] <= G13_MAX_P,
              'T4_segments_positive_at_least_3': sum(v > 0 for v in segments.values()) >= 3}
    fridays = [u for u in pool if date.fromisoformat(u['day']).weekday() == 4]
    by_regime = {}
    for name in ('up', 'down', 'chop'):
        sel = [u for u in pool if regimes.get(u['day']) == name]
        by_regime[name] = {'days': len({u['day'] for u in sel}), 'new': account(new_trades(sel)), 'old': account(old_trades(sel))}
    by_year = {name: {'new': account(new_trades([u for u in pool if lo <= u['day'] <= hi])),
                      'old': account(old_trades([u for u in pool if lo <= u['day'] <= hi]))} for name, lo, hi in SEGMENTS}
    outside = [u for u in units if not u['pool']]
    allu = units
    s2 = {'any_event': event_test(allu, lambda u: u['earnings_reaction'] or u['k4b']),
          'earnings_reaction': event_test(allu, lambda u: u['earnings_reaction']),
          'k4b_next_day': event_test(allu, lambda u: u['k4b'])}
    return {
        'days': len(days), 'symbol_days': len(pool),
        'new': account(n), 'old': account(o), 'new_minus_old_usd': sum(diff_day.values()),
        'new_boot': n_boot, 'new_minus_old_boot': diff_boot, 'segments_new_usd': segments, 'g13': g13,
        'checks': checks, 'timing_passed': all(checks.values()),
        'report_only': {'fridays': {'days': len({u['day'] for u in fridays}), 'new': account(new_trades(fridays)),
                                    'old': account(old_trades(fridays))},
                        'by_spy_regime': by_regime, 'by_segment': by_year, 'new_first_two_symbols': account(first_two(pool)),
                        'by_symbol': {s: {'new_usd': sum(unit_usd(u) for u in pool if u['symbol'] == s),
                                          'old_usd': sum(usd(u['old']['ret']) for u in pool if u['symbol'] == s and u['old'])}
                                      for s in POOL}},
        'selection': {'S1_rank_top2': selection_s1(pool), 'S2_event_days': s2,
                      'S2_passed': bool(s2['any_event'] and s2['any_event']['passed']),
                      'S3_pool_vs_outside_report_only': {
                          'pool_symbol_days': len(pool), 'pool_mean_usd': mean(unit_usd(u) for u in pool),
                          'outside_symbol_days': len(outside),
                          'outside_mean_usd': mean(unit_usd(u) for u in outside) if outside else None,
                          'outside_by_symbol': {s: {'days': len(v), 'mean_usd': mean(v)} for s, v in sorted(
                              {s: [unit_usd(u) for u in outside if u['symbol'] == s] for s in OUTSIDE}.items()) if v}}},
    }


def run(raw, workers=2):
    cal = json.loads(CALIBRATION.read_text(encoding='utf-8'))
    k, w = cal['k'], cal['w']
    symbols = list(POOL) + list(OUTSIDE)
    with Pool(workers, initializer=_setup, initargs=(raw, k, w)) as pool:
        results = dict(pool.imap_unordered(pass1, symbols))
        missing = [s for s, v in results.items() if v is None]
        units = [u for s in symbols if results.get(s) for u in results[s]]
        cases = [{'symbol': u['symbol'], 'day': u['day'], 'direction': d, 'minute': s['minute'], 'ret': s['ret'] or 0.0}
                 for u in units if u['pool'] for d, s in sorted(u['new'].items())]
        cases.sort(key=lambda c: (c['symbol'], c['day'], c['direction']))
        entered, draws = g13_tasks(cases)
        jobs = defaultdict(set)
        for minutes in draws:
            for c, m in zip(entered, minutes):
                jobs[c['symbol']].add((c['day'], c['direction'], m))
        values = {}
        for symbol, out in pool.imap_unordered(pass2, [(s, sorted(t)) for s, t in jobs.items()]):
            values.update({(symbol,) + key: v for key, v in out.items()})
    observed = mean(c['ret'] for c in cases)
    base = sum(c['ret'] for c in cases if c['minute'] is None)  # unentered cases are zero either way
    expectancies = [(base + sum(values[c['symbol'], c['day'], c['direction'], m] for c, m in zip(entered, minutes))) / len(cases)
                    for minutes in draws]
    g13 = {'draws': G13_DRAWS, 'entered_cases': len(entered), 'distinct_minutes': len({c['minute'] for c in entered}),
           'strategy_expectancy': observed, 'random_expectancy_mean': mean(expectancies),
           'p_expectancy': (sum(e >= observed for e in expectancies) + 1) / (G13_DRAWS + 1)}
    regimes = spy_regimes(raw)
    result = {'preregistration': 'studies/us_0dte_picks/notes/SV2_PREREG.md', 'proxy': {'k': k, 'w': w},
              'window': [FIRST_DAY, LAST_DAY], 'missing_symbols': missing, **score(units, regimes, g13)}
    return result, units


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--raw', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--units', type=Path, help='also write per symbol-day results (jsonl)')
    args = parser.parse_args(argv)
    if args.out.exists():
        raise SystemExit('refuse: SV2 is scored once; %s exists' % args.out)
    result, units = run(args.raw)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    if args.units:
        args.units.write_text(''.join(json.dumps(u) + '\n' for u in units), encoding='utf-8')
    print(json.dumps({k: result[k] for k in ('checks', 'timing_passed', 'new_minus_old_usd')}
                     | {'S1': result['selection']['S1_rank_top2'], 'S2_passed': result['selection']['S2_passed']}, indent=2))


if __name__ == '__main__':
    main()
