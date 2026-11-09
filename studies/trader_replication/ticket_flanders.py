"""Flanders rounds of the ticket-first work (notes/PREREG_L*.md): the evening list in front of his signals.

    $PY -m studies.trader_replication.ticket_flanders L1
"""
from __future__ import annotations

import math
import sys
from dataclasses import replace

import numpy as np

from . import panels, review as RV, systems as SY, ticket_t4 as T4, watchlist as WL

WINDOW = panels.WINDOW
ALL = dict(setups=['hi52', 'ep', 'vcp', 'pp', 'pb', 'brkv'], brkv=dict(listing=True))
ROUNDS = dict(L1=dict(REG=({}, 0, False), L1A=({}, 50, False), L1B=({}, 100, False), L1C=(ALL, 50, False), L1D=(ALL, 100, False),
                      L1E=(ALL, 50, True)))
ROUNDS['L2'] = dict(REG=({}, 0, False, 0, None),
                    L2A=(ALL, 100, True, 0, dict(max_new_long=4, max_open=12)),
                    L2B=(ALL, 100, True, 0, dict(max_new_long=4, max_open=12, max_gross=2.0)),
                    L2C=(ALL, 100, True, 1, dict(max_new_long=4, max_open=12, max_gross=2.0)),
                    L2D=(ALL, 100, True, 1, dict(max_new_long=6, max_open=16, max_gross=2.0)),
                    L2E=(ALL, 50, True, 1, dict(max_new_long=4, max_open=12, max_gross=2.0)))
_C = dict(max_open=12, max_gross=2.0)
_S = dict(_C, max_new_long=4, max_new_by_kind={'ep': 2})
ROUNDS['L3'] = dict(REG=({}, 0, False, 0, None), L3A=(ALL, 50, True, 2, dict(_C, max_new_long=4)), L3B=(ALL, 50, True, 1, _S),
                    L3C=(ALL, 50, True, 1, _S, (30, 2.0)), L3D=(ALL, 100, True, 1, _S), L3E=(ALL, 50, True, 1, _S, (50, 2.0)))
_T = dict(rule_opts=dict(trail='ema21'))
_ADD = dict(common=dict(add=dict(frac=.5, max=1, stop='keep', profit=True)))
_L3A = (50, True, 2, dict(_C, max_new_long=4))
ROUNDS['L4'] = dict(REG=({}, 0, False, 0, None), L3A=(ALL,) + _L3A, L4A=({**ALL, **_T},) + _L3A, L4B=({**ALL, **_T, **_ADD},) + _L3A,
                    L4C=({**ALL, **_ADD},) + _L3A, L4D=({**ALL, **_T, 'near': .9},) + _L3A, L4E=({**ALL, **_T, **_ADD, 'near': .9},) + _L3A)
def _rot(x):
    return (50, True, 2, dict(_C, max_new_long=4, rotate_below=x))


ROUNDS['L5'] = dict(L3A=(ALL,) + _L3A, L5A=({**ALL, **_T},) + _rot(.001), L5B=({**ALL, **_T},) + _rot(.05), L5C=({**ALL, **_T},) + _rot(.10),
                    L5D=({**ALL, **_T, **_ADD},) + _rot(.05), L5E=(ALL,) + _rot(.05))
_N = dict(_C, max_new_long=4, nft_days=1)
_R = dict(_N, rotate_below=.03, rotate_min_days=3)
_P = dict(add_r=2.0, add_frac=.5, add_cap_mult=2.0, add_cap_limit=.5)
_NOTRIM = dict(trims=(), trim_frac=0.0, trim_day=0)
ROUNDS['L6'] = dict(L3A=(ALL,) + _L3A, L6A=({**ALL, **_T}, 50, True, 2, _N), L6B=({**ALL, **_T}, 50, True, 2, _R),
                    L6C=({**ALL, **_T}, 50, True, 2, dict(_R, **_P)), L6D=({**ALL, **_T}, 50, True, 2, dict(_R, **_NOTRIM)),
                    L6E=({**ALL, **_T}, 50, True, 2, dict(_R, **_P, **_NOTRIM)))
def _lead(**kw):
    return dict(_C, max_new_long=4, management_by_kind={k: kw for k in ('hi52', 'vcp', 'pp', 'pb', 'brkv')})


ROUNDS['L7'] = dict(L3A=(ALL,) + _L3A, L7A=(ALL, 50, True, 2, _lead(trail='ema21')), L7B=(ALL, 50, True, 2, _lead(trail='sma50')),
                    L7C=(ALL, 50, True, 2, dict(_lead(trail='ema21', add_r=2.0), add_frac=.5, add_cap_mult=2.0, add_cap_limit=.5)),
                    L7D=(ALL, 50, True, 2, _lead(trail='ema21', trims=(), trim_frac=0.0)),
                    L7E=(ALL, 50, True, 2, _lead(trail='sma50', trims=(), trim_frac=0.0)))
_L7C = dict(_lead(trail='ema21', add_r=2.0), add_frac=.5, add_cap_mult=2.0, add_cap_limit=.5)
_FAIL = dict(rotate_below=.0001, rotate_min_days=5)
ROUNDS['L8'] = dict(L7C=(ALL, 50, True, 2, _L7C), L8A=(ALL, 100, True, 2, _L7C), L8B=(ALL, 50, True, 2, dict(_L7C, max_new_long=5)),
                    L8C=(ALL, 50, True, 2, dict(_L7C, max_open=14)), L8D=(ALL, 50, True, 2, dict(_L7C, **_FAIL)),
                    L8E=(ALL, 50, True, 2, dict(_L7C, max_new_long=5, **_FAIL)))
