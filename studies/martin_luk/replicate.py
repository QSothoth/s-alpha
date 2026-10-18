"""Martin Luk as the first case of skills/trader-replication: stage masks on the point-in-time US daily panel,
scored against his public trades (notes/trades.csv) and against random entry on the same stocks.

    nice -n 19 /opt/futu-opend/venv/bin/python -m studies.martin_luk.replicate r19
"""
from __future__ import annotations

from dataclasses import replace
import csv
import json
import sys
from pathlib import Path

import numpy as np

from studies.trader_replication import edge as E, fidelity as F, ledger as L, system as Y

from . import intraday as I, luk, selection as S

LEDGER = Path(__file__).resolve().parent / 'notes' / 'trades.csv'
CUTOFF = '2026-04-01'           # PREREG_R19: selection trades start before this day, validation trades on or after


def prev(x):
    """Value as of the previous day (False / NaN on the first day)."""
    out = np.zeros_like(x) if x.dtype == bool else np.full_like(x, np.nan)
    out[1:] = x[:-1]
    return out


def pct_rank(x, pool):
    """Per-day percentile (0..1) of x among pool names; NaN elsewhere."""
    out = np.full(x.shape, np.nan)
    for t in range(len(x)):
        ok = pool[t] & np.isfinite(x[t])
        n = ok.sum()
        if n >= 20:
            v = x[t, ok]
            out[t, np.flatnonzero(ok)] = (np.argsort(np.argsort(v)) + .5) / n
    return out


def us_arrays():
    """Indicators on the broad US panel (3433 names incl. ones that later went cold; delisted names missing)."""
    return market_arrays('us')


def market_arrays(market):
    """Historical daily panels of 2026-10 liquidity-selected universes; historical filters do not remove
    the initial universe's survivorship/selection bias in any of the three markets."""
    b = S.broad() if market == 'us' else luk.load(market)
    A = dict(days=b['days'] if market == 'us' else b['dates'], codes=b['codes'], market=market)
    for k in ('open', 'high', 'low', 'close', 'turnover'):
        A[k] = b[k].astype(float)
    A['raw'] = b['raw_close'].astype(float)
    del b
    c, h, l = A['close'], A['high'], A['low']
    A['to20'] = luk.rolling_mean(A['turnover'], 20)
    A['adr'] = luk.rolling_mean(h / l - 1, 20) * 100
    A['e9'], A['e21'], A['e50'] = luk.ema(c, 9), luk.ema(c, 21), luk.ema(c, 50)
    with np.errstate(invalid='ignore', divide='ignore'):
        A['rank_pool'] = ((A['raw'] >= 1) & (A['to20'] >= 2e6)) if market == 'us' else np.isfinite(A['to20'])
        A['pool'] = (A['raw'] >= 5) & (A['to20'] >= 20e6) & (A['adr'] >= 4)
        A['stack'] = (A['e9'] > A['e21']) & (A['e21'] > A['e50'])
        A['tight'] = ((h <= luk.lag(h)) & (l >= luk.lag(l))) | ((h / l - 1) * 100 <= .5 * A['adr'])
        for hz in (21, 63, 126):
            A[f'pr{hz}'] = pct_rank(c / luk.lag(c, hz) - 1, A['rank_pool'])
    A['has'] = np.isfinite(c)
    return A


def weekly_ema(close, days, n):
    """Weekly EMA as a chart shows it during the week: completed weeks plus the running week's latest close."""
    import datetime as dt
    week = np.array([dt.date.fromisoformat(str(d)).isocalendar()[:2] for d in days])
    wid = week[:, 0] * 100 + week[:, 1]
    a = 2 / (n + 1)
    out = np.full_like(close, np.nan)
    done = np.full(close.shape[1], np.nan)          # EMA through the last completed week
    last = np.full(close.shape[1], np.nan)          # latest close seen
    for t in range(len(days)):
        if t and wid[t] != wid[t - 1]:              # the previous week just completed
            fresh = np.isnan(done) & np.isfinite(last)
            done = np.where(fresh, last, np.where(np.isfinite(last), a * last + (1 - a) * done, done))
        last = np.where(np.isfinite(close[t]), close[t], last)
        out[t] = np.where(np.isnan(done), last, a * last + (1 - a) * done)
    return out


def w2_mask(A, top=.02, need=2, lookback=20):
    """Names on >= `need` of the 1/3/6-month top-`top` lists on one day within the past `lookback` days (as of t-1)."""
    n = sum(((A[f'pr{hz}'] >= 1 - top) & A['rank_pool']).astype(np.int8) for hz in (21, 63, 126))
    return S._past_any(n >= need, lookback)


def setup_close(A):
    """R17 G1 base setup on day t, confirmed by day t's close."""
    c, h, l = A['close'], A['high'], A['low']
    e9p, e21p = prev(A['e9']), prev(A['e21'])
    with np.errstate(invalid='ignore'):
        return ((l < e21p) & (c > e21p)) | ((l < e9p) & (c > e9p)) | (prev(A['tight']) & (c > prev(h)))


def setup_intraday(A):
    """R19's report-only P4': PDH break after a tight day, a touch of EMA9/21 that holds into the close, or a 10% gap
    (the 'holds' part uses the day's close, so this is a daily description, not an intraday trigger)."""
    o, c, h, l = A['open'], A['close'], A['high'], A['low']
    e9p, e21p = prev(A['e9']), prev(A['e21'])
    with np.errstate(invalid='ignore', divide='ignore'):
        brk = prev(A['tight']) & (h > prev(h))
        touch = ((l <= e9p) & (c >= e9p)) | ((l <= e21p) & (c >= e21p))
        gap = o / prev(c) - 1 >= .10
    return brk | touch | gap


def baseline_stages(A):
    return [('P0 has data', A['has']),
            ('P1 pool', prev(A['pool'])),
            ('P2 W2', w2_mask(A)),
            ('P3 stack', prev(A['stack'])),
            ('P4 close setup', setup_close(A))]


def features(A, located):
    """Point-in-time features of each located trade on its entry day (window start for window trades)."""
    rows = []
    for t, j, a, b in located:
        d = np.searchsorted(A['days'], t.entry_date) if t.dated else a
        p = d - 1
        f = A['raw'][p, j] / A['close'][p, j]
        rows.append(dict(
            id=t.id, ticker=t.ticker, day=str(A['days'][d]), setup=t.setup, price=round(float(A['raw'][p, j]), 2),
            to20_m=round(float(A['to20'][p, j]) / 1e6, 1), adr=round(float(A['adr'][p, j]), 1),
            pr21=round(float(A['pr21'][p, j]), 3), pr63=round(float(A['pr63'][p, j]), 3),
            pr126=round(float(A['pr126'][p, j]), 3), stack=bool(A['stack'][p, j]),
            vs_e9=round(float(A['close'][p, j] / A['e9'][p, j] - 1), 3),
            vs_e21=round(float(A['close'][p, j] / A['e21'][p, j] - 1), 3),
            vs_e50=round(float(A['close'][p, j] / A['e50'][p, j] - 1), 3),
            gap=round(float(A['open'][d, j] / A['close'][p, j] - 1), 3),
            day_chg=round(float(A['close'][d, j] / A['close'][p, j] - 1), 3),
            low_vs_e9=round(float(A['low'][d, j] / A['e9'][p, j] - 1), 3),
            pdh_break=bool(A['high'][d, j] > A['high'][p, j]), prior_tight=bool(A['tight'][p, j]),
            raw_open=round(float(A['open'][d, j] * f), 2)))
    return rows


def r19():
    trades = L.load(LEDGER)
    sel, _ = L.split(trades, CUTOFF)
    A = us_arrays()
    longs = [t for t in sel if t.side == 'long']
    loc_all, missing = F.locate(longs, A['days'], A['codes'], has=A['has'])
    loc_dated = [x for x in loc_all if x[0].dated]
    stages = baseline_stages(A)
    pool = A['has']
    out = dict(trades=len(sel), longs=len(longs), located=len(loc_all), dated=len(loc_dated), missing=missing)
    out['funnel_all'] = F.funnel(stages[:4], loc_all, pool)
    out['funnel_dated'] = F.funnel(stages, loc_dated, pool)
    alt = stages[:4] + [('P4\' intraday setup', setup_intraday(A))]
    out['funnel_dated_intraday'] = F.funnel(alt, loc_dated, pool)
    cur = None
    for name, m in stages:
        cur = m if cur is None else cur & m
        out.setdefault('width', {})[name] = F.width(cur, A['days'], '2024-01-02', '2026-03-31', pool)
    out['features'] = features(A, loc_all)
    for k in ('funnel_all', 'funnel_dated', 'funnel_dated_intraday'):
        for r in out[k]:
            print(k, r['stage'], f"{r['hits']}/{r['n']} recall {r['recall']:.2f} random {r['random']:.3f} "
                  f"lift {r['lift']:.1f}", flush=True)
    print(json.dumps(out['width'], indent=0))
    (I.OUT / 'r19_fidelity_baseline.json').write_text(json.dumps(out, indent=1))


POOLS = {'U0': (5, 20e6, 4), 'U1': (1, 100e6, 4), 'U2': (1, 100e6, 3), 'U3': (1, 50e6, 4), 'U4': (2, 50e6, 3),
         'U5': (5, 100e6, 3), 'U6': (2, 50e6, 2)}


def pool_mask(A, price, turnover, adr):
    """Tradeable pool as of t-1: raw close, 20-day average dollar volume and ADR20 floors."""
    with np.errstate(invalid='ignore'):
        return prev((A['raw'] >= price) & (A['to20'] >= turnover) & (A['adr'] >= adr))


def located_longs(A, trades):
    return F.locate([t for t in trades if t.side == 'long'], A['days'], A['codes'], has=A['has'])[0]


def r20():
    trades = L.load(LEDGER)
    sel, val = L.split(trades, CUTOFF)
    A = us_arrays()
    ls, lv = located_longs(A, sel), located_longs(A, val)
    out = {'select': {}, 'validate': {}}
    for k, spec in POOLS.items():
        m = pool_mask(A, *spec)
        r = F.recall(m, ls, A['has'])
        w = F.width(m, A['days'], '2024-01-02', '2026-03-31')
        out['select'][k] = dict(hits=r['hits'], n=r['n'], recall=r['recall'], width=w,
                                lost=[i for i, ok in r['per_trade'].items() if not ok])
        print('select', k, out['select'][k], flush=True)
    ok = {k: v for k, v in out['select'].items() if k != 'U0' and v['width']['median'] <= 600}
    best = max(ok, key=lambda k: (ok[k]['hits'], -ok[k]['width']['median']))     # ties: the narrower pool
    for k in ('U0', best):
        r = F.recall(pool_mask(A, *POOLS[k]), lv, A['has'])
        out['validate'][k] = dict(hits=r['hits'], n=r['n'], recall=r['recall'],
                                  lost=[i for i, ok_ in r['per_trade'].items() if not ok_])
        print('validate', k, out['validate'][k], flush=True)
    out['chosen'] = best
    out['passed'] = bool(out['validate'][best]['recall'] >= out['validate']['U0']['recall'])
    print('chosen', best, 'passed', out['passed'])
    (I.OUT / 'r20_pool.json').write_text(json.dumps(out, indent=1))


def chosen(name, fallback):
    """Choice of an earlier round from its report (the fallback when it did not pass)."""
    path = I.OUT / name
    if not path.exists():
        raise SystemExit(f'run the round that writes {name} first')
    res = json.loads(path.read_text())
    return res['chosen'] if res.get('passed') else fallback


def pdh_events(A, pool, horizon=10):
    """Day-t breaks of the prior-day high by pool names: fill at max(open, prior high), result `horizon` closes later."""
    h, o, c = A['high'], A['open'], A['close']
    ph = prev(h)
    with np.errstate(invalid='ignore', divide='ignore'):
        ev = pool & (h > ph) & np.isfinite(o)
        fill = np.fmax(o, ph)
        out = np.full_like(c, np.nan)
        out[:-horizon] = c[horizon:] / fill[:-horizon] - 1
    return ev, np.where(ev, out, np.nan)


def strength_lists(A, pool):
    c = A['close']
    with np.errstate(invalid='ignore', divide='ignore'):
        r1 = np.where(pool, c / luk.lag(c) - 1, np.nan)
        top1 = (r1 >= np.nanquantile(r1, .98, axis=1)[:, None]) & pool
        k1 = A['pr21'] >= .9
        k2 = k1 | (A['pr63'] >= .9) | (A['pr126'] >= .9)
        k3 = np.zeros_like(k1)
        for hz in (21, 63, 126):
            k3 |= c / luk.lag(c, hz) - 1 >= .30
        k7 = (A['pr21'] >= .95) | (A['pr63'] >= .95) | (A['pr126'] >= .95)
    rp = A['rank_pool']
    return {'K0': w2_mask(A), 'K1': S._past_any(k1 & rp, 20), 'K2': S._past_any(k2 & rp, 20),
            'K3': S._past_any(k3 & rp, 20), 'K4': S._past_any((k1 & rp) | top1, 20),
            # R21b: one-week retention (his weekend leader scan) or a higher bar
            'K5': S._past_any(k1 & rp, 5), 'K6': S._past_any(k2 & rp, 5), 'K7': S._past_any(k7 & rp, 20),
            'K8': S._past_any(k3 & rp, 5), 'K9': S._past_any((k1 & rp) | top1, 5)}


def strength_choice():
    """R21b when it passed, else R21 when it passed, else the reference W2."""
    for name in ('r21b_strength.json', 'r21_strength.json'):
        if (I.OUT / name).exists():
            res = json.loads((I.OUT / name).read_text())
            if res.get('passed'):
                return res['chosen']
    return 'K0'


