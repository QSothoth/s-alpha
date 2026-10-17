"""Pre-registered checks for one (market, candidate, segment): bootstrap of per-trade R and the placebo.

    /opt/futu-opend/venv/bin/python -m studies.martin_luk.checks us C2 validate [round]
"""
from __future__ import annotations

from dataclasses import replace
import json
import sys

import numpy as np

from . import luk, r1


def bootstrap_lo(r, n=2000, seed=0):
    rng = np.random.default_rng(seed)
    means = rng.choice(r, (n, len(r))).mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def placebo(p, ind, cfg, start, end, orders, closes, n=200, seed=1):
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        curve, _, _ = luk.simulate(p, ind, cfg, start, end, orders, closes, placebo=rng)
        out.append(curve[-1] - 1)
    return np.array(out)


def main(argv):
    market, cand, seg = argv[:3]
    cands = getattr(sys.modules[__package__ + '.' + (argv[3] if len(argv) > 3 else 'r1')], 'CANDIDATES', luk.CANDIDATES)
    start, end = r1.SEGMENTS[seg]
    p, ind = r1.prepared(market)
    cfg = replace(luk.Config(market=market), **cands[cand])
    orders, closes = luk.signals(p, ind, cfg)
    curve, dates, trades = luk.simulate(p, ind, cfg, start, end, orders, closes)
    s = luk.stats(curve, dates, trades)
    r = np.array([t['r'] for t in trades])
    lo, hi = bootstrap_lo(r)
    pl = placebo(p, ind, cfg, start, end, orders, closes)
    top = np.sort(r)[::-1]
    res = dict(total=float(s['total']), exp_r=float(r.mean()), ci=(lo, hi), bench=luk.benchmark(ind, p['dates'], start, end),
               placebo_p90=float(np.percentile(pl, 90)), placebo_median=float(np.median(pl)),
               placebo_rank=float((pl < s['total']).mean()), sum_r=float(r.sum()), sum_r_ex_top10=float(top[10:].sum()))
    print(json.dumps(res, indent=1))
    (r1.OUT / f'checks_{market}_{cand}_{seg}.json').write_text(json.dumps(res, indent=1))


if __name__ == '__main__':
    main(sys.argv[1:])
