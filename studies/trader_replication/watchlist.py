"""Is his ticket already on a list built from market data the evening before?  Every measure is computed at t-1 over the
system's own pool and ranked; recall@K is the share of his dated longs inside the top K, against K / pool for a random
list.  Selection and validation parts of his ledger; reports/gap_review/watch_<id>.json

    $PY -m studies.trader_replication.watchlist <id> <selection end ISO>
"""
from __future__ import annotations

import sys

import numpy as np

from . import review as RV, systems as SY

KS = (20, 30, 50, 100)


def roll_mean(x, n):
    ok = np.isfinite(x)
    a = np.cumsum(np.where(ok, x, 0.0), axis=0)
    c = np.cumsum(ok, axis=0)
    out = np.full(x.shape, np.nan)
    s = a[n:] - a[:-n]
    k = c[n:] - c[:-n]
    with np.errstate(all='ignore'):
        out[n:] = np.where(k >= n * .75, s / k, np.nan)
    return out


def measures(A):
    c, h, l, t = (A[k].astype(float) for k in ('close', 'high', 'low', 'turnover'))
    with np.errstate(all='ignore'):
        rng = roll_mean(h / l - 1, 20)
        to20 = roll_mean(t, 20)
        back = lambda n: np.vstack([np.full((n, c.shape[1]), np.nan), c[n:] / c[:-n] - 1])
        up_day = np.vstack([np.zeros((1, c.shape[1])), (c[1:] / c[:-1] - 1 > rng[1:]) & (t[1:] > 1.5 * to20[1:])]).astype(float)
        m = dict(dollar_range=np.log(to20 * rng), turnover20=np.log(to20), adr=rng, gain5=back(5), gain20=back(20), gain60=back(60),
                 gain120=back(120), range5=roll_mean(h / l - 1, 5) / rng, rvol5=roll_mean(t, 5) / to20,
                 big10=roll_mean(up_day, 10), from_hi=c / np.fmax.accumulate(c, axis=0))
    return m


def pct(x, pool):
    """Within-row percentile among the pool (1 = best); NaN outside it."""
    v = np.where(pool, x, np.nan)
    o = np.argsort(np.argsort(np.where(np.isfinite(v), v, -np.inf), axis=1), axis=1).astype(float)
    n = np.isfinite(v).sum(1, keepdims=True)
    out = (o - (v.shape[1] - n)) / np.maximum(n - 1, 1)
    return np.where(np.isfinite(v), out, np.nan)


def main(id_, cut):
    W, cfg = SY.get(id_).load()
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    entries, rules, mask, pool = W.build(A, cfg)
    if getattr(pool, 'shape', None) != A['close'].shape:
        pool = np.isfinite(A['close'])
    prior = np.vstack([np.zeros((1, pool.shape[1]), bool), pool[:-1]])
    m = measures(A)
    p = {k: pct(np.vstack([np.full((1, v.shape[1]), np.nan), v[:-1]]), prior) for k, v in m.items()}
    p['dr_g20'] = np.nanmean([p['dollar_range'], p['gain20']], axis=0)
    p['dr_g60'] = np.nanmean([p['dollar_range'], p['gain60']], axis=0)
    p['dr_g20_big'] = np.nanmean([p['dollar_range'], p['gain20'], p['big10']], axis=0)
    p['dr_g5_g20_g60'] = np.nanmean([p['dollar_range'], p['gain5'], p['gain20'], p['gain60']], axis=0)
    days = A['days'].astype(str)
    his = [(t, j, a) for t, j, a, z in base.located(A, base.trades()) if t.side == 'long' and t.entry_date >= '2024-01-02' and t.dated]
    di = {d: i for i, d in enumerate(days)}
    out = dict(id=id_, cut=cut, parts={})
    size = np.isfinite(p['dollar_range']).sum(1)
    for part, rows in (('selection', [x for x in his if x[0].entry_date <= cut]), ('validation', [x for x in his if x[0].entry_date > cut])):
        res = {}
        for k, v in p.items():
            hit = {K: [] for K in KS}
            for t, j, a in rows:
                d = di.get(t.entry_date)
                if d is None:
                    continue
                row = v[d]
                x = row[j]
                for K in KS:
                    hit[K].append(bool(np.isfinite(x) and (row > x).sum() < K))
            res[k] = {str(K): float(np.mean(h)) if h else None for K, h in hit.items()}
        ds = [di[x[0].entry_date] for x in rows if x[0].entry_date in di]
        pool_n = float(np.median(size[ds])) if ds else None
        out['parts'][part] = dict(tickets=len(ds), pool=pool_n, recall=res)
        print(part, 'tickets', len(ds), 'pool', pool_n, 'random@30', round(30 / pool_n, 3) if pool_n else None)
        for k, r in sorted(res.items(), key=lambda kv: -(kv[1]['30'] or 0))[:9]:
            print(f"  {k:15}", {a: round(b, 2) for a, b in r.items()})
    RV.write(f'watch_{id_}.json', out)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