def r21():
    A = us_arrays()
    ls, lv, seg = common(A)
    pool = stage_inputs(A, 21)['pool']
    ev, res = pdh_events(A, pool)
    grp = E.groups(prev(A['adr']), pool, A['days'] >= '2024-01-02')
    lists = strength_lists(A, pool)
    round_lists(A, pool, {k: lists[k] for k in ('K0', 'K1', 'K2', 'K3', 'K4')}, ls, lv, ev, res, grp, seg, 'K0', 150,
                'r21_strength.json', 'R21')


def r21b():
    A = us_arrays()
    ls, lv, seg = common(A)
    pool = stage_inputs(A, 21)['pool']
    ev, res = pdh_events(A, pool)
    grp = E.groups(prev(A['adr']), pool, A['days'] >= '2024-01-02')
    lists = strength_lists(A, pool)
    round_lists(A, pool, {k: lists[k] for k in ('K0', 'K5', 'K6', 'K7', 'K8', 'K9')}, ls, lv, ev, res, grp, seg,
                'K0', 150, 'r21b_strength.json', 'R21b')


def stage_inputs(A, upto):
    """Pool, strength list and watchlist chosen by the rounds before `upto` (fallbacks when a round did not pass)."""
    pool = pool_mask(A, *POOLS[chosen('r20_pool.json', 'U0')])
    out = dict(pool=pool)
    if upto > 21:
        k = strength_choice()
        out['k'] = pool & strength_lists(A, pool)[k]
    if upto > 22:
        v = watch_choice()
        out['w'] = out['k'] & watch_lists(A)[v]
    return out


def watch_lists(A):
    stack = prev(A['stack'])
    w9 = weekly_ema(A['close'], A['days'], 9)
    wk = prev(w9 > weekly_ema(A['close'], A['days'], 21))
    was_not = S._past_any(~A['stack'], 10)                     # some day in t-10..t-1 not stacked
    not_before = prev(was_not)                                 # ... shifted: some day in t-11..t-2
    with np.errstate(invalid='ignore'):
        above50 = prev(A['close'] > A['e50'])
    ones = np.ones_like(stack)
    with np.errstate(invalid='ignore'):
        big = prev(A['to20'] >= 100e6)                          # R22b: he only adds $100M+ names to watchlists
        fast = prev(A['adr'] >= 5)
    return {'V0': stack, 'V1': stack | wk, 'V2': above50, 'V3': stack & not_before, 'V4': ones,
            'V5': (stack | wk) & big, 'V6': stack & big, 'V7': above50 & big, 'V8': (stack | wk) & fast, 'V9': big,
            'V10': stack | prev(A['close'] > w9)}


def watch_choice():
    for name in ('r22b_watchlist.json', 'r22_watchlist.json'):
        if (I.OUT / name).exists():
            res = json.loads((I.OUT / name).read_text())
            if res.get('passed'):
                return res['chosen']
    return 'V0'


def round_lists(A, base, lists, ls, lv, ev, res, grp, seg, ref, cap, file, kind):
    """Shared R21/R22 loop: fidelity and PDH-break edge per candidate, choice on the selection segment."""
    days = A['days']
    out = {'select': {}, 'validate': {}}
    for k, m in lists.items():
        mm = base & m
        r = F.recall(mm, ls, A['has'])
        out['select'][k] = dict(hits=r['hits'], n=r['n'], recall=r['recall'], random=r['random'], lift=r['lift'],
                                width=F.width(mm, days, '2024-01-02', '2026-03-31'),
                                edge=E.excess(res, grp, ev & base, m, seg['select']),
                                lost=[i for i, ok in r['per_trade'].items() if not ok])
        print(kind, 'select', k, {a: b for a, b in out['select'][k].items() if a != 'lost'}, flush=True)
    ok = {k: v for k, v in out['select'].items()
          if k != ref and v['width']['median'] <= cap and v['edge'].get('excess', -1) >= 0}
    best = max(ok, key=lambda k: (ok[k]['hits'], -ok[k]['width']['median'])) if ok else None
    for k in [ref] + ([best] if best else []):
        mm = base & lists[k]
        r = F.recall(mm, lv, A['has'])
        out['validate'][k] = dict(hits=r['hits'], n=r['n'], recall=r['recall'], random=r['random'], lift=r['lift'],
                                  edge=E.excess(res, grp, ev & base, lists[k], seg['validate']),
                                  lost=[i for i, ok_ in r['per_trade'].items() if not ok_])
        print(kind, 'validate', k, {a: b for a, b in out['validate'][k].items() if a != 'lost'}, flush=True)
    out['chosen'] = best
    if best:
        v, v0 = out['validate'][best], out['validate'][ref]
        out['closer'] = bool(v['recall'] >= v0['recall'])
        out['edge_passed'] = bool(v['edge'].get('ci', [-1])[0] > 0)
        out['passed'] = out['closer']
    print(kind, 'chosen', best, {k: out.get(k) for k in ('closer', 'edge_passed')})
    (I.OUT / file).write_text(json.dumps(out, indent=1))
    return out


def common(A):
    trades = L.load(LEDGER)
    sel, val = L.split(trades, CUTOFF)
    days = A['days']
    seg = {'select': (days >= '2024-01-02') & (days <= '2024-12-31'),
           'validate': (days >= '2025-01-02') & (days <= '2026-10-16')}
    return located_longs(A, sel), located_longs(A, val), seg


def r22():
    A = us_arrays()
    ls, lv, seg = common(A)
    st = stage_inputs(A, 22)
    ev, res = pdh_events(A, st['pool'])
    grp = E.groups(prev(A['adr']), st['pool'], A['days'] >= '2024-01-02')
    lists = watch_lists(A)
    round_lists(A, st['k'], {k: lists[k] for k in ('V0', 'V1', 'V2', 'V3', 'V4')}, ls, lv, ev, res, grp, seg, 'V0',
                100, 'r22_watchlist.json', 'R22')


def r22b():
    A = us_arrays()
    ls, lv, seg = common(A)
    st = stage_inputs(A, 22)
    ev, res = pdh_events(A, st['pool'])
    grp = E.groups(prev(A['adr']), st['pool'], A['days'] >= '2024-01-02')
    lists = watch_lists(A)
    round_lists(A, st['k'], {k: lists[k] for k in ('V0', 'V5', 'V6', 'V7', 'V8', 'V9')}, ls, lv, ev, res, grp, seg,
                'V0', 100, 'r22b_watchlist.json', 'R22b')


def setups(A):
    o, h, l = A['open'], A['high'], A['low']
    ph, pc = prev(h), prev(A['close'])
    e9p, e21p, adrp = prev(A['e9']), prev(A['e21']), prev(A['adr'])
    with np.errstate(invalid='ignore', divide='ignore'):
        e1 = h > ph
        e2 = prev(A['tight']) & e1
        e3 = o >= pc * (1 + np.fmax(.05, adrp / 100))
        e4 = (e9p > e21p) & (l <= e9p) & (h >= e9p)
        e21 = (e9p > e21p) & (l <= e21p) & (A['close'] >= e21p)
    return {'E1': e1, 'E2': e2, 'E3': e3, 'E4': e4, 'E5': e2 | e3 | e4, 'E21': e21}


def top_per_day(m, score, n=10):
    """Keep, per day, the n flagged names with the highest score."""
    out = np.zeros_like(m)
    for t in np.flatnonzero(m.any(1)):
        js = np.flatnonzero(m[t])
        if len(js) > n:
            js = js[np.argsort(-np.nan_to_num(score[t, js], nan=-np.inf))[:n]]
        out[t, js] = True
    return out


def setup_families(A, w):
    """Candidate setups as {name: {trigger kind: mask}}; the kind tells the 5-minute trigger what to wait for
    ('E2' break of the prior-day high, 'E3' opening-range high after a gap, 'E4' dip into EMA9 then a bar breakout)."""
    s = setups(A)
    o, h, l, c = A['open'], A['high'], A['low'], A['close']
    ph, pl, pc, e9p = prev(h), prev(l), prev(c), prev(A['e9'])
    with np.errstate(invalid='ignore', divide='ignore'):
        near = prev(np.abs(A['close'] / A['e9'] - 1) <= .03)       # R23b: prior close within 3% of the 9 EMA
        # R23c
        handshake = (o > pc * 1.01) & (l <= np.fmax(ph, e9p)) & (c > np.fmin(ph, e9p))
        wick = (o >= pl + .5 * (ph - pl)) & (o <= ph) & (h > ph)
        r3 = prev(c / luk.lag(c, 3) - 1)
        strong_close = prev((c - l) >= .5 * (h - l))
    e10 = s['E1'] & near | s['E4'] & near
    top10 = top_per_day(w & e10, prev(A['pr21']), 8)
    return {
            'E11': {'E11': handshake}, 'E12': {'E2': wick}, 'E13': {'E2': top_per_day(w & s['E1'], r3)},
            'E14': {'E2': top10 & s['E1'], 'E4': top10 & s['E4']},
            'E15': {'E2': s['E1'] & near & strong_close},'E1': {'E2': s['E1']}, 'E2': {'E2': s['E2']}, 'E3': {'E3': s['E3']}, 'E4': {'E4': s['E4']},
            'E5': {'E2': s['E2'], 'E3': s['E3'], 'E4': s['E4']},
            'E6': {'E2': s['E1'] & near},
            'E7': {'E2': s['E2'] & near, 'E3': s['E3'] & near, 'E4': s['E4'] & near},
            'E8': {'E2': top_per_day(w & s['E1'], prev(A['pr21']))},
            'E9': {'E2': top_per_day(w & s['E1'], prev(A['to20']))},
            'E10': {'E2': s['E1'] & near, 'E4': s['E4'] & near},
            'E21': {'E21': s['E21']},
            'EW1': {'E2': weekly_cached(A)['EW1']}, 'EW2': {'E2': weekly_cached(A)['EW2']}}


def weekly_breakouts(A):
    """R73: the first break of the last completed week's high, after that week was an inside week ('EW1') or a
    weekly pin bar ('EW2': lower wick >= 2 x body, close in the top third).  Weeks start on Monday; only completed
    weeks are used, and the break must be the first one this week (earlier days this week stayed below)."""
    D = np.array(A['days'], dtype='datetime64[D]').astype('int64')
    wk = (D + 3) // 7
    o, h, l, c = A['open'], A['high'], A['low'], A['close']
    ids, start = np.unique(wk, return_index=True)
    end = np.r_[start[1:], len(wk)]
    n, N = len(ids), c.shape[1]
    WO, WH, WL, WC = (np.full((n, N), np.nan) for _ in range(4))
    for k in range(n):
        for r in range(start[k], end[k]):
            WO[k] = np.where(np.isnan(WO[k]), o[r], WO[k])
            WH[k] = np.fmax(WH[k], h[r])
            WL[k] = np.fmin(WL[k], l[r])
            WC[k] = np.where(np.isfinite(c[r]), c[r], WC[k])
    with np.errstate(invalid='ignore'):
        inside = np.zeros((n, N), bool)
        inside[1:] = (WH[1:] <= WH[:-1]) & (WL[1:] >= WL[:-1])
        body = np.abs(WC - WO)
        pin = ((np.fmin(WO, WC) - WL) >= 2 * body) & ((WC - WL) >= (2 / 3) * (WH - WL)) & (WH > WL)
    k_of = np.searchsorted(ids, wk)
    ew1, ew2 = np.zeros_like(c, bool), np.zeros_like(c, bool)
    wtd = np.full(N, np.nan)                                     # this week's high before today
    for t in range(len(wk)):
        k = k_of[t]
        if t == 0 or k != k_of[t - 1]:
            wtd = np.full(N, np.nan)
        if k > 0:
            level = WH[k - 1]
            with np.errstate(invalid='ignore'):
                first = (h[t] > level) & ~(wtd > level)
            ew1[t] = first & inside[k - 1]
            ew2[t] = first & pin[k - 1]
        wtd = np.fmax(wtd, h[t])
    return {'EW1': ew1, 'EW2': ew2}


def weekly_cached(A):
    if '_weekly' not in A:
        A['_weekly'] = weekly_breakouts(A)
    return A['_weekly']


def union(fam):
    out = None
    for m in fam.values():
        out = m.copy() if out is None else out | m
    return out


