"""Martin's own list: 9 > 21 > 50 EMA, the names that just upgraded into it, and the several names of a move rising
together.  Recall of his dated longs at t-1, selection 2024-25, validation 2026.  Market data only.

    $PY -m studies.trader_replication.martin_list
"""
from __future__ import annotations

import numpy as np

from . import review as RV, systems as SY, watchlist as WL


def ema(c, n):
    out = np.full(c.shape, np.nan)
    a = 2 / (n + 1)
    prev = np.full(c.shape[1], np.nan)
    for i in range(len(c)):
        x = c[i]
        prev = np.where(np.isfinite(prev), np.where(np.isfinite(x), a * x + (1 - a) * prev, prev), x)
        out[i] = prev
    return out


def main():
    W, cfg = SY.get('martin_luk').load()
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    e, rules, mask, pool = W.build(A, cfg)
    if getattr(pool, 'shape', None) != A['close'].shape:
        pool = np.isfinite(A['close'])
    c = A['close'].astype(float)
    e9, e21, e50 = ema(c, 9), ema(c, 21), ema(c, 50)
    stack = (e9 > e21) & (e21 > e50) & (c > e21)
    fresh = {n: stack & ~np.vstack([np.zeros((n, c.shape[1]), bool), stack[:-n]]) for n in (5, 10, 20)}
    m = WL.measures(A)
    prior = np.vstack([np.zeros((1, pool.shape[1]), bool), pool[:-1]])
    lag = lambda x: np.vstack([np.zeros((1, x.shape[1]), x.dtype), x[:-1]])
    dr = np.vstack([np.full((1, c.shape[1]), np.nan), m['dollar_range'][:-1]])
    days = A['days'].astype(str)
    di = {d: i for i, d in enumerate(days)}
    his = [(t, j) for t, j, a, z in base.located(A, base.trades()) if t.side == 'long' and t.dated and t.entry_date >= '2024-01-02' and t.entry_date in di]
    gates = dict(all=np.ones(c.shape, bool), stack=lag(stack), fresh5=lag(fresh[5]), fresh10=lag(fresh[10]), fresh20=lag(fresh[20]))
    out = {}
    for name, g in gates.items():
        v = np.where(prior & g, dr, np.nan)
        for part, rows in (('selection', [x for x in his if x[0].entry_date <= '2025-12-31']), ('validation', [x for x in his if x[0].entry_date > '2025-12-31'])):
            res = {}
            sizes = []
            for K in (30, 50, 100, 10 ** 6):
                hit = []
                for t, j in rows:
                    d = di[t.entry_date]
                    row, x = v[d], v[d, j]
                    hit.append(bool(np.isfinite(x) and (row > x).sum() < K))
                res[str(K) if K < 10 ** 6 else 'any'] = round(float(np.mean(hit)), 2)
            size = float(np.median([np.isfinite(v[di[t.entry_date]]).sum() for t, j in rows]))
            out[f'{name}_{part}'] = dict(res, list_size=size, tickets=len(rows))
            print(f'{name:8}{part:11}', res, 'list size', size, flush=True)
    RV.write('martin_list.json', out)


if __name__ == '__main__':
    main()
