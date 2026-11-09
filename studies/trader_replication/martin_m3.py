"""M3, a diagnosis on the hourly list: the close of a strong day against his dip-and-reclaim with the stop at the low so far.
studies/martin_luk/notes/PREREG_M3.md

    $PY -m studies.trader_replication.martin_m3
"""
from dataclasses import replace

import numpy as np

from studies import trader_data as TD

from . import panels, review as RV, systems as SY, ticket_t4 as T4
from .martin_m1 import report


def book(A, rk, mode):
    h = TD.load_hourly('us', mode='frozen')
    hc = {str(c): i for i, c in enumerate(h['codes'])}
    idx = {}
    for i, d in enumerate(h['days'].astype(str)):
        idx.setdefault(d, []).append(i)
    codes = [str(c) for c in A['codes']]
    cols = {j: hc[c] for j, c in enumerate(codes) if c in hc}
    C, H, L = (A[k].astype(float) for k in ('close', 'high', 'low'))
    out = [[] for _ in A['days']]
    for d in range(2, len(C)):
        day = str(A['days'][d])
        if day < '2023-12-01' or day not in idx:
            continue
        bars = np.array(idx[day])
        for j, k in cols.items():
            if rk[d, j] >= 100:
                continue
            if mode == 'close':
                if C[d, j] > H[d - 1, j] and C[d, j] - L[d, j] >= .5 * (H[d, j] - L[d, j]):
                    out[d].append(((-float(rk[d, j]),), j, 1, float(C[d, j]), float(min(max(L[d, j], C[d, j] * .95), C[d, j] * .99)), 'his'))
                continue
            o, hi, lo, cl = (h[x][bars, k].astype(float) for x in ('open', 'high', 'low', 'close'))
            fin = np.isfinite(hi) & np.isfinite(cl)
            if fin.sum() < 3:
                continue
            o, hi, lo, cl = o[fin], hi[fin], lo[fin], cl[fin]
            s = C[d, j] / cl[-1]
            o, hi, lo, cl = o * s, hi * s, lo * s, cl * s
            dipped = False
            for t in range(1, len(cl) - 1):
                dipped = dipped or lo[t] < (lo[0] if mode == 'undercut' else o[0]) or (mode == 'dip' and lo[0] < o[0])
                if dipped and cl[t] > hi[t - 1]:
                    low = lo[:t + 1].min()
                    w = 1 - low / cl[t]
                    if .01 <= w <= .03:
                        e = ((-float(rk[d, j]),), j, 1, float(cl[t]), float(low), 'his')
                        out[d].append(e + ((float(low),) if (lo[t + 1:] <= low).any() else ()))
                    break
    return out


def main():
    W, cfg = SY.get('martin_luk').load()
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    _, rules, mask, pool = W.build(A, cfg)
    rk = T4.ranks(A, pool)
    his = [x for x in base.located(A, base.trades()) if x[0].side == 'long' and x[0].dated and x[0].entry_date >= '2024-01-02']
    res = {}
    for k, m in (('CLOSE', 'close'), ('M3A', 'undercut'), ('M3B', 'dip')):
        e = [sorted(x, key=lambda v: v[0])[:8] for x in book(A, rk, m)]
        ru = replace(rules, max_new_long=8, max_new_by_kind={}, max_position=.17, intraday_kinds=('his',) if m != 'close' else ())
        st, tr = base.run(A, e, panels.WINDOW, pool, ru, placebo=0, audit=True)
        r = res[k] = report(base, A, st, tr, his)
        r['E'] = r['win'] * r['avg_win'] + (1 - r['win']) * r['avg_loss']
        print(k, {y: round(v, 2) for y, v in r['by_year'].items()}, f"dd {r['maxdd']:.2f} n/y {r['per_year']:.0f} win {r['win']:.3f} aw {r['avg_win']:+.3f} al {r['avg_loss']:+.3f} E {r['E']*100:+.2f}% dw {r['days_win']:.1f} strict {r['strict']}/{r['of']} 2026 {r['strict26']}/{r['of26']}", flush=True)
        RV.write('martin_m3.json', res)


if __name__ == '__main__':
    main()
