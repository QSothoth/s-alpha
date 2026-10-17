"""How the replicated edge scales: universe size, and per-trade equity growth projected to his trade count.

    nice -n 19 /opt/futu-opend/venv/bin/python -m studies.martin_luk.scale
"""
from __future__ import annotations

from dataclasses import replace
import json

import numpy as np

from . import intraday as I


def per_trade(P, cand):
    """Per-trade log growth of equity by calendar year from one full-period run (trade pnl / equity at entry)."""
    cfg = replace(I.Cfg(), **I.CANDIDATES[cand])
    curve, dates, trades = I.simulate(P, cfg, *I.SEGMENTS['full'])
    eq = dict(zip(dates.astype(str), np.r_[1.0, curve[:-1]]))      # equity at the previous close
    by = {}
    for t in trades:
        g = np.log1p(t['pnl'] / eq[t['entry']])
        by.setdefault(t['entry'][:4], []).append(g)
    return {y: np.array(v) for y, v in by.items()}, curve, dates


def main():
    P = I.prepare()
    out = {}
    stocks = np.flatnonzero(P['stock'])
    yrs = len(I.simulate(P, replace(I.Cfg(), **I.CANDIDATES['L3']), *I.SEGMENTS['full'])[0]) / 252
    for cand in ('L3', 'L5'):
        cfg = replace(I.Cfg(), **I.CANDIDATES[cand])
        rows = []
        for size in (21, 42, 63):
            for seed in range(10):
                keep = np.zeros(len(P['syms']), bool)
                keep[np.random.default_rng(seed).choice(stocks, size, replace=False)] = True
                curve, _, trades = I.simulate(P, cfg, *I.SEGMENTS['full'], keep=keep)
                rows.append((size, float(np.log(curve[-1]) / yrs), len(trades) / yrs))
        curve, _, trades = I.simulate(P, cfg, *I.SEGMENTS['full'])
        rows.append((len(stocks), float(np.log(curve[-1]) / yrs), len(trades) / yrs))
        scale = {}
        for size in sorted({r[0] for r in rows}):
            g = [r[1] for r in rows if r[0] == size]
            n = [r[2] for r in rows if r[0] == size]
            scale[size] = dict(log_growth_per_year=float(np.median(g)), trades_per_year=float(np.median(n)))
        by, _, _ = per_trade(P, cand)
        proj = {}
        for y, g in by.items():
            rng = np.random.default_rng(0)
            boots = [float(np.exp(rng.choice(g, 930).sum()) - 1) for _ in range(2000)]
            proj[y] = dict(trades=len(g), mean_log_per_trade=float(g.mean()),
                           at_930_trades=float(np.exp(930 * g.mean()) - 1),
                           at_930_p10_p90=[float(np.percentile(boots, 10)), float(np.percentile(boots, 90))])
        allg = np.concatenate(list(by.values()))
        out[cand] = dict(scale=scale, by_year=proj, two_year_at_930=float(np.exp(2 * 930 * allg.mean()) - 1))
        print(cand, json.dumps(out[cand], indent=1), flush=True)
    (I.OUT / 'scale.json').write_text(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
