"""Why his name and not the other names of the evening list?  Only what happened in the weeks before the buy day, read at
t-1, against the rest of that day's list.  Selection and validation parts of his ledger, then the score built on selection
measured on validation: how often his name lands in the top n of the list.  reports/gap_review/pick_<id>.json

    $PY -m studies.trader_replication.pick_map <id> <selection end>
"""
from __future__ import annotations

import sys

import numpy as np

from . import review as RV, systems as SY, ticket_t4 as T4, watchlist as WL

K = 100


def panel(A, rk):
    c, h, l, v = (A[k].astype(float) for k in ('close', 'high', 'low', 'turnover'))
    with np.errstate(all='ignore'):
        r = np.vstack([np.full((1, c.shape[1]), np.nan), c[1:] / c[:-1] - 1])
        rng = WL.roll_mean(h / l - 1, 20)
        to20 = WL.roll_mean(v, 20)
        up, dn = np.where(r > 0, v, 0.0), np.where(r < 0, v, 0.0)
        ma21 = WL.roll_mean(c, 21)
        ma50 = WL.roll_mean(c, 50)
        back = lambda n: np.vstack([np.full((n, c.shape[1]), np.nan), c[n:] / c[:-n] - 1])
        hi60 = np.full(c.shape, np.nan)
        for i in range(60, len(c)):
            hi60[i] = np.nanmax(c[i - 59:i + 1], axis=0)
        mkt = np.nanmedian(np.where(rk < 300, r, np.nan), axis=1, keepdims=True)
        big = (r > rng) & (v > 1.5 * to20)
        m = dict(g20=back(20), g60=back(60), g120=back(120), acc20=WL.roll_mean(up, 20) / WL.roll_mean(dn, 20), acc60=WL.roll_mean(up, 60) / WL.roll_mean(dn, 60),
                 big20=WL.roll_mean(big.astype(float), 20), big60=WL.roll_mean(big.astype(float), 60), above21=WL.roll_mean((c > ma21).astype(float), 40), above50=WL.roll_mean((c > ma50).astype(float), 60),
                 from_hi=c / hi60 - 1, tight5=WL.roll_mean(h / l - 1, 5) / rng, dry5=WL.roll_mean(v, 5) / to20, money5=WL.roll_mean(v, 5) / WL.roll_mean(v, 60), money20=to20 / WL.roll_mean(v, 120),
                 rs20=WL.roll_mean(r - mkt, 20), rs60=WL.roll_mean(r - mkt, 60), stay=WL.roll_mean((rk < K).astype(float), 60), stay20=WL.roll_mean((rk < K).astype(float), 20),
                 climb=-(rk.astype(float) - np.vstack([np.full((20, c.shape[1]), np.nan), rk[:-20].astype(float)])), adr=rng, low_vol=-WL.roll_mean(np.abs(r), 60) / rng)
    return m, r


PICKED = dict(martin_luk=dict(g20=1, g120=1, rs20=1, stay20=-1, adr=1, low_vol=1),
              christian_flanders=dict(g20=1, g60=1, g120=1, acc20=1, acc60=1, big20=-1, big60=-1, above21=1, above50=1, from_hi=1, dry5=1, rs20=1, rs60=1, stay=-1, stay20=-1, adr=1))


def pick_rank(A, rk, who):
    """Place of each list name by his score, read at t-1; 10 ** 6 off the list."""
    m, _ = panel(A, rk)
    out = np.full(rk.shape, 10 ** 6)
    for d in range(1, len(rk)):
        names = np.flatnonzero(rk[d] < K)
        if len(names) < 10:
            continue
        s = np.zeros(len(names))
        for k, sign in PICKED[who].items():
            v = m[k][d - 1, names]
            ok = np.isfinite(v)
            q = np.full(len(v), .5)
            if ok.any():
                q[ok] = (v[ok][:, None] > v[ok]).mean(1)
            s += sign * (q - .5)
        out[d, names[np.argsort(np.argsort(-s))]] = np.arange(len(names))
    return out


def main(id_, cut):
    W, cfg = SY.get(id_).load()
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    e, rules, mask, pool = W.build(A, cfg)
    rk = T4.ranks(A, pool)
    m, ret = panel(A, rk)
    di = {str(d): i for i, d in enumerate(A['days'])}
    his = [(t, j) for t, j, a, z in base.located(A, base.trades()) if t.side == 'long' and t.dated and t.entry_date >= '2024-01-02' and t.entry_date in di]
    parts = dict(selection=[x for x in his if x[0].entry_date <= cut], validation=[x for x in his if x[0].entry_date > cut])
    keys = list(m)
    out, use = {}, {}
    for part, rows in parts.items():
        pct = {k: [] for k in keys}
        n = 0
        for t, j in rows:
            d = di[t.entry_date]
            names = np.flatnonzero(rk[d] < K)
            if rk[d, j] >= K:
                continue
            n += 1
            for k in keys:
                v, x = m[k][d - 1, names], m[k][d - 1, j]
                v = v[np.isfinite(v)]
                if np.isfinite(x) and len(v) > 10:
                    pct[k].append(float((v < x).mean()))
        res = {k: round(float(np.mean(v)), 3) for k, v in pct.items() if v}
        out[part] = dict(tickets=n, mean_pct=res)
        print(part, 'in list', n, sorted(res.items(), key=lambda kv: -abs(kv[1] - .5))[:10], flush=True)
    sel, val = out['selection']['mean_pct'], out['validation']['mean_pct']
    picked = {k: (1 if sel[k] > .5 else -1) for k in sel if abs(sel[k] - .5) >= .08}
    print('picked on selection', picked, 'same side on validation', {k: val.get(k) for k in picked})
    for part, rows in parts.items():
        hits = {4: [], 10: [], 20: []}
        for t, j in rows:
            d = di[t.entry_date]
            if rk[d, j] >= K:
                continue
            names = np.flatnonzero(rk[d] < K)
            s = np.zeros(len(names))
            for k, sign in picked.items():
                v = m[k][d - 1, names]
                ok = np.isfinite(v)
                q = np.full(len(v), .5)
                if ok.any():
                    q[ok] = (v[ok][:, None] > v[ok]).mean(1)
                s += sign * (q - .5)
            at = int(np.flatnonzero(names == j)[0])
            place = int((s > s[at]).sum())
            for a in hits:
                hits[a].append(place < a)
        print(part, 'score top-n hit', {a: round(float(np.mean(b)), 2) for a, b in hits.items()}, 'random', {a: a / K for a in hits}, flush=True)
    RV.write(f'pick_{id_}.json', dict(out, picked=picked))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