def setup_round(names, file, tag, ref='E2'):
    A = us_arrays()
    trades = L.load(LEDGER)
    sel, val = L.split(trades, CUTOFF)
    ls = [x for x in located_longs(A, sel) if x[0].dated]
    lv = [x for x in located_longs(A, val) if x[0].dated]
    days = A['days']
    seg = {'select': (days >= '2024-01-02') & (days <= '2024-12-31'),
           'validate': (days >= '2025-01-02') & (days <= '2026-10-16')}
    w = stage_inputs(A, 23)['w']
    c = A['close']
    res = np.full_like(c, np.nan)
    with np.errstate(invalid='ignore', divide='ignore'):
        res[:-10] = c[10:] / c[:-10] - 1                          # buy the signal day's close, 10 closes later
    grp = E.groups(prev(A['adr']), w, days >= '2024-01-02')
    fams = setup_families(A, w)
    sets = {k: union(fams[k]) for k in set(names) | {ref}}
    out = {'select': {}, 'validate': {}}
    for k in names:
        mm = w & sets[k]
        r = F.recall(mm, ls, A['has'])
        rw = F.recall(mm, ls, w)                                  # random baseline drawn from the watchlist itself
        out['select'][k] = dict(hits=r['hits'], n=r['n'], recall=r['recall'], random_in_watchlist=rw['random'],
                                lift_in_watchlist=rw['lift'], width=F.width(mm, days, '2024-01-02', '2026-03-31'),
                                edge=E.excess(res, grp, w, sets[k], seg['select']),
                                lost=[i for i, ok in r['per_trade'].items() if not ok])
        print(tag, 'select', k, {a: b for a, b in out['select'][k].items() if a != 'lost'}, flush=True)
    ok = {k: v for k, v in out['select'].items() if v['width']['median'] <= 15 and v['edge'].get('excess', -1) >= 0}
    best = max(ok, key=lambda k: (ok[k]['hits'], -ok[k]['width']['median'])) if ok else None
    for k in [ref] + ([best] if best and best != ref else []):
        mm = w & sets[k]
        r, rw = F.recall(mm, lv, A['has']), F.recall(mm, lv, w)
        out['validate'][k] = dict(hits=r['hits'], n=r['n'], recall=r['recall'], random_in_watchlist=rw['random'],
                                  lift_in_watchlist=rw['lift'], edge=E.excess(res, grp, w, sets[k], seg['validate']),
                                  lost=[i for i, ok_ in r['per_trade'].items() if not ok_])
        print(tag, 'validate', k, {a: b for a, b in out['validate'][k].items() if a != 'lost'}, flush=True)
    out['chosen'] = best
    if best:
        v, v0 = out['validate'][best], out['validate'][ref]
        out['closer'] = bool(v['lift_in_watchlist'] > 1 and v['recall'] >= v0['recall'])
        out['edge_passed'] = bool(v['edge'].get('ci', [-1])[0] > 0)
        out['passed'] = out['closer']
    print(tag, 'chosen', best, {k: out.get(k) for k in ('closer', 'edge_passed')})
    (I.OUT / file).write_text(json.dumps(out, indent=1))


def r23():
    setup_round(['E1', 'E2', 'E3', 'E4', 'E5'], 'r23_setup.json', 'R23')


def r23b():
    setup_round(['E6', 'E7', 'E8', 'E9', 'E10'], 'r23b_setup.json', 'R23b')


def r23c():
    setup_round(['E11', 'E12', 'E13', 'E14', 'E15'], 'r23c_setup.json', 'R23c', ref='E10')


def setup_choice():
    for name in ('r23c_setup.json', 'r23b_setup.json', 'r23_setup.json'):
        if (I.OUT / name).exists():
            res = json.loads((I.OUT / name).read_text())
            if res.get('passed'):
                return res['chosen']
    return 'E5'


RULES = Y.Rules(risk=.005, max_position=.30, max_gross=2.0, trims=(3, 5), trim_frac=.15, trail='e9')


def signal_inputs(A):
    """Watchlist W* and the chosen setup's masks per trigger kind (R23b, else R23, else E5)."""
    w = stage_inputs(A, 23)['w']
    return w, {k: w & m for k, m in setup_families(A, w)[setup_choice()].items()}


def stop_cap(A, cap_max=.05):
    return np.fmin(cap_max, .5 * prev(A['adr']) / 100)


def entries_close(A, sig, cols=None):
    """N1: buy the signal day's close, stop at that day's low; priority to the most liquid names."""
    c, l = A['close'], A['low']
    cap = stop_cap(A)
    any_sig = np.zeros_like(c, bool)
    for m in sig.values():
        any_sig |= m
    if cols is not None:
        any_sig &= cols[None, :]
    out = [[] for _ in range(len(c))]
    for d, j in zip(*np.nonzero(any_sig)):
        risk = (c[d, j] - l[d, j]) / c[d, j]
        if 0 < risk <= cap[d, j]:
            out[d].append((-A['to20'][d - 1, j], j, 1, c[d, j], l[d, j], 'n1'))
    return out


def entries_next_open(A, sig, cols=None):
    """N2: buy the next open, stop at the signal day's low; skip opens more than 0.5 ADR above the signal close."""
    o, c, l = A['open'], A['close'], A['low']
    cap = stop_cap(A)
    any_sig = np.zeros_like(c, bool)
    for m in sig.values():
        any_sig |= m
    if cols is not None:
        any_sig &= cols[None, :]
    out = [[] for _ in range(len(c))]
    for d, j in zip(*np.nonzero(any_sig[:-1])):
        f = o[d + 1, j]
        if not np.isfinite(f) or f > c[d, j] * (1 + .5 * A['adr'][d, j] / 100) or f <= l[d, j]:
            continue
        if (f - l[d, j]) / f <= cap[d + 1, j]:
            out[d + 1].append((-A['to20'][d, j], j, 1, f, l[d, j], 'n2'))
    return out


def first_trigger(o5, h5, l5, kind, pdh, e9p, b_start=0):
    """(bar, fill, lod) of the first 5-minute trigger of one setup kind on one day, or None; the trigger bar is
    at or after `b_start` (R24b skips the first half hour), the low of day always counts from the open."""
    from .intraday import NB
    if np.isnan(o5[0]):
        return None
    if kind in ('E2', 'E3'):
        trig, b0 = (h5[0], 1) if kind == 'E3' or o5[0] > pdh else (pdh, 0)
        for b in range(max(b0, b_start), NB):
            if np.isfinite(h5[b]) and h5[b] >= trig:
                return b, max(trig, o5[b]), np.nanmin(l5[:b + 1])
        return None
    support = max(pdh, e9p) if kind == 'E11' else e9p           # handshake: the gap fades into the prior high or EMA9
    dipped = False
    for b in range(NB):
        if np.isnan(h5[b]):
            continue
        if dipped and b >= max(b_start, 1) and np.isfinite(h5[b - 1]) and h5[b] > h5[b - 1]:
            return b, max(h5[b - 1], o5[b]), np.nanmin(l5[:b + 1])
        dipped |= l5[b] <= support
    return None


def pre_open_masks(A, w, pick):
    """The chosen setup reduced to what is known before its 5-minute trigger (previous days and today's open);
    the dip, the break and the close are left to the trigger itself, so intraday entries never see the day's end."""
    o, pc, ph, pl = A['open'], prev(A['close']), prev(A['high']), prev(A['low'])
    e9p, e21p, adrp = prev(A['e9']), prev(A['e21']), prev(A['adr'])
    with np.errstate(invalid='ignore', divide='ignore'):
        near = prev(np.abs(A['close'] / A['e9'] - 1) <= .03)
        up = e9p > e21p
        gap = o >= pc * (1 + np.fmax(.05, adrp / 100))
        tight = prev(A['tight'])
        upper_open = (o >= pl + .5 * (ph - pl)) & (o <= ph)
        strong = prev((A['close'] - A['low']) >= .5 * (A['high'] - A['low']))
    table = {'E1': {'E2': w}, 'E2': {'E2': w & tight}, 'E3': {'E3': w & gap}, 'E4': {'E4': w & up},
             'E5': {'E2': w & tight, 'E3': w & gap, 'E4': w & up},
             'E6': {'E2': w & near}, 'E7': {'E2': w & tight & near, 'E3': w & gap & near, 'E4': w & up & near},
             'E10': {'E2': w & near, 'E4': w & up & near}, 'E11': {'E11': w & (o > pc * 1.01)},
             'E12': {'E2': w & upper_open}, 'E15': {'E2': w & near & strong}}
    if pick not in table:
        raise SystemExit(f'{pick}: per-day rankings need the day-t set; no pre-open version for 5-minute entries')
    return table[pick]


def entries_intraday(A, sig, P, b_start=0, day_ok=None):
    """N3 on the R8 sample: first 5-minute trigger, stop at the low of day so far; a later break of that low the
    same day exits at the stop.  Prices are mapped onto the daily panel through the day's 5-minute close.
    `sig` must hold pre-open masks (pre_open_masks), never conditions on the day's own high, low or close."""
    o5, h5, l5, c5 = P['arr'][:4]
    col = {str(x): j for j, x in enumerate(A['codes'])}
    di = {str(x): i for i, x in enumerate(P['days'])}
    cap = stop_cap(A)
    out = [[] for _ in range(len(A['days']))]
    ph, e9p = prev(A['high']), prev(A['e9'])
    for s, sym in enumerate(P['syms']):
        j = col.get('US.' + str(sym))
        if j is None:
            continue
        for d in np.flatnonzero(np.any([m[:, j] for m in sig.values()], axis=0)):
            if day_ok is not None and not day_ok[d]:
                continue
            dd = di.get(str(A['days'][d]))
            if dd is None:
                continue
            day_c = c5[s, dd][np.isfinite(c5[s, dd])]
            if not len(day_c):
                continue
            k = A['close'][d, j] / day_c[-1]
            best = None
            for kind, m in sig.items():
                if m[d, j]:
                    e = first_trigger(o5[s, dd], h5[s, dd], l5[s, dd], kind, ph[d, j] / k, e9p[d, j] / k,
                                      b_start)
                    if e and (best is None or e[0] < best[0]):
                        best = e
            if best is None:
                continue
            b, fill, lod = best
            if not (0 < (fill - lod) / fill <= cap[d, j]):
                continue
            later = l5[s, dd, b + 1:]
            hit = bool(np.any(later[np.isfinite(later)] <= lod))
            out[d].append((-A['to20'][d - 1, j], j, 1, fill * k, lod * k, 'n3', lod * k if hit else None))
    return out


def run_system(A, entries, seg, pool, placebo=100):
    px = dict(open=A['open'], high=A['high'], low=A['low'], close=A['close'], dates=A['days'], codes=A['codes'])
    ema = {'e9': A['e9']}
    curve, dates, tr = Y.simulate(px, ema, RULES, entries, *seg)
    st = Y.stats(curve, dates, tr)
    r = np.array([t['r'] for t in tr]) if tr else np.zeros(1)
    boots = np.random.default_rng(0).choice(r, (2000, len(r))).mean(axis=1)
    st['ci_r'] = [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))]
    if placebo:
        st['placebo'] = Y.placebo_rank(px, ema, RULES, entries, *seg, pool, draws=placebo)
    return st


def entry_round(build, file, tag, full_market=True):
    """R24-style loop on the R8 random sample: build(A, w, sig, P, r8) -> {name: entries}."""
    from . import intraday as I5
    A = us_arrays()
    w, sig = signal_inputs(A)
    P = I5.prepare_r8('new')
    r8 = np.isin(np.array([str(x) for x in A['codes']]), ['US.' + str(s) for s in P['syms']])
    cands = build(A, w, sig, P, r8)
    del P
    pool = w & r8[None, :]
    segs = {'select': ('2024-01-02', '2024-12-31'), 'validate': ('2025-01-02', '2026-10-16')}
    out = {'select': {}, 'validate': {}, 'full_market': {}}
    for k, e in cands.items():
        out['select'][k] = run_system(A, e, segs['select'], pool)
        print(tag, 'select', k, {a: b for a, b in out['select'][k].items() if a != 'by_year'}, flush=True)
    best = max(cands, key=lambda k: out['select'][k]['total'] - out['select'][k]['placebo']['median'])
    v = out['validate'][best] = run_system(A, cands[best], segs['validate'], pool)
    print(tag, 'validate', best, {a: b for a, b in v.items() if a != 'by_year'}, flush=True)
    out['chosen'] = best
    out['passed'] = bool(v['total'] > v['placebo']['p90'] and v['ci_r'][0] > 0)
    if full_market:
        for k, fn in (('N1', entries_close), ('N2', entries_next_open)):
            out['full_market'][k] = run_system(A, fn(A, sig), ('2024-01-02', '2026-10-16'), w)
            print(tag, 'full market', k, {a: b for a, b in out['full_market'][k].items() if a != 'by_year'},
                  flush=True)
    print(tag, 'chosen', best, 'passed', out['passed'])
    (I.OUT / file).write_text(json.dumps(out, indent=1))


def r24():
    def build(A, w, sig, P, r8):
        pre = pre_open_masks(A, w, setup_choice())
        return {'N1': entries_close(A, sig, r8), 'N2': entries_next_open(A, sig, r8),
                'N3': entries_intraday(A, pre, P)}
    entry_round(build, 'r24_entry.json', 'R24')


def r24b():
    def build(A, w, sig, P, r8):
        pre = pre_open_masks(A, w, setup_choice())
        up21 = ew_index_up(A, stage_inputs(A, 21)['pool'], 21)
        return {'N4': entries_intraday(A, pre, P, b_start=6), 'N5': entries_intraday(A, pre, P, b_start=12),
                'N6': entries_intraday(A, pre, P, b_start=6, day_ok=up21)}
    entry_round(build, 'r24b_entry.json', 'R24b', full_market=False)


EXITS = {'X0': {}, 'X1': dict(trims=()), 'X2': dict(trail='e21'), 'X3': dict(stop_ema_buffer=.01),
         'X4': dict(nft_days=1)}
SIZING = {'S0': {}, 'S1': dict(max_gross=2.8), 'S2': dict(feedback=10, risk_low=.0025)}
SEGS = {'select': ('2024-01-02', '2024-12-31'), 'validate': ('2025-01-02', '2026-10-16')}


def system_entries(A, sig):
    """Full-market long entries with the R24 choice (N3 exists only on the 5-minute sample, so N1 stands in)."""
    return entries_next_open(A, sig) if chosen('r24_entry.json', 'N1') == 'N2' else entries_close(A, sig)


def run_rules(A, entries, seg, pool, rules, placebo=100):
    px = dict(open=A['open'], high=A['high'], low=A['low'], close=A['close'], dates=A['days'], codes=A['codes'])
    if 'w9' in (rules.trail, rules.trail_after_trim) and 'w9' not in A:
        A['w9'] = weekly_ema(A['close'], A['days'], 9)
    names = (rules.exit_signal, rules.trim_signal, rules.risk_scale, rules.trail_alt_days)
    for k in names:
        if k and (k not in A or k.startswith('idx_')):            # index scales depend on the pool
            A[k] = named_signal(A, pool, k)
    ema = {k: A[k] for k in ('e9', 'e21', 'e50', 'w9') + names if k and k in A}
    curve, dates, tr = Y.simulate(px, ema, rules, entries, *seg)
    st = Y.stats(curve, dates, tr)
    r = np.array([t['r'] for t in tr]) if tr else np.zeros(1)
    boots = np.random.default_rng(0).choice(r, (2000, len(r))).mean(axis=1)
    st['ci_r'] = [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))]
    if placebo:
        st['placebo'] = Y.placebo_rank(px, ema, rules, entries, *seg, pool, draws=placebo)
    return st, tr


