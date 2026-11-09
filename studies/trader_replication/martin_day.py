"""Inside the evening list, what does Martin's name look like on the day he buys, compared with the rest of the list?
Close of that day and earlier only.  Selection 2024-25, validation 2026.  Also the next 10 days of every list name in the
same state, so a look that is only famous does not pass as an edge.

    $PY -m studies.trader_replication.martin_day
"""
from __future__ import annotations

import numpy as np

from . import review as RV, systems as SY, ticket_t4 as T4
from .martin_list import ema

K = 100


def state(A, e9, e21, e50, d, j):
    c, h, l, o, v = (A[k][:, j].astype(float) for k in ('close', 'high', 'low', 'open', 'turnover'))
    if d < 25 or not np.isfinite(c[d]) or c[d] <= 0 or not np.isfinite(c[d - 1]):
        return None
    adr = np.nanmean((h / l - 1)[d - 20:d])
    if not adr > 0:
        return None
    hi20 = np.nanmax(h[d - 20:d])
    base = np.nanmean(v[d - 20:d])
    day = h[d] - l[d]
    return dict(depth=(c[d] / hi20 - 1) / adr, to_e9=(c[d] / e9[d, j] - 1) / adr, to_e21=(c[d] / e21[d, j] - 1) / adr, to_e50=(c[d] / e50[d, j] - 1) / adr,
                touch_e9=(l[d] / e9[d, j] - 1) / adr, touch_e21=(l[d] / e21[d, j] - 1) / adr, gain=(c[d] / c[d - 1] - 1) / adr,
                close_pos=(c[d] - l[d]) / day if day > 0 else np.nan, over_pdh=(c[d] / h[d - 1] - 1) / adr, gap=(o[d] / c[d - 1] - 1) / adr,
                vol=v[d] / base if base > 0 else np.nan, dry3=np.nanmean(v[d - 3:d]) / base if base > 0 else np.nan,
                range3=np.nanmean((h / l - 1)[d - 3:d]) / adr, down3=c[d - 1] / c[d - 4] - 1 if d > 4 else np.nan,
                prior_range=(h[d - 1] / l[d - 1] - 1) / adr, trend20=c[d] / c[d - 20] - 1, up_stack=float(e9[d, j] > e21[d, j] > e50[d, j]))


def main():
    W, cfg = SY.get('martin_luk').load()
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    e, rules, mask, pool = W.build(A, cfg)
    rk = T4.ranks(A, pool)
    c = A['close'].astype(float)
    e9, e21, e50 = ema(c, 9), ema(c, 21), ema(c, 50)
    di = {str(d): i for i, d in enumerate(A['days'])}
    his = [(t, j) for t, j, a, z in base.located(A, base.trades()) if t.side == 'long' and t.dated and t.entry_date >= '2024-01-02' and t.entry_date in di]
    out = {}
    for part, rows in (('selection', [x for x in his if x[0].entry_date <= '2025-12-31']), ('validation', [x for x in his if x[0].entry_date > '2025-12-31'])):
        pct, kept = {}, 0
        for t, j in rows:
            d = di[t.entry_date]
            if rk[d, j] >= K:
                continue
            names = np.flatnonzero(rk[d] < K)
            f = {n: state(A, e9, e21, e50, d, int(n)) for n in names}
            me = state(A, e9, e21, e50, d, j)
            if not me:
                continue
            kept += 1
            for k, x in me.items():
                v = np.array([g[k] for g in f.values() if g], float)
                v = v[np.isfinite(v)]
                if np.isfinite(x) and len(v) > 5:
                    pct.setdefault(k, []).append(float((v < x).mean()))
        res = {k: (round(float(np.mean(v)), 3), round(float(np.mean(np.array(v) >= .8)), 2), round(float(np.mean(np.array(v) <= .2)), 2)) for k, v in pct.items()}
        out[part] = dict(tickets=kept, feats=res)
        print(part, 'tickets in list', kept)
        for k, v in sorted(res.items(), key=lambda kv: -abs(kv[1][0] - .5))[:12]:
            print(f'  {k:11} mean pct {v[0]:.3f}  top fifth {v[1]:.2f}  bottom fifth {v[2]:.2f}')
    RV.write('martin_day.json', out)


if __name__ == '__main__':
    main()