_BASE = dict(_C, max_new_long=4, max_open=14)
_ADD2 = dict(add_r=2.0, add_frac=.5, add_cap_mult=2.0, add_cap_limit=.5)
ROUNDS['U1'] = dict(L8C=(ALL, 50, True, 2, dict(_L7C, max_open=14)), U1A=(ALL, 50, True, 2, dict(_BASE, trail='ch3')), U1B=(ALL, 50, True, 2, dict(_BASE, trail='ch4')),
                    U1C=(ALL, 50, True, 2, dict(_BASE, trail='ch5')), U1D=(ALL, 50, True, 2, dict(_BASE, trail='ch4', **_ADD2)),
                    U1E=(ALL, 50, True, 2, dict(_BASE, trail='ch3', **_ADD2)))
HIS = {'2024': 4.335, '2025': 1.675}


def gap(y):
    return float(np.mean([abs(math.log((1 + y[k]) / (1 + v))) for k, v in HIS.items()]))


def keep(entries, rk, K, ep_free):
    return [[e for e in lst if e[2] <= 0 or rk[d, e[1]] < K or (ep_free and e[5] == 'ep')] for d, lst in enumerate(entries)]


def main(name):
    W, cfg = SY.get('christian_flanders').load()
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    his = [x for x in base.located(A, base.trades()) if '2024-01-02' <= x[0].entry_date <= '2025-12-31' and x[0].side == 'long']
    out = dict(round=name, tickets=len(his), results={})
    rk = None
    hi, lo = A['high'].astype(float), A['low'].astype(float)
    top = np.full(hi.shape, np.nan)
    for i in range(21, len(hi)):
        top[i] = np.nanmax(hi[i - 21:i + 1], axis=0)
    rng = WL.roll_mean(hi - lo, 20)
    for k_ in (3, 4, 5):
        A[f'ch{k_}'] = top - k_ * rng
    for k, v in ROUNDS[name].items():
        c, K, free, first, change, tier = (v + (0, None, None))[:6] if len(v) < 5 else (v + (None,))[:6]
        near = c.get('near')
        merged = {**cfg, **{a: b for a, b in c.items() if a != 'near'}}
        for key in ('rule_opts', 'common'):
            if key in c:
                merged[key] = {**cfg.get(key, {}), **c[key]}
        e, rules, mask, pool = W.build(A, merged)
        if near:
            top = np.full(A['high'].shape, np.nan)
            hi = A['high'].astype(float)
            for i in range(251, len(top)):
                top[i] = np.nanmax(hi[i - 251:i + 1], axis=0)
            e = [[x for x in lst if x[2] <= 0 or x[5] == 'ep' or A['close'][d, x[1]] >= near * top[d, x[1]]] for d, lst in enumerate(e)]
        if rk is None:
            rk = T4.ranks(A, pool)
        if K:
            e = keep(e, rk, K, free)
        if first:
            def pr(x, d):
                if first == 2 and x[5] == 'ep':
                    return -2e7
                if x[2] > 0 and rk[d, x[1]] < K:
                    return float(rk[d, x[1]] - 10 ** 7)
                return float(x[0]) if not isinstance(x[0], tuple) else 0.0
            e = [[(pr(x, d),) + x[1:] for x in lst] for d, lst in enumerate(e)]
        if tier:
            def lift(x, d):
                if x[2] > 0 and rk[d, x[1]] < tier[0]:
                    x = x + (None,) * (10 - len(x))
                    return x[:9] + (tier[1],) + x[10:]
                return x
            e = [[lift(x, d) for x in lst] for d, lst in enumerate(e)]
        if change:
            rules = replace(rules, **change)
        st, tr = base.run(A, e, WINDOW, pool, rules, placebo=0, audit=True)
        st.pop('_curve', None)
        b = st['behaviour']
        o = {(t['code'], t['entry']): t for t in tr if t['side'] > 0}
        got = {}
        for t, j, a, z in his:
            for d in range(a, z + 1):
                x = o.get((str(A['codes'][j]), str(A['days'][d])))
                if x:
                    got[t.id] = (t.ticker, round(x['ret'], 3))
        rets = [g[1] for g in got.values()]
        r = out['results'][k] = dict(by_year=st['by_year'], maxdd=st['maxdd'], per_year=b['per_year'], win=b['win'], avg_win=b['avg_win'], avg_loss=b['avg_loss'],
                                     days_win=b['days_win'], bought=len(got), gap=gap(st['by_year']), ticket_mean=float(np.mean(rets)) if rets else None, got=got)
        print(k, {y: round(v, 2) for y, v in r['by_year'].items()}, f"dd {r['maxdd']:.2f} n/yr {r['per_year']:.0f} win {r['win']:.3f} aw {r['avg_win']:+.3f}",
              f"al {r['avg_loss']:+.3f} dw {r['days_win']:.1f} bought {r['bought']}/{len(his)} gap {r['gap']:.3f} tmean {r['ticket_mean']}", flush=True)
        RV.write(f'ticket_christian_flanders_{name}.json', out)


if __name__ == '__main__':
    main(sys.argv[1])