def pick_and_validate(A, cands, pool, file, tag):
    """Shared R25/R26/R27 loop: cands = {name: (entries, rules)}; choose on 2024 by real - placebo median."""
    out = {'select': {}, 'validate': {}}
    for k, (e, rules) in cands.items():
        out['select'][k] = run_rules(A, e, SEGS['select'], pool, rules)[0]
        print(tag, 'select', k, {a: b for a, b in out['select'][k].items() if a != 'by_year'}, flush=True)
    best = max(cands, key=lambda k: out['select'][k]['total'] - out['select'][k]['placebo']['median'])
    v = run_rules(A, cands[best][0], SEGS['validate'], pool, cands[best][1])[0]
    out['validate'][best] = v
    print(tag, 'validate', best, {a: b for a, b in v.items() if a != 'by_year'}, flush=True)
    out['chosen'] = best
    out['passed'] = bool(v['total'] > v['placebo']['p90'] and v['ci_r'][0] > 0)
    print(tag, 'chosen', best, 'passed', out['passed'])
    (I.OUT / file).write_text(json.dumps(out, indent=1))
    return out


def chosen_rules():
    rules = replace(RULES, **EXITS[chosen('r25_exits.json', 'X0')])
    return replace(rules, **SIZING.get(chosen('r26_sizing.json', 'S0'), {}))


def ew_index_up(A, pool, n):
    """Equal-weight index of pool names, and whether its previous close is above its EMA(n)."""
    c = A['close']
    with np.errstate(invalid='ignore', divide='ignore'):
        r = np.where(pool & np.isfinite(luk.lag(c)), c / luk.lag(c) - 1, np.nan)
    idx = np.cumprod(1 + np.nan_to_num(np.nanmean(r, axis=1)))[:, None]
    return prev((idx > luk.ema(idx, n))[:, 0][:, None])[:, 0]


def benchmark_close(A, ticker):
    """Actual US benchmark closes aligned by date; the research input must cover every evaluation session."""
    key = '_benchmark_' + ticker
    if key not in A:
        path = luk.ROOT / 'data' / 'martin-luk-benchmarks-v1' / f'US.{ticker}.csv'
        with path.open() as fh:
            by_day = {row['time_key'][:10]: float(row['close']) for row in csv.DictReader(fh)}
        close = np.array([by_day.get(str(d), np.nan) for d in A['days']])[:,None]
        missing = (A['days'] >= FULL[0]) & ~np.isfinite(close[:,0])
        if missing.any():
            raise ValueError(f'{ticker} missing benchmark days: {A["days"][missing][:5]}')
        A[key] = close
    return A[key]


def filter_days(entries, ok_day):
    return [e if ok_day[d] else [] for d, e in enumerate(entries)]


def r25():
    A = us_arrays()
    w, sig = signal_inputs(A)
    e = system_entries(A, sig)
    cands = {k: (e, replace(RULES, **x)) for k, x in EXITS.items()}
    pick_and_validate(A, cands, w, 'r25_exits.json', 'R25')


def r26():
    A = us_arrays()
    w, sig = signal_inputs(A)
    e = system_entries(A, sig)
    base = replace(RULES, **EXITS[chosen('r25_exits.json', 'X0')])
    st = stage_inputs(A, 21)
    cands = {k: (e, replace(base, **x)) for k, x in SIZING.items()}
    cands['S3'] = (filter_days(e, ew_index_up(A, st['pool'], 21)), base)
    cands['S4'] = (filter_days(e, breadth_ok(A, w)), base)
    pick_and_validate(A, cands, w, 'r26_sizing.json', 'R26')


def short_signals(A, pool):
    c, h, l = A['close'], A['high'], A['low']
    e9p, e21p, e50p = prev(A['e9']), prev(A['e21']), prev(A['e50'])
    wk_down = prev(weekly_ema(c, A['days'], 9) < weekly_ema(c, A['days'], 21))
    with np.errstate(invalid='ignore'):
        above50 = c > A['e50']
        fresh = S._past_any(above50, 30) & prev(~above50)
        z1 = fresh & (e9p < e21p) & (h >= .99 * e50p) & (c < e50p)
        z2 = (e9p < e21p) & (e21p < e50p) & (h >= e21p) & (c < e9p)
        z5 = (e9p < e21p) & (e21p < e50p) & prev(A['tight']) & (c < prev(l))
    base = pool & wk_down
    return {'Z1': base & z1, 'Z2': base & z2, 'Z5': base & z5}


def entries_short(A, m):
    c, h = A['close'], A['high']
    cap = stop_cap(A)
    out = [[] for _ in range(len(c))]
    for d, j in zip(*np.nonzero(m)):
        risk = (h[d, j] - c[d, j]) / c[d, j]
        if 0 < risk <= cap[d, j]:
            out[d].append((-A['to20'][d - 1, j], j, -1, c[d, j], h[d, j], 'short'))
    return out


def r27():
    A = us_arrays()
    pool = stage_inputs(A, 21)['pool']
    down50 = ~ew_index_up(A, pool, 50)
    z = short_signals(A, pool)
    rules = replace(chosen_rules(), trims=(3,), trail='e9', max_days=3)
    cands = {'Z1': (entries_short(A, z['Z1']), rules), 'Z2': (entries_short(A, z['Z2']), rules),
             'Z3': (filter_days(entries_short(A, z['Z1']), down50), rules),
             'Z4': (filter_days(entries_short(A, z['Z2']), down50), rules),
             'Z5': (filter_days(entries_short(A, z['Z5']), down50), rules)}
    out = pick_and_validate(A, cands, pool, 'r27_shorts.json', 'R27')
    trades = L.load(LEDGER)
    shorts = [t for t in trades if t.side == 'short' and t.dated]
    loc, _ = F.locate(shorts, A['days'], A['codes'], has=A['has'])
    best = {'Z3': 'Z1', 'Z4': 'Z2'}.get(out['chosen'], out['chosen'])
    out['fidelity'] = {k: {a: b for a, b in F.recall(m, loc, A['has']).items()} for k, m in z.items()}
    out['fidelity_chosen_signal'] = best
    print('R27 fidelity', {k: (v['hits'], v['n']) for k, v in out['fidelity'].items()})
    (I.OUT / 'r27_shorts.json').write_text(json.dumps(out, indent=1))


def breadth_ok(A, w):
    """R26 S4: yesterday's count of watchlist names in a daily EMA stack is at least its 50-day median."""
    lead = (w & prev(A['stack'])).sum(1).astype(float)
    med50 = np.array([np.median(lead[max(0, t - 50):t]) if t else np.nan for t in range(len(lead))])
    return prev((lead >= med50)[:, None])[:, 0]


def leader_shorts(A, pool):
    """R27b: shorts on former leaders right after their first break below the 21 EMA."""
    o, h, c = A['open'], A['high'], A['close']
    e9, e9p, e21p = A['e9'], prev(A['e9']), prev(A['e21'])
    k9 = strength_lists(A, pool)['K9']
    with np.errstate(invalid='ignore'):
        was_leader = S._past_any(k9, 40)
        cross = prev(A['close'] > A['e21']) & (A['close'] < A['e21'])        # close moves from above to below EMA21
        fresh = S._past_any(cross, 5)
        base = pool & was_leader & fresh
        z6 = base & (h >= e9p) & (c < e9p) & (e9 < e9p)
        z8 = base & (o > prev(c)) & (h >= e21p) & (c < e9p)
    return {'Z6': z6, 'Z8': z8, 'Z9': z6 | z8}


def short_entries_for(A, pool, w, name):
    """Entries for any R27 / R27b short candidate."""
    if name in ('Z1', 'Z2', 'Z3', 'Z4', 'Z5'):
        z = short_signals(A, pool)
        e = entries_short(A, z[{'Z3': 'Z1', 'Z4': 'Z2'}.get(name, name)])
        return filter_days(e, ~ew_index_up(A, pool, 50)) if name in ('Z3', 'Z4', 'Z5') else e
    z = leader_shorts(A, pool)
    if name == 'Z7':
        return filter_days(entries_short(A, z['Z6']), ~ew_index_up(A, pool, 21))
    if name == 'Z10':
        return filter_days(entries_short(A, z['Z9']), ~breadth_ok(A, w))
    return entries_short(A, z[name])


def short_choice():
    for name in ('r27b_shorts.json', 'r27_shorts.json'):
        if (I.OUT / name).exists():
            res = json.loads((I.OUT / name).read_text())
            if res.get('passed'):
                return res['chosen']
    return None


def r27b():
    A = us_arrays()
    pool = stage_inputs(A, 21)['pool']
    w = stage_inputs(A, 23)['w']
    rules = replace(chosen_rules(), trims=(3,), trail='e9', max_days=3)
    cands = {k: (short_entries_for(A, pool, w, k), rules) for k in ('Z6', 'Z7', 'Z8', 'Z9', 'Z10')}
    out = pick_and_validate(A, cands, pool, 'r27b_shorts.json', 'R27b')
    trades = L.load(LEDGER)
    shorts = [t for t in trades if t.side == 'short' and t.dated]
    loc, _ = F.locate(shorts, A['days'], A['codes'], has=A['has'])
    z = leader_shorts(A, pool)
    out['fidelity'] = {k: {a: b for a, b in F.recall(m, loc, A['has']).items()} for k, m in z.items()}
    print('R27b fidelity', {k: (v['hits'], v['n']) for k, v in out['fidelity'].items()})
    (I.OUT / 'r27b_shorts.json').write_text(json.dumps(out, indent=1))


FLOOR = {'hk': 1.0, 'cn': 3.0}
COSTS = {'us': (.0005, .0005), 'hk': (.0016, .0016), 'cn': (.00076, .00126)}


def pool_for(A, name=None):
    """US: the R20 pool (or `name`); HK / CN: top 30% by 20-day turnover in that market, price floor, the same
    ADR floor."""
    spec = POOLS[name or chosen('r20_pool.json', 'U0')]
    if A['market'] == 'us':
        return pool_mask(A, *spec)
    with np.errstate(invalid='ignore'):
        cut = np.nanquantile(np.where(A['rank_pool'], A['to20'], np.nan), .7, axis=1)
        m = (A['to20'] >= cut[:, None]) & (A['raw'] >= FLOOR[A['market']]) & (A['adr'] >= spec[2])
    return prev(m)


def system_signals(A, cfg=None, trace=None):
    cfg = cfg or {}
    pool = pool_for(A, cfg.get('pool'))
    k = pool & strength_lists(A, pool)[cfg.get('strength') or strength_choice()]
    watch_type = watch_lists(A)[cfg.get('watch') or watch_choice()]
    w = k & watch_type
    if trace is not None:
        trace.update(strength=k, watch_type=watch_type)
    fams = setup_families(A, w)
    names = (cfg.get('setup') or setup_choice()).split('+')                # R46: 'E11+E2' is a union
    return pool, w, {(f'{n}:{x}' if len(names) > 1 else x): w & m for n in names for x, m in fams[n].items()}


def limit_up(A):
    """A-share closes at the daily limit (main board 9.5%, ChiNext / STAR 19.5%) cannot be bought."""
    codes = np.array([str(c) for c in A['codes']])
    wide = np.char.startswith(codes, 'SZ.300') | np.char.startswith(codes, 'SH.688')
    with np.errstate(invalid='ignore', divide='ignore'):
        r = A['raw'] / prev(A['raw']) - 1
    return r >= np.where(wide, .195, .095)[None, :]


def ew_hold(A, pool, seg):
    c = A['close']
    with np.errstate(invalid='ignore', divide='ignore'):
        r = np.where(pool & np.isfinite(luk.lag(c)), c / luk.lag(c) - 1, np.nan)
    m = (A['days'] >= seg[0]) & (A['days'] <= seg[1])
    return float(np.prod(1 + np.nan_to_num(np.nanmean(r[m], axis=1))) - 1)


def r28():
    out = {}
    trades = L.load(LEDGER)
    _, val = L.split(trades, CUTOFF)
    full = ('2024-01-02', '2026-10-16')
    shorts_on = short_choice()
    sizing = chosen('r26_sizing.json', 'S0')
    for market in ('us', 'hk', 'cn'):
        A = market_arrays(market)
        pool, w, sig = system_signals(A)
        if market == 'cn':
            lu = limit_up(A)
            sig = {k: m & ~lu for k, m in sig.items()}
        entries = system_entries(A, sig)
        if sizing == 'S3':
            entries = filter_days(entries, ew_index_up(A, pool, 21))
        elif sizing == 'S4':
            entries = filter_days(entries, breadth_ok(A, w))
        rules = replace(chosen_rules(), buy_cost=COSTS[market][0], sell_cost=COSTS[market][1],
                        short_trims=(3,), short_max_days=3)
        res = {'sizing': sizing}
        if market == 'us' and shorts_on:
            se = short_entries_for(A, pool, w, shorts_on)
            entries = [a + b for a, b in zip(entries, se)]
            res['shorts'] = shorts_on
        for name, seg in (('full', full), ('2024', SEGS['select']), ('2025-26', SEGS['validate'])):
            st, tr = run_rules(A, entries, seg, w, rules, placebo=100 if name == 'full' else 0)
            st['ew_hold_pool'] = ew_hold(A, pool, seg)
            st['stop_width_median'] = float(np.median([t['risk_pct'] for t in tr])) if tr else None
            res[name] = st
            print('R28', market, name, {a: b for a, b in st.items() if a != 'by_year'}, flush=True)
        if market == 'us':
            loc = located_longs(A, val)
            dated = [x for x in loc if x[0].dated]
            fired = np.zeros_like(A['has'])                      # the signal fires that day (entry may follow)
            for m in sig.values():
                fired |= m
            res['fidelity_validate'] = {
                'watchlist_all_longs': {a: b for a, b in F.recall(w, loc, A['has']).items() if a != 'per_trade'},
                'signal_dated_longs': {a: b for a, b in F.recall(fired, dated, A['has']).items()},
                'signals_per_day': F.width(fired, A['days'], *full)}
            print('R28 fidelity', {k: (v.get('hits'), v.get('n')) for k, v in res['fidelity_validate'].items()})
        out[market] = res
        del A
    (I.OUT / 'r28_system.json').write_text(json.dumps(out, indent=1))


