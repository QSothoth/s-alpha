"""Historical M1: the fold-held-out model trains on later tickets and is not a causal backtest or live score.

It buys a resting support limit; see studies/martin_luk/notes/PREREG_M1.md for the timing correction.

    $PY -m studies.trader_replication.martin_m1
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

import numpy as np

from . import panels, review as RV, systems as SY, ticket_t4 as T4, watchlist as WL
from .martin_list import ema
from .martin_words import FOLDS, WORDS, words
from .pick_model import K, NAMES, day_matrix, features, fit

WINDOW = panels.WINDOW
CACHE = Path(__file__).resolve().parents[2] / 'data' / 'martin-luk-cache' / 'm1_score.npy'
CANDS = dict(M1A=(20, 'e9', 4, 'e9'), M1B=(20, 'near', 4, 'e9'), M1C=(20, 'near', 8, 'e9'), M1D=(40, 'near', 8, 'e9'), M1E=(20, 'near', 8, None))


def scores(A, base, rk):
    """Historical only: weights include later folds; the shape-only cache has no provenance proof."""
    if CACHE.exists():
        s = np.load(CACHE)
        if s.shape == rk.shape:
            return s.astype(float)
    F = {**features(A, rk), **words(A, rk)}
    keys = NAMES + tuple(WORDS)
    di = {str(d): i for i, d in enumerate(A['days'])}
    his = [(t, j) for t, j, a, z in base.located(A, base.trades()) if t.side == 'long' and t.dated and t.entry_date >= '2024-01-02' and t.entry_date in di]
    rows = []
    for t, j in his:
        d = di[t.entry_date]
        if rk[d, j] < K:
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
    CACHE.parent.mkdir(exist_ok=True)
    np.save(CACHE, s)
    return s.astype(float)


def book(A, s, n, level, gate):
    o, h, l, c = (A[k].astype(float) for k in ('open', 'high', 'low', 'close'))
    e9, e21 = ema(c, 9), ema(c, 21)
    rng = WL.roll_mean(h / l - 1, 20)
    out = [[] for _ in range(len(c))]
    for d in range(1, len(c)):
        if gate is not None and not gate[d - 1]:
            continue
        v = np.nan_to_num(s[d], nan=-1e9)
        for j in np.argsort(-v)[:n]:
            j = int(j)
            if v[j] <= -1e8 or not np.isfinite(l[d, j]):
                continue
            pc = c[d - 1, j]
            lv = [e9[d - 1, j]] if level == 'e9' else [e9[d - 1, j], e21[d - 1, j], h[d - 2, j]]
            lv = [x for x in lv if np.isfinite(x) and x < pc]
            if not lv:
                continue
            L = float(max(lv))
            if not (o[d, j] >= L and l[d, j] <= L):
                continue
            a = rng[d - 1, j]
            w = max(.01, min(.03, a / 2 if np.isfinite(a) else .03))
            stop = L * (1 - w)
            e = ((float(-v[j]),), j, 1, L, float(stop), 'list')
            out[d].append(e + ((float(stop),) if l[d, j] <= stop else ()))
    return out


def report(base, A, st, tr, his):
    st.pop('_curve', None)
    b = st['behaviour']
    o = {(t['code'], t['entry']) for t in tr if t['side'] > 0}
    got = lambda rows: sum(any((str(A['codes'][j]), str(A['days'][d])) in o for d in range(a, z + 1)) for t, j, a, z in rows)
    held = {}
    sel = [x for x in his if x[0].entry_date <= '2025-12-31']
    val = [x for x in his if x[0].entry_date > '2025-12-31']
    return dict(by_year=st['by_year'], maxdd=st['maxdd'], per_year=b['per_year'], win=b['win'], avg_win=b['avg_win'], avg_loss=b['avg_loss'], days_win=b['days_win'], strict=got(sel), of=len(sel), strict26=got(val), of26=len(val), placebo=st.get('placebo'))


def main():
    W, cfg = SY.get('martin_luk').load()
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    reg, rules, mask, pool = W.build(A, cfg)
    rk = T4.ranks(A, pool)
    s = scores(A, base, rk)
    gate = base.market_gate(A, cfg)
    his = [x for x in base.located(A, base.trades()) if x[0].side == 'long' and x[0].dated and x[0].entry_date >= '2024-01-02']
    shorts = [[((0.0,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:]) for e in lst if e[2] <= 0] for lst in reg]
    print('rules', rules.trail, rules.risk, rules.max_position, rules.max_gross, rules.max_new_long, flush=True)
    res = {}
    st, tr = base.run(A, reg, WINDOW, pool, rules, placebo=0, audit=True)
    res['REG'] = report(base, A, st, tr, his)
    show = lambda k, r: print(k, {y: round(v, 2) for y, v in r['by_year'].items()}, f"dd {r['maxdd']:.2f} n/y {r['per_year']:.0f} win {r['win']:.3f} aw {r['avg_win']:+.3f} al {r['avg_loss']:+.3f} dw {r['days_win']:.1f} strict {r['strict']}/{r['of']} 2026 {r['strict26']}/{r['of26']} {r['placebo'] or ''}", flush=True)
    show('REG', res['REG'])
    for k, (n, lv, per, trail) in CANDS.items():
        ent = book(A, s, n, lv, gate)
        e = [[((1.0,) + x[0],) + tuple(x[1:]) for x in a] + b for a, b in zip(ent, shorts)]
        ru = replace(rules, max_new_long=per, max_new_by_kind={}, max_position=.25, max_gross=2.8, intraday_kinds=tuple(rules.intraday_kinds) + ('list',))
        if trail:
            ru = replace(ru, trail=trail)
        st, tr = base.run(A, e, WINDOW, pool, ru, placebo=0, audit=True)
        r = res[k] = report(base, A, st, tr, his)
        show(k, r)
        y = r['by_year']
        ok = r['strict'] >= 16 and r['strict26'] >= .4 * r['of26'] and y['2024'] > 0 and y['2025'] > 0 and r['win'] <= .35 and r['per_year'] >= 200
        if ok:
            st, tr = base.run(A, e, WINDOW, pool, ru, placebo=100, audit=True)
            r = res[k] = report(base, A, st, tr, his)
            show(k + ' placebo', r)
        RV.write('martin_m1.json', res)


if __name__ == '__main__':
    main()
