"""From any day of a holding, what do the daily bars say about what comes next?  Only the future return counts: a stock's
gain so far is an input, never part of the answer.  Selection 2024-25, validation 2026.  Diagnosis only.

    $PY -m studies.trader_replication.hold_forward
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np

from . import panels, review as RV, systems as SY, ticket_flanders as F, ticket_t4 as T4

WINDOW = panels.WINDOW
FWD, STEP = 20, 5


def rows(A, tr, di, cj):
    out = []
    for t in tr:
        d0, j = di[t['entry']], cj[t['code']]
        c, h, l, v = (A[k][:, j].astype(float) for k in ('close', 'high', 'low', 'turnover'))
        f, r0 = t['fill'], abs(t['fill'] - t['stop'])
        rng = np.nanmean((h / l - 1)[max(0, d0 - 20):d0])
        base = np.nanmean(v[max(0, d0 - 20):d0])
        for k in (1, 2, 3, *range(5, 61, STEP)):
            e = d0 + k
            if e + FWD >= len(c) or k > t['days']:
                break
            cc, past = c[e], c[d0:e + 1]
            ups = np.diff(c[d0:e + 1]) > 0
            vv = v[d0 + 1:e + 1]
            ema = np.nanmean(c[e - 20:e + 1])
            out.append(dict(entry=t['entry'], days=k, r=(cc - f) / r0 if r0 > 0 else np.nan, gain=cc / f - 1, from_peak=cc / np.nanmax(past) - 1,
                            above=(cc / ema - 1) / rng if rng > 0 else np.nan, up_share=float(ups.mean()), vol_up=np.nansum(vv[ups]) / max(np.nansum(vv), 1.0),
                            vol=np.nanmean(vv[-5:]) / base if base > 0 else np.nan, fwd=c[e + FWD] / cc - 1,
                            fwd_max=np.nanmax(h[e + 1:e + FWD + 1]) / cc - 1, fwd_min=np.nanmin(l[e + 1:e + FWD + 1]) / cc - 1))
    return out


def show(p, key, q=(0, .2, .4, .6, .8, 1)):
    v = np.array([x[key] for x in p], float)
    edges = np.nanquantile(v, q)
    edges[-1] += 1e-9
    res = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        s = [x for x, y in zip(p, v) if lo <= y < hi]
        if s:
            f = np.array([x['fwd'] for x in s], float)
            res.append((round(float(lo), 2), len(s), f'{np.nanmean(f) * 100:+.1f}%', f'big {np.nanmean(f >= .3):.2f}', f'bad {np.nanmean(f <= -.15):.2f}'))
    print(f'  {key:10}', res, flush=True)
    return [list(map(str, r)) for r in res]


def main():
    W, cfg = SY.get('christian_flanders').load()
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    e, rules, mask, pool = W.build(A, {**cfg, **F.ALL, 'rule_opts': {**cfg.get('rule_opts', {}), 'trail': 'ema21'}})
    rk = T4.ranks(A, pool)
    e = [[x for x in lst if x[2] > 0] for lst in F.keep(e, rk, 50, True)]
    alone = replace(rules, max_open=0, max_new_long=0, max_new_by_kind={}, max_gross=1e9, max_position=.02, risk=.002, feedback=0, risk_scale='', margin_rate=0.0, trims=(), trim_frac=0.0, trim_day=0)
    st, tr = base.run(A, e, WINDOW, pool, alone, placebo=0, audit=True)
    st.pop('_curve', None)
    di = {str(d): i for i, d in enumerate(A['days'])}
    cj = {str(c): j for j, c in enumerate(A['codes'])}
    all_rows = rows(A, tr, di, cj)
    out = {}
    for part, p in (('selection', [x for x in all_rows if x['entry'] <= '2025-12-31']), ('validation', [x for x in all_rows if x['entry'] >= '2026-01-01'])):
        f = np.array([x['fwd'] for x in p], float)
        print(part, 'states', len(p), 'mean fwd', round(float(np.nanmean(f)) * 100, 2), '%', 'big', round(float(np.nanmean(f >= .3)), 3))
        out[part] = {k: show(p, k) for k in ('gain', 'r', 'days', 'from_peak', 'above', 'up_share', 'vol_up', 'vol')}
    RV.write('hold_forward_flanders.json', out)


if __name__ == '__main__':
    main()
