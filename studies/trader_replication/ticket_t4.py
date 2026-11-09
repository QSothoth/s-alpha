"""T4 and later: the evening list (top K of the pool by 20-day turnover x ADR at t-1) in front of a system's long signals.

    $PY -m studies.trader_replication.ticket_t4 <id> <round>
"""
from __future__ import annotations

import sys
from dataclasses import replace

import numpy as np

from . import panels, review as RV, systems as SY, watchlist as WL

WINDOW = panels.WINDOW


def ranks(A, pool):
    if getattr(pool, 'shape', None) != A['close'].shape:
        pool = np.isfinite(A['close'])
    m = WL.measures(A)['dollar_range']
    v = np.vstack([np.full((1, m.shape[1]), np.nan), m[:-1]])
    prior = np.vstack([np.zeros((1, pool.shape[1]), bool), pool[:-1]])
    v = np.where(prior, v, np.nan)
    o = np.argsort(np.argsort(-np.where(np.isfinite(v), v, -np.inf), axis=1), axis=1)
    return np.where(np.isfinite(v), o, 10 ** 6)


def listed(entries, rk, K, n):
    out = []
    for d, lst in enumerate(entries):
        lon = sorted((e for e in lst if e[2] > 0 and rk[d, e[1]] < K), key=lambda e: e[0])
        out.append(lon[:n] + [e for e in lst if e[2] <= 0])
    return out


def ordered(entries, rk, K, n, ep):
    out = []
    for d, lst in enumerate(entries):
        lon = [e for e in lst if e[2] > 0]
        eps = sorted((e for e in lon if ep and str(e[5]).lower().startswith('ep')), key=lambda e: e[0])
        rest = sorted((e for e in lon if rk[d, e[1]] < K and e not in eps), key=lambda e: rk[d, e[1]])
        out.append((eps + rest)[:n] + [e for e in lst if e[2] <= 0])
    return out


ROUNDS = dict(P1=dict(PM10=(10, 4), PM20=(20, 4), PM30=(30, 4), PM20n8=(20, 8)), T4=dict(T4A=(30, 4), T4B=(50, 4), T4C=(100, 4), T4D=(50, 8), T4E=(100, 8)),
              T5=dict(T5A=(30, 8, .17), T5B=(50, 8, .17), T5C=(100, 8, .17), T5D=(30, 99, .17), T5E=(50, 99, .10)),
              T7=dict(T7A=(30, 4, None, False), T7B=(50, 4, None, False), T7C=(50, 4, None, True), T7D=(50, 6, None, True), T7E=(100, 6, None, True)),
              T8=dict(T8A=(50, 8, .17, dict(trims=(3,), trim_frac=.5)), T8B=(50, 8, .17, dict(trims=(2,), trim_frac=.5)), T8C=(50, 8, .17, dict(max_days=10)),
                      T8D=(50, 8, .17, dict(max_days=5)), T8E=(50, 8, .17, dict(trims=(3,), trim_frac=.5, max_days=10))))


def main(id_, name):
    W, cfg = SY.get(id_).load()
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    his = [x for x in base.located(A, base.trades()) if '2024-01-02' <= x[0].entry_date <= '2025-12-31' and x[0].side == 'long']
    reg, rg, _, pg = W.build(A, cfg)
    wide, rules, mask, pool = W.build(A, {**cfg, 'max_new': 0})
    rk = ranks(A, pool)
    if name.startswith('P'):
        from .pick_map import pick_rank
        rk = pick_rank(A, rk, id_)
    out = dict(id=id_, round=name, tickets=len(his), results={})
    for k, c in {'REG': None, **ROUNDS[name]}.items():
        if c is None:
            e, ru, po = reg, rg, pg
        else:
            e, ru, po = listed(wide, rk, *c[:2]), replace(rules, max_new_long=0, max_new_by_kind={}), pool
            if len(c) > 3 and isinstance(c[3], dict):
                ru = replace(ru, **c[3])
            elif len(c) > 3:
                e = ordered(wide, rk, c[0], c[1], c[3])
            if len(c) > 2 and c[2]:
                ru = replace(ru, max_position=c[2])
        st, tr = base.run(A, e, WINDOW, po, ru, placebo=0, audit=True)
        st.pop('_curve', None)
        b = st['behaviour']
        o = {(t['code'], t['entry']): t for t in tr if t['side'] > 0}
        got = {}
        for t, j, a, z in his:
            for d in range(a, z + 1):
                x = o.get((str(A['codes'][j]), str(A['days'][d])))
                if x:
                    got[t.id] = (t.ticker, round(x['ret'], 3))
        r = out['results'][k] = dict(by_year=st['by_year'], maxdd=st['maxdd'], per_year=b['per_year'], win=b['win'], avg_win=b['avg_win'],
                                     avg_loss=b['avg_loss'], days_win=b['days_win'], bought=len(got), got=got)
        print(k, {y: round(v, 2) for y, v in r['by_year'].items()}, f"dd {r['maxdd']:.2f} n/yr {r['per_year']:.0f} win {r['win']:.3f}",
              f"aw {r['avg_win']:+.3f} al {r['avg_loss']:+.3f} dw {r['days_win']:.1f} bought {r['bought']}/{len(his)}", flush=True)
        RV.write(f'ticket_{id_}_{name}.json', out)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
