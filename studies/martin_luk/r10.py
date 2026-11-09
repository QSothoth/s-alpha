"""R10 (notes/PREREG_R10.md): his selection (S2 on the whole market) gating his L3 rules.

    nice -n 19 /opt/opend-us-options/.venv/bin/python -m studies.martin_luk.r10
"""
from __future__ import annotations

from dataclasses import replace
import json

import numpy as np

from . import intraday as I, luk, selection as S


def allow_for(P, b, s2):
    """Map the broad (days x codes) selection onto P's (days x syms) grid."""
    di = {d: i for i, d in enumerate(b['days'])}
    ci = {str(c): i for i, c in enumerate(b['codes'])}
    out = np.zeros((len(P['days']), len(P['syms'])), bool)
    rows = [di.get(d, -1) for d in P['days']]
    for j, sym in enumerate(P['syms']):
        k = ci.get('US.' + sym)
        if k is None:
            continue
        for t, r in enumerate(rows):
            if r >= 0:
                out[t, j] = s2[r, k]
    return out


def main():
    b = S.broad()
    base, s1, _ = S.scanners(b)
    c = b['close'].astype(float)
    e9, e21, e50 = luk.ema(c, 9), luk.ema(c, 21), luk.ema(c, 50)
    with np.errstate(invalid='ignore'):
        s2 = s1 & (e9 > e21) & (e21 > e50)
    out = {}
    for which in ('new', 'all'):
        P = I.prepare_r8(which)
        P['_allow'] = allow_for(P, b, s2)
        a, z = I.SEGMENTS['r8']
        for cand in ('L3', 'L4'):
            cfg = replace(I.Cfg(), **I.CANDIDATES[cand])
            curve, dates, tr = I.simulate(P, cfg, a, z)
            st = luk.stats(curve, dates, tr)
            r = np.array([t['r'] for t in tr]) if tr else np.zeros(1)
            res = dict(total=float(st['total']), maxdd=float(st['maxdd']), trades=len(tr), win=float(st['win']),
                       avg_win=float(st['avg_win']), avg_loss=float(st['avg_loss']), exp_r=float(r.mean()),
                       by_year={k: float(v) for k, v in st['by_year'].items()},
                       selected_name_days=int(P['_allow'][(P['days'] >= a) & (P['days'] <= z)].sum()))
            if which == 'new' and cand == 'L3':
                boots = np.random.default_rng(0).choice(r, (2000, len(r))).mean(axis=1)
                rng = np.random.default_rng(1)
                pl = np.array([I.simulate(P, cfg, a, z, placebo=rng)[0][-1] - 1 for _ in range(100)])
                res.update(ci=[float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))],
                           placebo_median=float(np.median(pl)), placebo_p90=float(np.percentile(pl, 90)),
                           placebo_rank=float((pl < st['total']).mean()), bench=I.benchmark(P, cfg, a, z))
            out[f'{which}_{cand}'] = res
            print(which, cand, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in res.items()}, flush=True)
            del P['_burst']
    (I.OUT / 'r10.json').write_text(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
