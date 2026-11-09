"""Historical M2: the fold-held-out model trains on later tickets and is not a causal backtest or live score.

It removes the index gate; see studies/martin_luk/notes/PREREG_M2.md for the timing correction.

    $PY -m studies.trader_replication.martin_m2
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np

from . import panels, review as RV, systems as SY, ticket_t4 as T4
from .martin_m1 import report
from .martin_words import FOLDS, WORDS, words
from .pick_model import DAY, K, NAMES, day_matrix, features, fit

WINDOW = panels.WINDOW
CACHE = Path(__file__).resolve().parents[2] / 'data' / 'martin-luk-cache' / 'm2_score.npy'
CANDS = dict(M2A=(False, 8, .06, .0015), M2B=(True, 8, .06, .0015), M2C=(True, 4, .06, .0015), M2D=(True, 14, .06, .0015), M2E=(True, 8, .17, .005))


def scores(A, base, rk):
    if CACHE.exists():
        s = np.load(CACHE)
        if s.shape == rk.shape:
            return s.astype(float)
    F = {**features(A, rk), **words(A, rk)}
    keys = NAMES + DAY + tuple(WORDS)
    di = {str(d): i for i, d in enumerate(A['days'])}
    rows = []
    for t, j, a, z in base.located(A, base.trades()):
        if t.side == 'long' and t.dated and t.entry_date >= '2024-01-02' and t.entry_date in di and rk[di[t.entry_date], j] < K:
            d = di[t.entry_date]
            names = np.flatnonzero(rk[d] < K)
            rows.append((t.entry_date, day_matrix(F, keys, names, d), int(np.flatnonzero(names == j)[0])))
    s = np.full(rk.shape, np.nan, dtype=np.float32)
    days = [str(d) for d in A['days']]
    for a, z in FOLDS:
        w = fit([(X, y) for dt, X, y in rows if not a <= dt <= z], len(keys), 3.0)
        for d, day in enumerate(days):
            if a <= day <= z:
                names = np.flatnonzero(rk[d] < K)
                if len(names) >= 10:
                    s[d, names] = day_matrix(F, keys, names, d) @ w
        print('fold', a, flush=True)
    np.save(CACHE, s)
    return s.astype(float)


def book(A, s, n, strong):
    h, l, c = (A[k].astype(float) for k in ('high', 'low', 'close'))
    out = [[] for _ in range(len(c))]
    for d in range(1, len(c)):
        v = np.nan_to_num(s[d], nan=-1e9)
        if strong:
            v = np.where((c[d] > h[d - 1]) & ((c[d] - l[d]) >= .5 * (h[d] - l[d])), v, -1e9)
        for j in np.argsort(-v)[:n]:
            j = int(j)
            if v[j] > -1e8:
                out[d].append(((1.0, float(-v[j])), j, 1, float(c[d, j]), float(min(max(l[d, j], c[d, j] * .95), c[d, j] * .99)), 'list'))
    return out


def main():
    W, cfg = SY.get('martin_luk').load()
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    reg, rules, mask, pool = W.build(A, cfg)
    rk = T4.ranks(A, pool)
    s = scores(A, base, rk)
    his = [x for x in base.located(A, base.trades()) if x[0].side == 'long' and x[0].dated and x[0].entry_date >= '2024-01-02']
    shorts = [[((0.0,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:]) for e in lst if e[2] <= 0] for lst in reg]
    show = lambda k, r: print(k, {y: round(v, 2) for y, v in r['by_year'].items()}, f"dd {r['maxdd']:.2f} n/y {r['per_year']:.0f} win {r['win']:.3f} aw {r['avg_win']:+.3f} al {r['avg_loss']:+.3f} dw {r['days_win']:.1f} strict {r['strict']}/{r['of']} 2026 {r['strict26']}/{r['of26']} {r['placebo'] or ''}", flush=True)
    res = {}
    for k, (strong, n, pos, risk) in CANDS.items():
        e = [a + b for a, b in zip(book(A, s, n, strong), shorts)]
        ru = replace(rules, trail='e9', max_new_long=n, max_new_by_kind={}, max_position=pos, risk=risk, risk_low=risk / 2, risk_high=0.0)
        st, tr = base.run(A, e, WINDOW, pool, ru, placebo=0, audit=True)
        r = res[k] = report(base, A, st, tr, his)
        show(k, r)
        y = r['by_year']
        if r['strict'] >= 16 and r['strict26'] >= .4 * r['of26'] and y['2024'] > 0 and y['2025'] > 0 and r['win'] <= .35 and r['per_year'] >= 200:
            st, tr = base.run(A, e, WINDOW, pool, ru, placebo=100, audit=True)
            r = res[k] = report(base, A, st, tr, his)
            show(k + ' placebo', r)
        RV.write('martin_m2.json', res)


if __name__ == '__main__':
    main()
