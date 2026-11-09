"""R12 (notes/PREREG_R12.md): W2 watchlist (whole-market multi-list leaders) gating his L3 rules.

    nice -n 19 /opt/opend-us-options/.venv/bin/python -m studies.martin_luk.r12
"""
from __future__ import annotations

from dataclasses import replace
import json

import numpy as np

from . import intraday as I, luk, selection as S
from .r10 import allow_for


def w2_matrix(b):
    c, h, l = (b[k].astype(float) for k in ('close', 'high', 'low'))
    raw = b['raw_close'].astype(float)
    to20 = luk.rolling_mean(b['turnover'].astype(float), 20)
    adr = luk.rolling_mean(h / l - 1, 20) * 100
    e9, e21, e50 = luk.ema(c, 9), luk.ema(c, 21), luk.ema(c, 50)
    with np.errstate(invalid='ignore', divide='ignore'):
        pool = (raw >= 1) & (to20 >= 2e6)
        nlist = np.zeros(c.shape, np.int8)
        for hz in (21, 63, 126):
            r = np.where(pool, c / luk.lag(c, hz) - 1, np.nan)
            nlist += (pool & (r >= np.nanquantile(r, .98, axis=1)[:, None])).astype(np.int8)
        return S._past_any(nlist >= 2, 20) & (raw >= 5) & (to20 >= 20e6) & (adr >= 4) & (e9 > e21) & (e21 > e50)


def main():
    b = S.broad()
    w2 = w2_matrix(b)
    out = {}
    for which in ('new', 'all'):
        P = I.prepare_r8(which)
        P['_allow'] = allow_for(P, b, w2)
        a, z = I.SEGMENTS['r8']
        span = (P['days'] >= a) & (P['days'] <= z)
        names_in = int(P['_allow'][span].any(0).sum())
        for cand in ('L3', 'L4'):
            cfg = replace(I.Cfg(), **I.CANDIDATES[cand])
            curve, dates, tr = I.simulate(P, cfg, a, z)
            st = luk.stats(curve, dates, tr)
            r = np.array([t['r'] for t in tr]) if tr else np.zeros(1)
            res = dict(total=float(st['total']), cagr=float(st['cagr']), maxdd=float(st['maxdd']), trades=len(tr),
                       win=float(st['win']), avg_win=float(st['avg_win']), avg_loss=float(st['avg_loss']),
                       exp_r=float(r.mean()), by_year={k: float(v) for k, v in st['by_year'].items()},
                       names_in_watchlist=names_in, watch_name_days=int(P['_allow'][span].sum()))
            if which == 'new' and cand == 'L3':
                boots = np.random.default_rng(0).choice(r, (2000, len(r))).mean(axis=1)
                rng = np.random.default_rng(1)
                pl = np.array([I.simulate(P, cfg, a, z, placebo=rng)[0][-1] - 1 for _ in range(100)])
                res.update(ci=[float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))],
                           placebo_median=float(np.median(pl)), placebo_p90=float(np.percentile(pl, 90)),
                           placebo_rank=float((pl < st['total']).mean()))
            out[f'{which}_{cand}'] = res
            print(which, cand, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in res.items()}, flush=True)
            P.pop('_burst', None)
    (I.OUT / 'r12.json').write_text(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
