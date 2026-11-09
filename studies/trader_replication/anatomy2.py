"""His dated longs against our longs on what was known the day before: 20-day turnover, price, ADR, and the rank of
his name's turnover among that day's pool.  Diagnosis only; reports/gap_review/anatomy2.json.

    $PY -m studies.trader_replication.anatomy2 <id> ...
"""
from __future__ import annotations

import gc
import sys

import numpy as np

from . import panels, review as RV, systems as SY

WINDOW = panels.WINDOW


def facts(A, d, j, to20, adr, pool):
    if d < 1:
        return None
    p = A['close'][d - 1, j]
    t = to20[d - 1, j]
    if not (np.isfinite(p) and np.isfinite(t)):
        return None
    row = to20[d - 1][pool[d]] if pool is not None and pool[d].any() else to20[d - 1]
    row = row[np.isfinite(row)]
    return p, t, adr[d - 1, j], float((row < t).mean()) if len(row) else np.nan


def med(rows):
    if not rows:
        return dict(n=0)
    a = np.array(rows, float)
    return dict(n=len(a), price=float(np.nanmedian(a[:, 0])), turnover20=float(np.nanmedian(a[:, 1])),
                adr=float(np.nanmedian(a[:, 2])), pool_rank=float(np.nanmedian(a[:, 3])))


def one(id_, out):
    W, cfg = SY.get(id_).load()
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    entries, rules, mask, pool = W.build(A, cfg)
    _, tr = base.run(A, entries, WINDOW, pool, rules, placebo=0)
    to = A['turnover'].astype(float)
    to20, adr = np.full(to.shape, np.nan), np.full(to.shape, np.nan)
    rng = (A['high'] / A['low'] - 1).astype(float)
    with np.errstate(all='ignore'):
        for i in range(19, len(to)):
            to20[i] = np.nanmean(to[i - 19:i + 1], axis=0)
            adr[i] = np.nanmean(rng[i - 19:i + 1], axis=0)
    di = {str(d): i for i, d in enumerate(A['days'])}
    cj = {str(c): j for j, c in enumerate(A['codes'])}
    pl = pool if getattr(pool, 'shape', None) == to.shape else None
    ours = [facts(A, di[t['entry']], cj[t['code']], to20, adr, pl) for t in tr if t['side'] > 0 and t['entry'] <= '2025-12-31']
    his = [(t, j) for t, j, a, b in base.located(A, base.trades())
           if WINDOW[0] <= t.entry_date <= '2025-12-31' and t.side == 'long' and t.entry_date in di]
    mine = [facts(A, di[t.entry_date], j, to20, adr, pl) for t, j in his]
    r = out[id_] = dict(ours=med([x for x in ours if x]), his=med([x for x in mine if x]))
    print(id_, r, flush=True)
    RV.write('anatomy2.json', out)
    del A
    gc.collect()


if __name__ == '__main__':
    res = {}
    for x in sys.argv[1:]:
        one(x, res)
