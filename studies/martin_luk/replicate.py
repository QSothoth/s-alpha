"""Martin Luk as the first case of skills/trader-replication: stage masks on the point-in-time US daily panel,
scored against his public trades (notes/trades.csv) and against random entry on the same stocks.

    nice -n 19 /opt/futu-opend/venv/bin/python -m studies.martin_luk.replicate r19
"""
from __future__ import annotations

from dataclasses import replace
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
    """US: broad point-in-time panel; HK / CN: data/trend-scan lists chosen by 2026-10 liquidity (survivorship)."""
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


POOLS = {'U0': (5, 20e6, 4), 'U1': (1, 100e6, 4), 'U2': (1, 100e6, 3), 'U3': (1, 50e6, 4), 'U4': (2, 50e6, 3)}


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
    wk = prev(weekly_ema(A['close'], A['days'], 9) > weekly_ema(A['close'], A['days'], 21))
    was_not = S._past_any(~A['stack'], 10)                     # some day in t-10..t-1 not stacked
    not_before = prev(was_not)                                 # ... shifted: some day in t-11..t-2
    with np.errstate(invalid='ignore'):
        above50 = prev(A['close'] > A['e50'])
    ones = np.ones_like(stack)
    with np.errstate(invalid='ignore'):
        big = prev(A['to20'] >= 100e6)                          # R22b: he only adds $100M+ names to watchlists
        fast = prev(A['adr'] >= 5)
    return {'V0': stack, 'V1': stack | wk, 'V2': above50, 'V3': stack & not_before, 'V4': ones,
            'V5': (stack | wk) & big, 'V6': stack & big, 'V7': above50 & big, 'V8': (stack | wk) & fast, 'V9': big}


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
    return {'E1': e1, 'E2': e2, 'E3': e3, 'E4': e4, 'E5': e2 | e3 | e4}


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
            'E10': {'E2': s['E1'] & near, 'E4': s['E4'] & near}}


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


def stop_cap(A):
    return np.fmin(.05, .5 * prev(A['adr']) / 100)


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
    ema = {'e9': A['e9'], 'e21': A['e21']}
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


def pool_for(A):
    """US: the R20 pool; HK / CN: top 30% by 20-day turnover in that market, price floor, the same ADR floor."""
    spec = POOLS[chosen('r20_pool.json', 'U0')]
    if A['market'] == 'us':
        return pool_mask(A, *spec)
    with np.errstate(invalid='ignore'):
        cut = np.nanquantile(np.where(A['rank_pool'], A['to20'], np.nan), .7, axis=1)
        m = (A['to20'] >= cut[:, None]) & (A['raw'] >= FLOOR[A['market']]) & (A['adr'] >= spec[2])
    return prev(m)


def system_signals(A):
    pool = pool_for(A)
    k = pool & strength_lists(A, pool)[strength_choice()]
    w = k & watch_lists(A)[watch_choice()]
    return pool, w, {x: w & m for x, m in setup_families(A, w)[setup_choice()].items()}


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


def ep_signal(A, pool):
    """His pre-market gapper scan, without the leader list: gap >= max(5%, ADR), double volume, holds the open."""
    o, c = A['open'], A['close']
    with np.errstate(invalid='ignore', divide='ignore'):
        gap = o >= prev(c) * (1 + np.fmax(.05, prev(A['adr']) / 100))
        vol = A['turnover'] >= 2 * prev(A['to20'])
        return pool & gap & vol & (c >= o)


def entries_close_stop(A, mask, mode, kind='n1'):
    """Close entries with the stop at the day's low; when that is wider than cap = min(5%, 0.5 ADR):
    'skip' drops the trade (R24 N1), 'cap' moves the stop up to the cap, 'half' to half the cap (R30)."""
    c, l = A['close'], A['low']
    cap = stop_cap(A)
    out = [[] for _ in range(len(c))]
    for d, j in zip(*np.nonzero(mask)):
        if not (np.isfinite(c[d, j]) and np.isfinite(l[d, j]) and c[d, j] > 0):
            continue
        if mode == 'skip':
            if not (0 < (c[d, j] - l[d, j]) / c[d, j] <= cap[d, j]):
                continue
            stop = l[d, j]
        else:
            width = cap[d, j] if mode == 'cap' else cap[d, j] / 2
            stop = max(l[d, j], c[d, j] * (1 - width))
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
BASE_CONFIG = dict(signals='C2', stop='cap', exits='X0', small_cap=False, gap_size=False, gross=2.0, risk=.005,
                   filter='S4', rank=None, rank_n=0)
CARRY = ['r31_exits_sizing.json', 'r32_exposure.json', 'r33_rotation.json', 'r34_base_path.json']                   # carry rounds in order; each later round extends this list