def close_outcomes(A, horizon=10, up=.20, down=.07, window=20):
    """From day t's close: return `horizon` closes later, and whether +up comes before -down within `window` days."""
    c, h, l = A['close'], A['high'], A['low']
    T = len(c)
    fwd = np.full_like(c, np.nan)
    with np.errstate(invalid='ignore', divide='ignore'):
        fwd[:-horizon] = c[horizon:] / c[:-horizon] - 1
    win = np.full_like(c, np.nan)
    for t in range(T - window):
        decided = np.zeros(c.shape[1], bool)
        res = np.zeros(c.shape[1])
        with np.errstate(invalid='ignore', divide='ignore'):
            for k in range(1, window + 1):
                dn = (l[t + k] / c[t] - 1 <= -down) & ~decided
                decided |= dn
                upk = (h[t + k] / c[t] - 1 >= up) & ~decided
                res[upk] = 1
                decided |= upk
        win[t] = np.where(np.isfinite(c[t]), res, np.nan)
    return fwd, win


def r29():
    A = us_arrays()
    trades = L.load(LEDGER)
    sel, _ = L.split(trades, CUTOFF)
    longs24 = [x for x in located_longs(A, sel) if x[0].window_lo < '2025-01-01']
    days = A['days']
    st = stage_inputs(A, 23)
    pool, k, w = st['pool'], st['k'], st['w']
    fams = setup_families(A, w)
    e11 = union(fams['E11'])
    c, l = A['close'], A['low']
    with np.errstate(invalid='ignore', divide='ignore'):
        feasible = (c > l) & ((c - l) / c <= stop_cap(A))
    breadth = breadth_ok(A, w)[:, None] & np.ones_like(w)
    stages = [('U4 pool', pool), ('K9 strength', k), ('V8 watchlist', w), ('E11 setup', e11),
              ('S4 breadth', breadth), ('stop feasible', feasible)]
    out = {'funnel_2024_longs': F.funnel(stages, longs24, A['has'])}
    for r in out['funnel_2024_longs']:
        print('R29 funnel', r['stage'], f"{r['hits']}/{r['n']}", 'lost', r['lost'], flush=True)
    # per-trade: which daily setups fire on his 2024 entry windows
    per = {}
    for t, j, a, b in longs24:
        per[t.id] = dict(ticker=t.ticker, setup=t.setup, in_w=bool(w[a:b + 1, j].any()),
                         fires=[n for n in ('E1', 'E2', 'E3', 'E4', 'E11', 'E12')
                                if union(fams[n])[a:b + 1, j].any()])
    out['his_2024_trades'] = per
    for i, v in per.items():
        print('R29 his', i, v, flush=True)
    # setup families inside the watchlist, 2024 by quarter
    fwd, win = close_outcomes(A)
    q = np.array([str(d)[:4] + 'Q' + str((int(str(d)[5:7]) - 1) // 3 + 1) for d in days]).astype(str)
    rows = (days >= '2024-01-02') & (days <= '2024-12-31')
    fam_out = {}
    for n in ('E1', 'E2', 'E3', 'E4', 'E11', 'E12', 'any'):
        m = w if n == 'any' else w & union(fams[n])
        res = {}
        for qq in sorted(str(x) for x in set(q[rows])):
            r_ = rows & (q == qq)
            mm = m & r_[:, None]
            f_, w_ = fwd[mm], win[mm]
            res[qq] = dict(n=int(np.isfinite(f_).sum()), fwd10=float(np.nanmean(f_)) if np.isfinite(f_).any() else None,
                           hit20=float(np.nanmean(w_)) if np.isfinite(w_).any() else None)
        fam_out[n] = res
        print('R29 family', n, {a: (b['n'], round(100 * b['fwd10'], 2) if b['fwd10'] is not None else None,
                                     round(100 * b['hit20'], 1) if b['hit20'] is not None else None)
                                 for a, b in res.items()}, flush=True)
    out['families_2024'] = fam_out
    # the combined system's 2024 trades
    pool_, w_, sig = system_signals(A)
    entries = filter_days(system_entries(A, sig), breadth_ok(A, w_))
    px = dict(open=A['open'], high=A['high'], low=A['low'], close=A['close'], dates=days, codes=A['codes'])
    curve, dd, tr = Y.simulate(px, {'e9': A['e9'], 'e21': A['e21']}, chosen_rules(), entries, *SEGS['select'])
    by_m = {}
    for t in tr:
        mth = t['entry'][:7]
        g = by_m.setdefault(mth, dict(n=0, pnl=0.0, wins=0))
        g['n'] += 1
        g['pnl'] += float(t['pnl'])
        g['wins'] += int(t['ret'] > 0)
    by_why = {}
    for t in tr:
        g = by_why.setdefault(t['why'], dict(n=0, pnl=0.0))
        g['n'] += 1
        g['pnl'] += float(t['pnl'])
    r = np.array([t['r'] for t in tr])
    rp = np.array([t['risk_pct'] for t in tr])
    out['system_2024'] = dict(total=float(curve[-1] - 1), by_month=by_m, by_exit=by_why,
                              r_quantiles=[float(x) for x in np.percentile(r, [10, 25, 50, 75, 90, 99])],
                              stop_quantiles=[float(x) for x in np.percentile(rp, [10, 25, 50, 75, 90])],
                              top_winners=sorted(((t['code'], t['entry'], round(t['r'], 1)) for t in tr),
                                                 key=lambda x: -x[2])[:10])
    print('R29 system 2024', {a: b for a, b in out['system_2024'].items()}, flush=True)
    (I.OUT / 'r29_diagnosis.json').write_text(json.dumps(out, indent=1))


def prior_low(l, n):
    """Lowest low of the previous n days (today excluded), NaN-aware."""
    out = np.full_like(l, np.nan)
    for k in range(1, n + 1):
        out = np.fmin(out, luk.lag(l, k))
    return out


def prior_high(h, n):
    """Highest high of the previous n days (today excluded), NaN-aware, one n-day pass at a time."""
    out = np.full_like(h, np.nan)
    for k in range(1, n + 1):
        out = np.fmax(out, luk.lag(h, k))
    return out


def climax(A, gain):
    """His sell-all-into-strength exit (lS9z@1:17:10): after a run of at least `gain` in 10 days, that day's dollar
    volume is above every day of the prior 52 weeks; the long is sold at that close."""
    c = A['close']
    with np.errstate(invalid='ignore', divide='ignore'):
        return (A['turnover'] > prior_high(A['turnover'], 252)) & (c / luk.lag(c, 10) - 1 >= gain)


def index_risk_scale(A, pool, pb=1.6, ext=1.0, ext_at=.05, band=.01, which='both', below=None,
                     index_close=None):
    """R59: risk multiplier from the pool's equal-weight index as of the previous close: x `pb` when it sits within
    1% of its EMA9 or EMA21 while above its EMA50 (his "attack when the index pulls back to the 9/21"), x `ext`
    when it is more than `ext_at` above its EMA21 (overextended); 1 otherwise.  R62: `band` around the EMA,
    which='e21' counts only EMA21 pullbacks, and `below` (when set) is the multiplier below the EMA50."""
    with np.errstate(invalid='ignore', divide='ignore'):
        if index_close is None:
            c = A['close']
            r = np.where(pool & np.isfinite(luk.lag(c)), c / luk.lag(c) - 1, np.nan)
            idx = np.cumprod(1 + np.nan_to_num(np.nanmean(r, axis=1)))[:, None]
        else:
            idx = index_close
        e9, e21, e50 = luk.ema(idx, 9), luk.ema(idx, 21), luk.ema(idx, 50)
        near = np.abs(idx / e21 - 1) <= band
        if which == 'both':
            near = near | (np.abs(idx / e9 - 1) <= band)
        out = np.where((idx > e50) & near, pb, 1.0)
        out = np.where(idx > e21 * (1 + ext_at), ext, out)
        if below is not None:
            out = np.where(idx <= e50, below, out)
    return prev(out)[:, 0]


INDEX_SCALES = {'idx_pb16': dict(pb=1.6), 'idx_ext05': dict(pb=1.0, ext=.5), 'idx_both': dict(pb=1.6, ext=.5),
                'idx_pb20': dict(pb=2.0), 'idx_ext05_3': dict(pb=1.0, ext=.5, ext_at=.03),
                'idx_pb16_b2': dict(pb=1.6, band=.02), 'idx_pb16_e21': dict(pb=1.6, which='e21'),
                'idx_pb16_lo05': dict(pb=1.6, below=.5), 'idx_pb16_lo025': dict(pb=1.6, below=.25),
                'idx_pb13': dict(pb=1.3)}


def named_signal(A, pool, name):
    if name == 'qqq_pb16':
        idx = benchmark_close(A, 'QQQ') if A['market'] == 'us' else None
        return index_risk_scale(A, pool, index_close=idx)
    """Day arrays the engine reads by name: 'climax<gain%>', 'ext<k>' (close at least k x ADR above the EMA9,
    his "extended"), and the index risk scales."""
    if name.startswith('climax'):
        return climax(A, int(name[len('climax'):]) / 100)
    if name.startswith('ext'):
        with np.errstate(invalid='ignore'):
            return A['close'] >= A['e9'] * (1 + int(name[3:]) * A['adr'] / 100)
    if name.startswith('idx_run'):                    # R74: index above its EMA50 on each of the last n closes
        up = ew_index_up(A, pool, 50).astype(float)
        n = int(name[len('idx_run'):])
        return luk.rolling_mean(up[:, None], n)[:, 0] >= 1
    if name in INDEX_SCALES:
        return index_risk_scale(A, pool, **INDEX_SCALES[name])
    raise ValueError(name)


def ep_signal(A, pool, gap_min=.05, gap_adr=1.0, vol_mult=2.0, hold_open=True, near_high=0.0):
    """His pre-market gapper scan, without the leader list: gap >= max(gap_min, gap_adr x ADR), vol_mult x volume,
    (hold_open) a close at or above the open, and (near_high) an open within that fraction of the 126-day high."""
    o, c = A['open'], A['close']
    with np.errstate(invalid='ignore', divide='ignore'):
        gap = o >= prev(c) * (1 + np.fmax(gap_min, gap_adr * prev(A['adr']) / 100))
        vol = A['turnover'] >= vol_mult * prev(A['to20'])
        held = (c >= o) if hold_open else True
        near = (o >= (1 - near_high) * prior_high(A['high'], 126)) if near_high else True
        return pool & gap & vol & held & near


def entries_close_stop(A, mask, mode, kind='n1', cap_max=.05, stop_min=0.0,
                       stop_floor_adr=0.0, stop_reference='day_low'):
    """Close entries with the stop at the day's low; when that is wider than cap = min(5%, 0.5 ADR):
    'skip' drops the trade (R24 N1), 'cap' moves the stop up to the cap, 'half' to half the cap (R30).
    R78 optionally uses the prior low or an ADR-based stop floor; both use only prior-day ADR."""
    c, l = A['close'], A['low']
    if stop_reference not in ('day_low', 'prior_low'):
        raise ValueError(stop_reference)
    if stop_reference == 'prior_low':
        l = prev(l)
    cap = stop_cap(A, cap_max)
    out = [[] for _ in range(len(c))]
    for d, j in zip(*np.nonzero(mask)):
        if d == 0:
            continue
        if not (np.isfinite(c[d, j]) and np.isfinite(l[d, j]) and c[d, j] > 0):
            continue
        if stop_reference == 'prior_low' and l[d, j] >= c[d, j]:
            continue
        if mode == 'skip':
            if not (0 < (c[d, j] - l[d, j]) / c[d, j] <= cap[d, j]):
                continue
            stop = l[d, j]
        else:
            width = cap[d, j] if mode == 'cap' else cap[d, j] / 2
            stop = max(l[d, j], c[d, j] * (1 - width))
        if stop_min and (c[d, j] - stop) / c[d, j] < stop_min:
            stop = c[d, j] * (1 - stop_min)
        if stop_floor_adr:
            floor = min(cap_max, stop_floor_adr * A['adr'][d - 1, j] / 100)
            stop = min(stop, c[d, j] * (1 - floor))
        if stop < c[d, j]:
            out[d].append((-A['to20'][d - 1, j], j, 1, c[d, j], stop, kind))
    return out


def add_fidelity(A, file, masks, tag):
    """Signal-day hit rate of his dated longs for each candidate's signal mask (selection and validation)."""
    trades = L.load(LEDGER)
    sel, val = L.split(trades, CUTOFF)
    ls = [x for x in located_longs(A, sel) if x[0].dated]
    lv = [x for x in located_longs(A, val) if x[0].dated]
    path = I.OUT / file
    out = json.loads(path.read_text())
    out['fidelity'] = {}
    for k, m in masks.items():
        rs, rv = F.recall(m, ls, A['has']), F.recall(m, lv, A['has'])
        out['fidelity'][k] = dict(select=(rs['hits'], rs['n']), validate=(rv['hits'], rv['n']),
                                  width=F.width(m, A['days'], '2024-01-02', '2026-03-31'))
        print(tag, 'fidelity', k, out['fidelity'][k], flush=True)
    path.write_text(json.dumps(out, indent=1))


def r30():
    A = us_arrays()
    st = stage_inputs(A, 23)
    pool, w = st['pool'], st['w']
    _, sig = signal_inputs(A)
    base = union(sig)
    ep = ep_signal(A, pool)
    ok = breadth_ok(A, w)
    masks = {'C0': base, 'C1': base, 'C2': base | ep, 'C3': ep, 'C4': base | ep}
    modes = {'C0': 'skip', 'C1': 'cap', 'C2': 'cap', 'C3': 'cap', 'C4': 'half'}
    rules = chosen_rules()
    cands = {k: (filter_days(entries_close_stop(A, masks[k], modes[k]), ok), rules) for k in masks}
    pick_and_validate(A, cands, pool, 'r30_entry_days.json', 'R30')
    add_fidelity(A, 'r30_entry_days.json', masks, 'R30')


EXITS['X5'] = dict(trims=(), trail='e21')
EXITS.update({'X6': dict(trims=(5, 10), trail='e21'), 'X7': dict(trail='e50'), 'X8': dict(trail='w9'),
              'X9': dict(trims=(10,), trim_frac=.30, trail='e21'), 'X10': dict(trail='e21', max_days=30),
              'X11': dict(trims=(10,), trim_frac=.30, trail='e50')})
EXITS.update({'X12': dict(EXITS['X9'], exit_signal='climax30'), 'X13': dict(EXITS['X9'], exit_signal='climax50'),
              'X14': dict(trims=(8,), trim_frac=.30, trail='e21'), 'X15': dict(trims=(10,), trim_frac=.50, trail='e21'),
              'X16': dict(trims=(10, 20), trim_frac=.30, trail='e21')})
EXITS.update({'X17': dict(EXITS['X9'], trail_after_trim='e9'), 'X18': dict(EXITS['X9'], breakeven_r=3.0),
              'X19': dict(EXITS['X9'], breakeven_r=5.0),
              'X20': dict(EXITS['X9'], trail_after_trim='e9', exit_signal='climax50'),
              'X21': dict(trims=(5,), trim_frac=.30, trail='e21', trail_after_trim='e9')})
EXITS.update({'X22': dict(EXITS['X9'], trim_signal='ext2', trim_signal_frac=.15),
              'X23': dict(EXITS['X9'], trim_signal='ext3', trim_signal_frac=.15),
              'X24': dict(trims=(), trail='e21', trim_signal='ext2', trim_signal_frac=.15),
              'X25': dict(EXITS['X9'], trim_signal='ext3', trim_signal_frac=.15, exit_signal='climax50'),
              'X26': dict(EXITS['X9'], trim_signal='ext2', trim_signal_frac=.30)})
BASE_CONFIG = dict(signals='C2', stop='cap', exits='X0', small_cap=False, gap_size=False, gross=2.0, risk=.005,
                   filter='S4', rank=None, rank_n=0)
CARRY = ['r31_exits_sizing.json', 'r32_exposure.json', 'r33_rotation.json', 'r34_base_path.json',
         'r35_minyear.json', 'r36_shorts.json', 'r37_exits.json', 'r38_priority.json', 'r39_risk.json',
         'r40_bpath.json', 'r41_exits.json']                   # carry rounds in order; each later round extends this list


def system_config():
    """The configuration carried forward by the latest finished carry round (BASE_CONFIG = R30's C2)."""
    cfg = dict(BASE_CONFIG)
    for name in CARRY:
        path = I.OUT / name
        if path.exists():
            cfg = json.loads(path.read_text())['chosen_config']
    return cfg


def market_ok(A, pool, w, spec):
    """Days that allow new longs: 'S4' (watchlist breadth), 'IDX<n>' (pool equal-weight index above its EMA n),
    joined by '+' (all) or '|' (any)."""
    def one(x):
        if x.startswith(('QQQ', 'IWM')):
            n = int(x[3:])
            if A['market'] != 'us':
                return ew_index_up(A, pool, n)
            idx = benchmark_close(A, x[:3])
            return prev(idx > luk.ema(idx, n))[:,0]
        return breadth_ok(A, w) if x == 'S4' else ew_index_up(A, pool, int(x[3:]))
    if '|' in spec:
        out = None
        for x in spec.split('|'):
            out = one(x) if out is None else out | one(x)
        return out
    out = None
    for x in spec.split('+'):
        out = one(x) if out is None else out & one(x)
    return out


def build_system(A, cfg, trace=None):
    """Entries, rules, signal mask and placebo pool for a configuration, in any market; `trace` (a dict) gets
    the entries after the stop rule ('raw'), the market filter ('filtered') and the daily cap ('capped')."""
    pool, w, sig = system_signals(A, cfg, trace)
    ep = ep_signal(A, pool, **cfg.get('ep_opts', {}))
    if cfg['signals'] == 'NONE':
        mask = np.zeros_like(w)
    elif cfg['signals'] in ('C0', 'C1', 'C2', 'C3'):
        base = union(sig)
        mask = {'C0': base, 'C1': base, 'C2': base | ep, 'C3': ep}[cfg['signals']]
    else:                                              # R33 families and rotation
        fam = families(A, pool, w)
        mask = {'T1': lambda: union(fam), 'T2': lambda: rotate(A, fam, 20),
                'T3': lambda: rotate(A, fam, 20, top_only=True), 'T4': lambda: rotate(A, fam, 40),
                'T5': lambda: fam['HS'] | fam['EP'] | fam['PB']}[cfg['signals']]()
    if trace is not None:
        trace.update(pool=pool, watch=w, ep=ep, main_signal=mask)
    if cfg.get('bpath'):
        bp = base_path(A, pool, cfg['bpath'], **cfg.get('bopts', {}))
        mask = mask | bp
        if trace is not None:
            trace['base_path'] = bp
    if cfg.get('wk_channel'):                          # R73: weekly breakouts anywhere in the pool
        wb = weekly_cached(A)
        for k in cfg['wk_channel'].split('+'):
            mask = mask | (pool & wb[k])
    if A['market'] == 'cn':
        mask = mask & ~limit_up(A)
    if cfg.get('rank'):
        mask = top_per_day(mask, prev(A[cfg['rank']]), cfg['rank_n'])
    entries = entries_close_stop(A, mask, cfg['stop'], cap_max=cfg.get('stop_cap_max', .05),
                                 stop_min=cfg.get('stop_min', 0.0), stop_floor_adr=cfg.get('stop_floor_adr', 0.0),
                                 stop_reference=cfg.get('stop_reference', 'day_low'))
    if cfg['small_cap'] or cfg['gap_size']:
        adrp, to20p = prev(A['adr']), prev(A['to20'])
        entries = [[e[:6] + (None, .5 * adrp[d, e[1]] / 100 if cfg['gap_size'] else None,
                             .20 if cfg['small_cap'] and to20p[d, e[1]] < 100e6 else None) for e in lst]
                   for d, lst in enumerate(entries)]
    if trace is not None:
        trace['raw'] = entries
    if cfg.get('liquidity_groups'):
        entries = liquidity_groups(A, entries)
    if cfg.get('trend_phase_groups'):
        if cfg.get('liquidity_groups'):
            raise ValueError('Combine phase and liquidity management explicitly before using both')
        entries = trend_phase_groups(A, entries)
    if cfg['filter'] and cfg['filter'] != 'NONE':
        entries = filter_days(entries, market_ok(A, pool, w, cfg['filter']))
    if cfg.get('priority') == 'theme':
        entries = theme_priority(A, entries)
    elif cfg.get('priority'):
        score = priority_score(A, cfg['priority'])
        entries = [[(-score[d, e[1]] if np.isfinite(score[d, e[1]]) else np.inf,) + e[1:] for e in lst]
                   for d, lst in enumerate(entries)]
    if trace is not None:
        trace['filtered'] = entries
    if cfg.get('max_new'):
        entries = [sorted(lst, key=lambda e: e[0])[:cfg['max_new']] for lst in entries]
    if trace is not None:
        trace['capped'] = entries
    if cfg.get('shorts') and A['market'] == 'us':
        z = short_masks(A, pool)[cfg['shorts']]
        se = entries_short_capped(A, z, cfg.get('short_size', 1.0))
        if cfg.get('short_gate'):
            se = filter_days(se, ~ew_index_up(A, pool, cfg['short_gate']))
        if cfg.get('short_max_new'):
            se = [sorted(lst, key=lambda e: e[0])[:cfg['short_max_new']] for lst in se]
        if cfg.get('short_last'):                        # R53: the day's longs are opened before any short
            entries = [[((0, e[0]),) + tuple(e[1:]) for e in a] + [((1, e[0]),) + tuple(e[1:]) for e in b]
                       for a, b in zip(entries, se)]
        else:
            entries = [a + b for a, b in zip(entries, se)]
    rules = replace(RULES, **EXITS[cfg['exits']], max_gross=cfg['gross'], risk=cfg['risk'],
                    feedback=10 if cfg.get('risk_high') else 0, risk_low=cfg['risk'],
                    risk_high=cfg.get('risk_high', 0.0), short_trims=(3,),
                    short_max_days=cfg.get('short_days', 3),
                    max_position=cfg.get('max_position', .30),
                    buy_cost=COSTS[A['market']][0], sell_cost=COSTS[A['market']][1])
    if cfg.get('rule_opts'):
        rules = replace(rules, **{k: tuple(v) if isinstance(v, list) else v for k, v in cfg['rule_opts'].items()})
    return entries, rules, mask, pool


def trend_phase_groups(A, entries):
    """Freeze early-trend management from completed history, never from the entry day's move."""
    c, e9, e21, e50 = (A[k] for k in ('close', 'e9', 'e21', 'e50'))
    strong = prev((c > e50) & (e9 > e21) & (e21 > e50)) & (prev(e50) > prev(prev(e50)))
    early = strong & S._past_any(c <= e50, 21)
    return [[e[:5] + ('early_trend',) + e[6:] if early[d, e[1]] else e for e in day]
            for d, day in enumerate(entries)]


def liquidity_groups(A, entries):
    """Freeze a position's management group using only the prior 20-day average turnover."""
    return [[e[:5] + ('thin' if d and A['to20'][d-1, e[1]] < 100e6 else 'premier',) + e[6:]
             for e in day] for d, day in enumerate(entries)]


def carry_round(cfgs, file, tag, ref):
    """R31+: choose on 2024 by total return among candidates above their placebo median whose selection-trade
    signal-day hits are at least the reference's; validate the choice once; report every candidate's years."""
    A = us_arrays()
    trades = L.load(LEDGER)
    sel, val = L.split(trades, CUTOFF)
    ls = [x for x in located_longs(A, sel) if x[0].dated]
    lv = [x for x in located_longs(A, val) if x[0].dated]
    out = {'configs': cfgs, 'select': {}, 'years': {}, 'fidelity': {}, 'validate': {}}
    built = {}
    for k, cfg in cfgs.items():
        entries, rules, mask, pool = build_system(A, cfg)
        built[k] = (entries, rules, pool)
        out['select'][k] = run_rules(A, entries, SEGS['select'], pool, rules)[0]
        out['years'][k] = run_rules(A, entries, ('2024-01-02', '2026-10-16'), pool, rules, placebo=0)[0]['by_year']
        rs, rv = F.recall(mask, ls, A['has']), F.recall(mask, lv, A['has'])
        out['fidelity'][k] = dict(select=[rs['hits'], rs['n']], validate=[rv['hits'], rv['n']])
        s = out['select'][k]
        print(tag, k, f"2024 {s['total']:+.3f} placebo median {s['placebo']['median']:+.3f} rank "
              f"{s['placebo']['rank']:.2f} trades {s['trades']} win {s['win']:.3f} "
              f"avg {s['avg_win']:+.3f}/{s['avg_loss']:+.3f} R {s['exp_r']:+.2f}",
              'years', {a: round(b, 3) for a, b in out['years'][k].items()}, 'fid', out['fidelity'][k], flush=True)
    need = out['fidelity'][ref]['select'][0]
    ok = [k for k in cfgs if k != ref and out['select'][k]['total'] > out['select'][k]['placebo']['median']
          and out['fidelity'][k]['select'][0] >= need]
    best = max(ok + [ref], key=lambda k: out['select'][k]['total'])           # never carry a worse system
    entries, rules, pool = built[best]
    v = out['validate'][best] = run_rules(A, entries, SEGS['validate'], pool, rules)[0]
    out['chosen'], out['chosen_config'] = best, cfgs[best]
    out['validated'] = bool(v['total'] > v['placebo']['p90'] and v['ci_r'][0] > 0)
    print(tag, 'validate', best, f"{v['total']:+.3f} placebo median {v['placebo']['median']:+.3f} p90 "
          f"{v['placebo']['p90']:+.3f} R {v['exp_r']:+.2f} {[round(x, 2) for x in v['ci_r']]}", flush=True)
    print(tag, 'chosen', best, 'validated', out['validated'])
    (I.OUT / file).write_text(json.dumps(out, indent=1))


def r31():
    b = dict(BASE_CONFIG)
    q1 = dict(b, exits='X2')
    carry_round({'Q1': q1, 'Q2': dict(q1, small_cap=True), 'Q3': dict(q1, gap_size=True),
                 'Q4': dict(q1, small_cap=True, gap_size=True), 'Q5': dict(b, exits='X5'), 'C2': b},
                'r31_exits_sizing.json', 'R31', ref='C2')


def r32():
    q1 = system_config_after('r31_exits_sizing.json')
    p2 = dict(q1, risk_high=.01)
    carry_round({'P1': dict(q1, gross=2.8), 'P2': p2, 'P3': dict(q1, max_new=4), 'P4': dict(p2, gross=2.8),
                 'P5': dict(p2, gross=2.8, max_new=4), 'Q1': q1}, 'r32_exposure.json', 'R32', ref='Q1')


def families(A, pool, w):
    """R33 setup families (signal masks on day t, all knowable at day t's close)."""
    fams = setup_families(A, w)
    e9p, e21p = prev(A['e9']), prev(A['e21'])
    with np.errstate(invalid='ignore'):
        pb = w & (e9p > e21p) & (A['low'] <= e9p) & (A['close'] >= e9p)
    return {'BO': w & union(fams['E6']), 'EP': ep_signal(A, pool), 'HS': w & union(fams['E11']), 'PB': pb}


def rotate(A, fams, lookback, top_only=False, lag=5):
    """Keep, each day, the families whose signals of the last `lookback` days (outcome known: signal day <= d-lag)
    had a positive mean `lag`-day return from the close; top_only keeps the single best of them."""
    c = A['close']
    T = len(c)
    fwd = np.full_like(c, np.nan)
    with np.errstate(invalid='ignore', divide='ignore'):
        fwd[:-lag] = c[lag:] / c[:-lag] - 1
    daily = {}
    for k, m in fams.items():
        x = np.where(m & np.isfinite(fwd), fwd, 0.0)
        daily[k] = (x.sum(1), (m & np.isfinite(fwd)).sum(1))
    keep = {k: np.zeros(T, bool) for k in fams}
    for d in range(T):
        hi, lo = d - lag, d - lag - lookback + 1
        if hi < 0:
            continue
        lo = max(lo, 0)
        score = {}
        for k, (s, n) in daily.items():
            cnt = n[lo:hi + 1].sum()
            if cnt:
                score[k] = s[lo:hi + 1].sum() / cnt
        good = {k: v for k, v in score.items() if v > 0}
        if top_only and good:
            good = {max(good, key=good.get): 0}
        for k in good:
            keep[k][d] = True
    out = np.zeros_like(c, bool)
    for k, m in fams.items():
        out |= m & keep[k][:, None]
    return out


def r33():
    p = system_config_after('r32_exposure.json')
    carry_round({t: dict(p, signals=t) for t in ('T1', 'T2', 'T3', 'T4', 'T5')} | {'P5': p},
                'r33_rotation.json', 'R33', ref='P5')


def base_path(A, pool, top=.10, weekly='9>21', band=.03, lookback=60, adr_min=0.0, trigger='both',
              close_stack=0.0, rising=False, higher_low=False):
    """R34 B path: a 6-month leader (top `top` on 126-day returns within `lookback` days) in a weekly uptrend
    ('9>21' weekly EMAs, or 'c>21' close above the weekly EMA21), sitting within `band` of its daily 9/21 EMA,
    breaking the prior-day high or (trigger='both') touching and holding the EMA9 / EMA21 ('e21': EMA21 only)
    (R40 variants).  R50: close_stack (daily 9 > 21 within that fraction), rising (21 and 50 EMA above their
    values 5 days earlier), higher_low (the last 5 days' low above the low of the 15 days before)."""
    c, h, l = A['close'], A['high'], A['low']
    e9p, e21p = prev(A['e9']), prev(A['e21'])
    with np.errstate(invalid='ignore', divide='ignore'):
        leader = S._past_any((A['pr126'] >= 1 - top) & A['rank_pool'], lookback)
        w21 = weekly_ema(c, A['days'], 21)
        up = (weekly_ema(c, A['days'], 9) > w21) if weekly == '9>21' else (c > w21)
        near = prev((np.abs(c / A['e9'] - 1) <= band) | (np.abs(c / A['e21'] - 1) <= band))
        trig = h > prev(h)
        if trigger == 'both':
            trig = trig | ((l <= e9p) & (c >= e9p)) | ((l <= e21p) & (c >= e21p))
        elif trigger == 'e21':
            trig = trig | ((l <= e21p) & (c >= e21p))
        fast = prev(A['adr'] >= adr_min) if adr_min else True
        extra = np.ones_like(pool)
        if close_stack:
            extra &= prev((A['e9'] > A['e21']) & (np.abs(A['e9'] / A['e21'] - 1) <= close_stack))
        if rising:
            extra &= prev((A['e21'] > luk.lag(A['e21'], 5)) & (A['e50'] > luk.lag(A['e50'], 5)))
        if higher_low:
            extra &= prior_low(l, 5) > luk.lag(prior_low(l, 15), 5)
    return pool & leader & prev(up) & near & trig & fast & extra


def r34():
    p = system_config_after('r32_exposure.json')
    l1 = dict(p, bpath=.10)
    carry_round({'L1': l1, 'L2': dict(l1, filter=None), 'L3': dict(l1, filter='IDX50'),
                 'L4': dict(p, signals='NONE', bpath=.10), 'L5': dict(l1, bpath=.20), 'P5': p},
                'r34_base_path.json', 'R34', ref='P5')


FULL = ('2024-01-02', '2026-10-16')


def bought(A, tr, located):
    """How many located trades the system actually opened on a day of their window (same stock, long)."""
    ours = {(t['code'], t['entry']) for t in tr if t['side'] > 0}
    return sum(any((str(A['codes'][j]), str(A['days'][d])) in ours for d in range(a, b + 1)) for _, j, a, b in located)


def minyear_round(cfgs, file, tag, ref, objective='min_year'):
    """R35+: choose the configuration whose worst calendar year (2024, 2025, 2026 to date) is highest, among those
    beating their full-period placebo median whose ledger hits (selection + validation) are at least the reference's;
    the whole 2024-2026 span is in-sample here."""
    A = us_arrays()
    trades = L.load(LEDGER)
    sel, val = L.split(trades, CUTOFF)
    ls = [x for x in located_longs(A, sel) if x[0].dated]
    lv = [x for x in located_longs(A, val) if x[0].dated]
    out = {'configs': cfgs, 'full': {}, 'fidelity': {}}
    for k, cfg in cfgs.items():
        entries, rules, mask, pool = build_system(A, cfg)
        st, tr = run_rules(A, entries, FULL, pool, rules)
        rs, rv = F.recall(mask, ls, A['has']), F.recall(mask, lv, A['has'])
        st['bought'] = dict(select=[bought(A, tr, ls), len(ls)], validate=[bought(A, tr, lv), len(lv)])
        st['min_year'] = float(min(st['by_year'].values()))
        y = st['by_year']
        st['min_2024_2025'] = float(min(y['2024'], y['2025'])) if y.get('2026', 0) > 0 else -9.0
        out['full'][k] = st
        out['fidelity'][k] = dict(select=[rs['hits'], rs['n']], validate=[rv['hits'], rv['n']])
        print(tag, k, f"full {st['total']:+.3f} dd {st['maxdd']:.2f} placebo median {st['placebo']['median']:+.3f} "
              f"p90 {st['placebo']['p90']:+.3f} rank {st['placebo']['rank']:.2f} trades/yr {st['per_year']:.0f} "
              f"win {st['win']:.3f} avg {st['avg_win']:+.3f}/{st['avg_loss']:+.3f} R {st['exp_r']:+.2f}",
              'years', {a: round(b, 3) for a, b in st['by_year'].items()}, 'fid', out['fidelity'][k],
              'bought', st['bought'], flush=True)
    need = sum(x[0] for x in out['fidelity'][ref].values())
    ok = [k for k in cfgs if k != ref and out['full'][k]['total'] > out['full'][k]['placebo']['median']
          and sum(x[0] for x in out['fidelity'][k].values()) >= need]
    best = max(ok + [ref], key=lambda k: out['full'][k][objective])
    out['chosen'], out['chosen_config'] = best, cfgs[best]
    out['objective'] = objective
    print(tag, 'chosen', best, objective, round(out['full'][best][objective], 3))
    (I.OUT / file).write_text(json.dumps(out, indent=1))


def r35():
    l5 = json.loads((I.OUT / 'r34_base_path.json').read_text())['configs']['L5']
    minyear_round({'M1': dict(l5, filter=None), 'M2': dict(l5, filter='IDX50'), 'M3': dict(l5, bpath=.30),
                   'M4': dict(l5, gap_size=True), 'M5': dict(l5, max_new=6), 'L5': l5},
                  'r35_minyear.json', 'R35', ref='L5')


def short_masks(A, pool):
    z = short_signals(A, pool)
    z.update(leader_shorts(A, pool))
    e9p,e21p,e50p = (prev(A[k]) for k in ('e9','e21','e50'))
    z['Z11'] = pool & (e9p < e21p) & (e21p < e50p) & (A['high'] >= e21p) & (A['close'] < e9p)
    reject = np.zeros_like(pool)
    for key in ('e9','e21','e50'):
        line = prev(A[key])
        reject |= (line < prev(line)) & (A['high'] >= line) & (A['close'] < line)
    z['Z12'] = pool & reject
    return z


def entries_short_capped(A, m, size_mult=1.0):
    """Close short entries, stop at the day's high moved down to close x (1 + cap) when wider (R36)."""
    c, h = A['close'], A['high']
    cap = stop_cap(A)
    out = [[] for _ in range(len(c))]
    for d, j in zip(*np.nonzero(m)):
        if not (np.isfinite(c[d, j]) and np.isfinite(h[d, j]) and c[d, j] > 0):
            continue
        stop = min(h[d, j], c[d, j] * (1 + cap[d, j]))
        if stop > c[d, j]:
            width = (stop - c[d, j]) / c[d, j]
            out[d].append((-A['to20'][d - 1, j], j, -1, c[d, j], stop, 'short', None,
                           width * size_mult if size_mult != 1.0 else None))
    return out


def r36():
    m2 = json.loads((I.OUT / 'r35_minyear.json').read_text())['chosen_config']
    h1 = dict(m2, shorts='Z6', short_gate=50)
    cfgs = {'H1': h1, 'H2': dict(h1, shorts='Z1'), 'H3': dict(h1, short_gate=21), 'H4': dict(h1, short_size=2.0),
            'H5': dict(h1, shorts='Z9'), 'M2': m2}
    minyear_round(cfgs, 'r36_shorts.json', 'R36', ref='M2')
    A = us_arrays()
    pool = stage_inputs(A, 21)['pool']
    shorts = [t for t in L.load(LEDGER) if t.side == 'short' and t.dated]
    sel, val = L.split(shorts, CUTOFF)
    z = short_masks(A, pool)
    path = I.OUT / 'r36_shorts.json'
    out = json.loads(path.read_text())
    out['short_fidelity'] = {}
    for name in ('Z1', 'Z6', 'Z9'):
        ls = F.locate(sel, A['days'], A['codes'], has=A['has'])[0]
        lv = F.locate(val, A['days'], A['codes'], has=A['has'])[0]
        out['short_fidelity'][name] = dict(select=F.recall(z[name], ls, A['has'])['hits'], n_select=len(ls),
                                           validate=F.recall(z[name], lv, A['has'])['hits'], n_validate=len(lv))
    print('R36 short fidelity', out['short_fidelity'])
    path.write_text(json.dumps(out, indent=1))


def r37():
    m2 = json.loads((I.OUT / 'r35_minyear.json').read_text())['chosen_config']
    minyear_round({x: dict(m2, exits=x) for x in ('X6', 'X7', 'X8', 'X9', 'X10')} | {'M2': m2},
                  'r37_exits.json', 'R37', ref='M2')


def theme_priority(A, entries, rho=.5, n=60):
    """R52: entries ranked by how many of the same day's entries moved with them (daily return correlation >= rho
    over the previous n days) -- his "several names of one theme in the scans at once"; ties keep the turnover
    order.  Priorities become (-count, previous priority) tuples."""
    c = A['close']
    with np.errstate(invalid='ignore', divide='ignore'):
        r = c / luk.lag(c) - 1
    out = []
    for d, lst in enumerate(entries):
        if len(lst) < 2 or d <= n:
            out.append(lst)
            continue
        x = np.nan_to_num(r[d - n:d][:, [e[1] for e in lst]])
        x = x - x.mean(0)
        sd = np.sqrt((x ** 2).sum(0))
        with np.errstate(invalid='ignore', divide='ignore'):
            cm = (x.T @ x) / np.outer(sd, sd)
        cnt = (np.nan_to_num(cm, nan=-1.0) >= rho).sum(1) - (sd > 0)
        out.append([((-int(k), e[0]),) + tuple(e[1:]) for k, e in zip(cnt, lst)])
    return out


def priority_score(A, name):
    """Higher = taken first: R38 scores from the previous day's data; R52 'rvol' and 'gain' use the entry day,
    known at its close (the fill)."""
    c = A['close']
    with np.errstate(invalid='ignore', divide='ignore'):
        if name == 'rvol':
            return A['turnover'] / prev(A['to20'])
        if name == 'gain':
            return c / prev(c) - 1
        if name == 'pr21':
            x = A['pr21']
        elif name == 'prior_gain':
            x = c / prev(c) - 1
        elif name == 'pr126':
            x = A['pr126']
        elif name == 'r3':
            x = c / luk.lag(c, 3) - 1
        elif name == 'pr21+pr126':
            x = A['pr21'] + A['pr126']
        elif name == 'tight':
            rng = A['high'] / A['low'] - 1
            x = -luk.rolling_mean(rng, 5) / luk.rolling_mean(rng, 20)
        elif name == 'dollar_range':
            x = A['to20'] * A['adr']
        elif name == 'adr5_to20':
            x = np.log(A['to20']) + 100 * (A['adr'] >= 5)
        else:
            raise ValueError(name)
    return prev(x)


def r38():
    m2 = json.loads((I.OUT / 'r35_minyear.json').read_text())['chosen_config']
    minyear_round({'O1': dict(m2, priority='pr21'), 'O2': dict(m2, priority='pr126'), 'O3': dict(m2, priority='r3'),
                   'O4': dict(m2, priority='pr21+pr126'), 'O5': dict(m2, priority='tight'), 'M2': m2},
                  'r38_priority.json', 'R38', ref='M2')


def r39():
    m2 = json.loads((I.OUT / 'r35_minyear.json').read_text())['chosen_config']
    minyear_round({'K1': dict(m2, risk_high=.008), 'K2': dict(m2, risk=.008, risk_high=.01),
                   'K3': dict(m2, max_position=.35), 'K4': dict(m2, max_position=.50, risk_high=.008),
                   'K5': dict(m2, risk=.01, risk_high=.01), 'M2': m2},
                  'r39_risk.json', 'R39', ref='M2')


def r40():
    k4 = json.loads((I.OUT / 'r39_risk.json').read_text())['configs']['K4']
    minyear_round({'B1': dict(k4, bopts=dict(weekly='c>21')), 'B2': dict(k4, bopts=dict(band=.05)),
                   'B3': dict(k4, bopts=dict(lookback=120)), 'B4': dict(k4, bopts=dict(adr_min=5.0)),
                   'B5': dict(k4, bopts=dict(trigger='pdh')), 'K4': k4},
                  'r40_bpath.json', 'R40', ref='K4', objective='min_2024_2025')


def r41():
    k4 = json.loads((I.OUT / 'r39_risk.json').read_text())['configs']['K4']
    minyear_round({x: dict(k4, exits=x) for x in ('X6', 'X7', 'X8', 'X9', 'X11')} | {'K4': k4},
                  'r41_exits.json', 'R41', ref='K4', objective='min_2024_2025')


def system_config_after(name):
    """The configuration a given carry round chose (for building the next round on top of it)."""
    return json.loads((I.OUT / name).read_text())['chosen_config']


HIS = {'2024': dict(ret=2.83, wins=104, losses=319, avg_win=.15, avg_loss=-.03),
       '2025': dict(ret=9.698, wins=209, losses=731, avg_win=.141, avg_loss=-.021)}


def year_trades(tr, y):
    t = [x for x in tr if x['entry'][:4] == y]
    win = [x['ret'] for x in t if x['ret'] > 0]
    loss = [x['ret'] for x in t if x['ret'] <= 0]
    return dict(n=len(t), wins=len(win), losses=len(loss), win=len(win) / len(t) if t else None,
                avg_win=float(np.mean(win)) if win else None, avg_loss=float(np.mean(loss)) if loss else None,
                exp_r=float(np.mean([x['r'] for x in t])) if t else None)


def final(report):
    """The configuration chosen in reports/<report> in all three markets: full period and calendar years against
    same-pool random entries and equal-weight holding of the pool, trade counts by year, and (US) ledger hits."""
    res = json.loads((I.OUT / report).read_text())
    cfg = res['chosen_config']
    trades = L.load(LEDGER)
    sel, val = L.split(trades, CUTOFF)
    out = {'report': report, 'chosen': res['chosen'], 'config': cfg, 'his': HIS}
    for market in ('us', 'hk', 'cn'):
        A = market_arrays(market)
        entries, rules, mask, pool = build_system(A, cfg)
        st, tr = run_rules(A, entries, FULL, pool, rules)
        span = A['days'][(A['days'] >= FULL[0]) & (A['days'] <= FULL[1])]
        st['data_span'] = [str(span[0]), str(span[-1])]
        years = sorted(st['by_year'])
        st['ew_hold_pool'] = ew_hold(A, pool, FULL)
        st['ew_hold_by_year'] = {y: ew_hold(A, pool, (f'{y}-01-01', f'{y}-12-31')) for y in years}
        st['trades_by_year'] = {y: year_trades(tr, y) for y in years}
        st['why'] = {w: sum(t['why'] == w for t in tr) for w in sorted({t['why'] for t in tr})}
        if market == 'us':
            ls = [x for x in located_longs(A, sel) if x[0].dated]
            lv = [x for x in located_longs(A, val) if x[0].dated]
            rs, rv = F.recall(mask, ls, A['has']), F.recall(mask, lv, A['has'])
            st['fidelity'] = {k: {a: b for a, b in r.items() if a != 'per_trade'} for k, r in (('select', rs),
                                                                                                ('validate', rv))}
            st['signals_per_day'] = F.width(mask, A['days'], *FULL)
        out[market] = st
        print('FINAL', market, f"full {st['total']:+.3f} dd {st['maxdd']:.2f} placebo median "
              f"{st['placebo']['median']:+.3f} rank {st['placebo']['rank']:.2f} ew {st['ew_hold_pool']:+.3f}",
              'years', {a: round(b, 3) for a, b in st['by_year'].items()},
              'ew years', {a: round(b, 3) for a, b in st['ew_hold_by_year'].items()},
              'trades', {y: (v['n'], v['win'] and round(v['win'], 3)) for y, v in st['trades_by_year'].items()},
              flush=True)
        del A
    (I.OUT / 'final_system.json').write_text(json.dumps(out, indent=1, default=float))


STAGES = ('no_signal', 'no_entry', 'market_filter', 'daily_cap', 'no_room', 'traded')


def diagnose(report):
    """For each of his dated longs: the furthest step the system reached on a day of the trade's window (signal,
    entry after the stop rule, market filter, daily cap, actually opened) and our result when we traded it."""
    cfg = json.loads((I.OUT / report).read_text())['chosen_config']
    A = us_arrays()
    trace = {}
    entries, rules, mask, pool = build_system(A, cfg, trace)
    st, tr = run_rules(A, entries, FULL, pool, rules, placebo=0)
    ours = {(t['code'], t['entry']): t for t in tr}
    sets = {k: [{e[1] for e in lst} for lst in trace[k]] for k in ('raw', 'filtered', 'capped')}
    rows = []
    for t, j, a, b in located_longs(A, L.load(LEDGER)):
        if not t.dated or t.entry_date < FULL[0]:
            continue
        code, best, ours_t, n_day, place = str(A['codes'][j]), 0, None, None, None
        for d in range(a, b + 1):
            k = 0
            if mask[d, j]:
                k = 1
                if j in sets['raw'][d]:
                    k = 2
                    if j in sets['filtered'][d]:
                        k = 3
                        if j in sets['capped'][d]:
                            k = 4
                            if (code, str(A['days'][d])) in ours:
                                k = 5
                                ours_t = ours[(code, str(A['days'][d]))]
            if k >= 3 and (place is None or k > best):
                order = [e[1] for e in sorted(trace['filtered'][d], key=lambda e: e[0])]
                n_day, place = len(order), order.index(j) + 1
            best = max(best, k)
        rows.append(dict(id=t.id, ticker=t.ticker, date=t.entry_date, his_r=t.r_multiple, his_outcome=t.outcome,
                         step=STAGES[best], our_r=ours_t and round(ours_t['r'], 2),
                         our_ret=ours_t and round(ours_t['ret'], 3), our_days=ours_t and ours_t['days'],
                         our_why=ours_t and ours_t['why'], entries_that_day=n_day, his_place=place))
        rows[-1]['input_days'] = [dict(day=str(A['days'][d]),
            **{name: bool(trace[name][d,j]) for name in ('pool','strength','watch_type','watch','ep','main_signal','base_path') if name in trace},
            prior_adr=float(A['adr'][d-1,j]), prior_turnover=float(A['to20'][d-1,j]),
            gap=float(A['open'][d,j]/A['close'][d-1,j]-1),
            relative_turnover=float(A['turnover'][d,j]/A['to20'][d-1,j])) for d in range(a,b+1) if d>0]
    by_year = {}
    for r in rows:
        y = by_year.setdefault(r['date'][:4], {k: 0 for k in STAGES})
        y[r['step']] += 1
    pnl = {}
    for t in tr:
        y = pnl.setdefault(t['entry'][:4], {})
        y[t['code']] = y.get(t['code'], 0.0) + t['pnl']
    top = {y: sorted(v.items(), key=lambda x: -x[1])[:10] for y, v in pnl.items()}
    out = dict(report=report, by_year=by_year, rows=rows, top_names=top, stats={k: v for k, v in st.items()})
    for r in rows:
        print('DIAG', r)
    print('DIAG by year', by_year)
    print('DIAG top names', {y: [(c, round(v, 3)) for c, v in x] for y, x in top.items()})
    for t in sorted(tr, key=lambda t: -t['pnl'])[:15]:
        print('DIAG top trade', {k: (round(v, 3) if isinstance(v, float) else v) for k, v in t.items()})
    (I.OUT / 'diagnose.json').write_text(json.dumps(out, indent=1, default=float))


def robust(report):
    """How fragile is the chosen configuration?  Real runs only (no placebo): start-date shifts, one-step neighbours
    of the knobs the rounds tuned, the add / risk-scale / climax rules switched off, and doubled costs.  Reported,
    never used to choose."""
    cfg = json.loads((I.OUT / report).read_text())['chosen_config']
    A = us_arrays()
    ro = cfg.get('rule_opts', {})
    variants = {'base': {}, 'max_new 3': {'max_new': 3}, 'max_new 5': {'max_new': 5},
                'risk x0.8': {'risk': cfg['risk'] * .8, 'risk_high': cfg.get('risk_high', 0) * .8},
                'risk x1.2': {'risk': cfg['risk'] * 1.2, 'risk_high': cfg.get('risk_high', 0) * 1.2},
                'max_position .4': {'max_position': .4}, 'max_position .6': {'max_position': .6},
                'gross 2.4': {'gross': 2.4}, 'gross 3.2': {'gross': 3.2},
                'stop_min .008': {'stop_min': .008}, 'stop_min .012': {'stop_min': .012},
                'no adds': {'rule_opts': {'add_r': 0.0, 'add_levels': []}},
                'no risk scale': {'rule_opts': {'risk_scale': ''}},
                'no climax exit': {'rule_opts': {'exit_signal': ''}},
                'costs x2': {'rule_opts': {'buy_cost': .001, 'sell_cost': .001}}}
    out = {'report': report, 'config': cfg, 'variants': {}, 'starts': {}}
    for name, change in variants.items():
        c = merged(cfg, change)
        entries, rules, mask, pool = build_system(A, c)
        st = run_rules(A, entries, FULL, pool, rules, placebo=0)[0]
        out['variants'][name] = {k: st[k] for k in ('total', 'maxdd', 'per_year', 'win', 'by_year')}
        print('ROBUST', name, f"full {st['total']:+.3f} dd {st['maxdd']:.2f}",
              {a: round(b, 3) for a, b in st['by_year'].items()}, flush=True)
    entries, rules, mask, pool = build_system(A, cfg)
    for start in ('2024-01-02', '2024-02-01', '2024-03-01', '2024-04-01', '2024-07-01', '2025-01-02'):
        st = run_rules(A, entries, (start, FULL[1]), pool, rules, placebo=0)[0]
        out['starts'][start] = {k: st[k] for k in ('total', 'maxdd', 'by_year')}
        print('ROBUST start', start, f"full {st['total']:+.3f} dd {st['maxdd']:.2f}",
              {a: round(b, 3) for a, b in st['by_year'].items()}, flush=True)
    (I.OUT / 'robust.json').write_text(json.dumps(out, indent=1, default=float))


ROUNDS = Path(__file__).resolve().parent / 'notes' / 'rounds'


def merged(base, change):
    """A configuration with `change` applied; nested option dicts (bopts, ep_opts, rule_opts) are merged."""
    out = dict(base)
    for k, v in change.items():
        out[k] = dict(base.get(k) or {}, **v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def run_round(name):
    """Run notes/rounds/<name>.json: {"stage", "base": [report, key | "chosen"], "ref", "objective",
    "candidates": {key: changes}}; results go to reports/<name lower-case>.json."""
    spec = json.loads((ROUNDS / f'{name}.json').read_text(encoding='utf-8'))
    report, key = spec['base']
    res = json.loads((I.OUT / report).read_text())
    base = res['chosen_config'] if key == 'chosen' else res['configs'][key]
    cfgs = {k: merged(base, v) for k, v in spec['candidates'].items()}
    cfgs[spec['ref']] = base
    minyear_round(cfgs, f'{name.lower()}.json', name, ref=spec['ref'],
                  objective=spec.get('objective', 'min_2024_2025'))


if __name__ == '__main__' and sys.argv[1] == 'round':
    run_round(sys.argv[2])
elif __name__ == '__main__' and sys.argv[1] == 'final':
    final(sys.argv[2])
elif __name__ == '__main__' and sys.argv[1] == 'diagnose':
    diagnose(sys.argv[2])
elif __name__ == '__main__' and sys.argv[1] == 'robust':
    robust(sys.argv[2])
elif __name__ == '__main__':
    {'r19': r19, 'r20': r20, 'r21': r21, 'r21b': r21b, 'r22': r22, 'r22b': r22b, 'r23': r23, 'r23b': r23b, 'r23c': r23c, 'r24': r24, 'r24b': r24b, 'r25': r25, 'r26': r26,
     'r27': r27, 'r27b': r27b, 'r28': r28, 'r29': r29, 'r30': r30, 'r31': r31, 'r32': r32, 'r33': r33, 'r34': r34, 'r35': r35, 'r36': r36, 'r37': r37, 'r38': r38, 'r39': r39, 'r40': r40, 'r41': r41}[sys.argv[1]]()
