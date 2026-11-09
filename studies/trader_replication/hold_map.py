"""What separates the big winners from the rest a few days after entry?  Every signal is run alone, held on the slow
trail, and bucketed by what its daily bars showed k sessions in.  Selection 2024-25, validation 2026.  Diagnosis only.

    $PY -m studies.trader_replication.hold_map
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np

from . import panels, review as RV, systems as SY, ticket_flanders as F, ticket_t4 as T4

WINDOW = panels.WINDOW
BIG = .30
KS = (1, 2, 3, 5, 10)


def path(A, t, di, cj):
    d, j = di[t['entry']], cj[t['code']]
    f, r = t['fill'], abs(t['fill'] - t['stop'])
    c, h, v = A['close'][:, j].astype(float), A['high'][:, j].astype(float), A['turnover'][:, j].astype(float)
    out = {}
    base = np.nanmean(v[max(0, d - 20):d]) if d else np.nan
    for k in KS:
        e = d + k
        if t['days'] < k or e >= len(c):
            continue
        gain = c[e] / f - 1
        out[k] = dict(gain=gain, r=(c[e] - f) / r if r > 0 else np.nan, new_high=float(c[e] >= np.nanmax(c[max(0, e - 20):e])),
                      vol=np.nanmean(v[d + 1:e + 1]) / base if base > 0 else np.nan, peak=np.nanmax(h[d + 1:e + 1]) / f - 1)
    return out


def table(rows, key, edges, label):
    res = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        p = [x for x in rows if lo <= x[key] < hi]
        if p:
            ret = np.array([x['final'] for x in p])
            res.append(dict(bucket=f'{lo:g}..{hi:g}', n=len(p), big=float((ret >= BIG).mean()), mean=float(ret.mean()), sum=float(ret.sum())))
    print(' ', label, [(r['bucket'], r['n'], f"big {r['big']:.2f}", f"mean {r['mean']:+.3f}", f"sum {r['sum']:+.1f}") for r in res], flush=True)
    return res


def main():
    W, cfg = SY.get('christian_flanders').load()
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    merged = {**cfg, **F.ALL, 'rule_opts': {**cfg.get('rule_opts', {}), 'trail': 'ema21'}}
    e, rules, mask, pool = W.build(A, merged)
    rk = T4.ranks(A, pool)
    e = F.keep(e, rk, 50, True)
    e = [[x for x in lst if x[2] > 0] for lst in e]
    alone = replace(rules, max_open=0, max_new_long=0, max_new_by_kind={}, max_gross=1e9, max_position=.02, risk=.002, feedback=0, risk_scale='',
                    margin_rate=0.0, trims=(), trim_frac=0.0, trim_day=0)
    st, tr = base.run(A, e, WINDOW, pool, alone, placebo=0, audit=True)
    st.pop('_curve', None)
    di = {str(d): i for i, d in enumerate(A['days'])}
    cj = {str(c): j for j, c in enumerate(A['codes'])}
    print('trades', len(tr), 'trail', alone.trail, 'days median', np.median([t['days'] for t in tr]))
    out = {}
    trades = [dict(t, final=t['ret'], path=path(A, t, di, cj)) for t in tr]
    for part, sel in (('selection', [t for t in trades if t['entry'] <= '2025-12-31']), ('validation', [t for t in trades if t['entry'] >= '2026-01-01'])):
        ret = np.array([t['final'] for t in sel])
        print(part, 'n', len(sel), 'big rate', round(float((ret >= BIG).mean()), 3), 'mean', round(float(ret.mean()), 4), 'share of gains from big', round(float(ret[ret >= BIG].sum() / ret[ret > 0].sum()), 2))
        out[part] = {}
        for k in KS:
            rows = [dict(t['path'][k], final=t['final']) for t in sel if k in t['path']]
            print(' day', k, 'alive', len(rows))
            out[part][k] = dict(gain=table(rows, 'gain', [-9, -.03, 0, .03, .07, .15, 99], 'gain'), r=table(rows, 'r', [-99, 0, .5, 1, 2, 4, 999], 'R'),
                                high=table(rows, 'new_high', [0, .5, 2], 'new20high'), vol=table(rows, 'vol', [0, .7, 1, 1.5, 3, 999], 'volume'))
    RV.write('hold_map_flanders.json', out)


if __name__ == '__main__':
    main()
