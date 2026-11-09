"""Which price and volume measures, known at the close of the signal day, tell his ticket from the day's other signals?
Measured inside the system's own day lists, per trader, on a selection and a validation part of his ledger.  Only market
data: no themes, no names.  reports/gap_review/lift_<id>.json

    $PY -m studies.trader_replication.signal_lift <id> <selection end ISO>
"""
from __future__ import annotations

import sys

import numpy as np

from . import review as RV, systems as SY


def feats(A, d, j, n_seen):
    """Everything here reads bars up to and including d."""
    a = max(0, d - 260)
    c, h, l, t = (A[k][a:d + 1, j].astype(float) for k in ('close', 'high', 'low', 'turnover'))
    o = A['open'][a:d + 1, j].astype(float)
    ok = np.isfinite(c)
    c, h, l, t, o = c[ok], h[ok], l[ok], t[ok], o[ok]
    if len(c) < 25 or c[-1] <= 0:
        return None
    r = np.r_[np.nan, c[1:] / c[:-1] - 1]
    rng = h / l - 1
    adr20 = np.nanmean(rng[-21:-1])
    to20 = np.nanmean(t[-21:-1])
    up = r[-20:] > 0
    gain = lambda k: c[-1] / c[-1 - k] - 1 if len(c) > k else np.nan
    bigup = np.nansum((r[-20:] > adr20) & (t[-20:] > 1.5 * to20))
    hi = np.nanmax(h[:-1]) if len(h) > 1 else np.nan
    return dict(
        rvol=t[-1] / to20 if to20 > 0 else np.nan, gain1=r[-1], gain1_adr=r[-1] / adr20 if adr20 > 0 else np.nan,
        gap=o[-1] / c[-2] - 1, gain5=gain(5), gain20=gain(20), gain60=gain(60), gain120=gain(120),
        close_pos=(c[-1] - l[-1]) / (h[-1] - l[-1]) if h[-1] > l[-1] else np.nan,
        turnover20=np.log(to20) if to20 > 0 else np.nan, dollar_range=np.log(to20 * adr20) if to20 * adr20 > 0 else np.nan,
        adr=adr20, tight=-np.nanmean(rng[-6:-1]) / adr20 if adr20 > 0 else np.nan,
        updown_vol=np.nansum(t[-20:][up]) / max(np.nansum(t[-20:][~up]), 1.0), bigup=float(bigup),
        to_trend=np.nanmean(t[-6:-1]) / np.nanmean(t[-61:-1]) if len(t) > 61 else np.nan,
        to_year=np.log(t[-1]) - np.log(np.nanmedian(t[-253:-1])) if t[-1] > 0 else np.nan,
        hi_dist=c[-1] / hi - 1 if hi > 0 else np.nan, hi_new=float(c[-1] >= np.nanmax(c[:-1])),
        extension=c[-1] / np.nanmean(c[-21:]) - 1, recur=float(n_seen), accel=gain(20) - gain(60) / 3)


def main(id_, cut):
    W, cfg = SY.get(id_).load()
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    entries, rules, mask, pool = W.build(A, {**cfg, 'max_new': 0})
    days = A['days'].astype(str)
    his = {}
    for t, j, a, z in base.located(A, base.trades()):
        if t.side == 'long' and t.entry_date >= '2024-01-02':
            for d in range(a, z + 1):
                his.setdefault(d, {})[j] = t.outcome
    seen, rows = {}, {}
    for d in range(len(entries)):
        lst = {e[1] for e in entries[d] if e[2] > 0}
        if d in his and lst & set(his[d]):
            rows[d] = {j: feats(A, d, j, sum(1 for x in seen.get(j, []) if d - x <= 20)) for j in lst}
        for j in lst:
            seen.setdefault(j, []).append(d)
    names = None
    out = dict(id=id_, cut=cut, parts={})
    parts = dict(selection=[d for d in rows if days[d] <= cut], validation=[d for d in rows if days[d] > cut])
    for part, ds in parts.items():
        ranks, tops, sizes = {}, {}, []
        n = 0
        for d in ds:
            row = {j: f for j, f in rows[d].items() if f}
            sizes.append(len(row))
            names = names or list(next(iter(row.values())))
            for j in set(row) & set(his[d]):
                n += 1
                for k in names:
                    v = np.array([f[k] for f in row.values()], float)
                    x = row[j][k]
                    if np.isfinite(x) and np.isfinite(v).sum() > 1:
                        ranks.setdefault(k, []).append(float((v[np.isfinite(v)] < x).mean()))
                        tops.setdefault(k, []).append(float((v[np.isfinite(v)] > x).sum() < 4))
        base4 = float(np.mean([min(1, 4 / s) for s in sizes])) if sizes else None
        res = {k: dict(mean_pct=float(np.mean(v)), hi=float(np.mean(tops[k])), lo=float(np.mean(np.array(v) <= np.percentile(v, 0) + 4 / max(np.median(sizes), 1)))) for k, v in ranks.items()}
        out['parts'][part] = dict(tickets=n, days=len(ds), median_signals=float(np.median(sizes)) if sizes else None, top4_random=base4, feats=res)
        print(part, 'tickets', n, 'days', len(ds), 'median signals/day', out['parts'][part]['median_signals'], 'random top4', round(base4 or 0, 3))
        for k, v in sorted(res.items(), key=lambda kv: -abs(kv[1]['mean_pct'] - .5)):
            print(f"  {k:13} pct {v['mean_pct']:.3f} top4 {v['hi']:.2f}")
    RV.write(f'lift_{id_}.json', out)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