def system_config():
    """The configuration carried forward by the latest finished carry round (BASE_CONFIG = R30's C2)."""
    cfg = dict(BASE_CONFIG)
    for name in CARRY:
        path = I.OUT / name
        if path.exists():
            cfg = json.loads(path.read_text())['chosen_config']
    return cfg


def build_system(A, cfg):
    """Entries, rules, signal mask and placebo pool for a configuration, in any market."""
    pool, w, sig = system_signals(A)
    if cfg['signals'] == 'NONE':
        mask = np.zeros_like(w)
    elif cfg['signals'] in ('C0', 'C1', 'C2', 'C3'):
        base = union(sig)
        mask = {'C0': base, 'C1': base, 'C2': base | ep_signal(A, pool), 'C3': ep_signal(A, pool)}[cfg['signals']]
    else:                                              # R33 families and rotation
        fam = families(A, pool, w)
        mask = {'T1': lambda: union(fam), 'T2': lambda: rotate(A, fam, 20),
                'T3': lambda: rotate(A, fam, 20, top_only=True), 'T4': lambda: rotate(A, fam, 40),
                'T5': lambda: fam['HS'] | fam['EP'] | fam['PB']}[cfg['signals']]()
    if cfg.get('bpath'):
        mask = mask | base_path(A, pool, cfg['bpath'])
    if A['market'] == 'cn':
        mask = mask & ~limit_up(A)
    if cfg.get('rank'):
        mask = top_per_day(mask, prev(A[cfg['rank']]), cfg['rank_n'])
    entries = entries_close_stop(A, mask, cfg['stop'])
    if cfg['small_cap'] or cfg['gap_size']:
        adrp, to20p = prev(A['adr']), prev(A['to20'])
        entries = [[e[:6] + (None, .5 * adrp[d, e[1]] / 100 if cfg['gap_size'] else None,
                             .20 if cfg['small_cap'] and to20p[d, e[1]] < 100e6 else None) for e in lst]
                   for d, lst in enumerate(entries)]
    if cfg['filter'] == 'S4':
        entries = filter_days(entries, breadth_ok(A, w))
    elif cfg['filter'] == 'IDX50':
        entries = filter_days(entries, ew_index_up(A, pool, 50))
    if cfg.get('max_new'):
        entries = [sorted(lst, key=lambda e: e[0])[:cfg['max_new']] for lst in entries]
    rules = replace(RULES, **EXITS[cfg['exits']], max_gross=cfg['gross'], risk=cfg['risk'],
                    feedback=10 if cfg.get('risk_high') else 0, risk_low=cfg['risk'],
                    risk_high=cfg.get('risk_high', 0.0),
                    buy_cost=COSTS[A['market']][0], sell_cost=COSTS[A['market']][1])
    return entries, rules, mask, pool


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


def base_path(A, pool, top=.10):
    """R34 B path: a 6-month leader (top `top` on 126-day returns within 60 days) in a weekly uptrend, sitting
    near its daily 9/21 EMA, breaking the prior-day high or touching and holding the EMA9 / EMA21."""
    c, h, l = A['close'], A['high'], A['low']
    e9p, e21p = prev(A['e9']), prev(A['e21'])
    with np.errstate(invalid='ignore', divide='ignore'):
        leader = S._past_any((A['pr126'] >= 1 - top) & A['rank_pool'], 60)
        weekly = prev(weekly_ema(c, A['days'], 9) > weekly_ema(c, A['days'], 21))
        near = prev((np.abs(c / A['e9'] - 1) <= .03) | (np.abs(c / A['e21'] - 1) <= .03))
        trigger = (h > prev(h)) | ((l <= e9p) & (c >= e9p)) | ((l <= e21p) & (c >= e21p))
    return pool & leader & weekly & near & trigger


def r34():
    p = system_config_after('r32_exposure.json')
    l1 = dict(p, bpath=.10)
    carry_round({'L1': l1, 'L2': dict(l1, filter=None), 'L3': dict(l1, filter='IDX50'),
                 'L4': dict(p, signals='NONE', bpath=.10), 'L5': dict(l1, bpath=.20), 'P5': p},
                'r34_base_path.json', 'R34', ref='P5')


def system_config_after(name):
    """The configuration a given carry round chose (for building the next round on top of it)."""
    return json.loads((I.OUT / name).read_text())['chosen_config']


if __name__ == '__main__':
    {'r19': r19, 'r20': r20, 'r21': r21, 'r21b': r21b, 'r22': r22, 'r22b': r22b, 'r23': r23, 'r23b': r23b, 'r23c': r23c, 'r24': r24, 'r24b': r24b, 'r25': r25, 'r26': r26,
     'r27': r27, 'r27b': r27b, 'r28': r28, 'r29': r29, 'r30': r30, 'r31': r31, 'r32': r32, 'r33': r33, 'r34': r34}[sys.argv[1]]()
