"""R1 runner: the five pre-registered candidates on one segment for all three markets.

    /opt/opend-us-options/.venv/bin/python -m studies.martin_luk.r1 select
    /opt/opend-us-options/.venv/bin/python -m studies.martin_luk.r1 validate C?   # once, after selection
"""
from __future__ import annotations

from dataclasses import replace
import json
import sys

import numpy as np

from . import luk

SEGMENTS = {'select': ('2024-05-01', '2025-04-30'), 'validate': ('2025-05-01', '2026-10-15')}
OUT = luk.ROOT / 'studies' / 'martin_luk' / 'reports'


def prepared(market):
    p = luk.load(market)
    base = luk.Config(market=market)
    ind = luk.indicators(p, base)
    ind['_close'] = p['close']
    return p, ind


def one(p, ind, market, cand, start, end, **over):
    cfg = replace(luk.Config(market=market), **luk.CANDIDATES[cand], **over)
    orders, closes = luk.signals(p, ind, cfg)
    curve, dates, trades = luk.simulate(p, ind, cfg, start, end, orders, closes)
    s = luk.stats(curve, dates, trades)
    s['bench'] = luk.benchmark(ind, p['dates'], start, end)
    s['calmar'] = s['cagr'] / s['maxdd'] if s['maxdd'] > 0 else np.nan
    return s, trades


def fmt(s):
    return (f"{s['total']*100:8.1f}% cagr {s['cagr']*100:7.1f}% dd {s['maxdd']*100:5.1f}% calmar {s['calmar']:5.2f} "
            f"n {s['trades']:4d} ({s['per_year']:4.0f}/y) win {s['win']*100:4.1f}% "
            f"+{s['avg_win']*100:4.1f}%/{s['avg_loss']*100:5.1f}% E {s['exp_r']:+.3f}R winR {s['avg_win_r']:4.1f} "
            f"hold {s['days_win']:4.1f}/{s['days_loss']:3.1f}d bench {s['bench']*100:6.1f}%")


def main(argv):
    seg = argv[0]
    start, end = SEGMENTS[seg]
    cands = list(luk.CANDIDATES) if seg == 'select' else [argv[1]]
    rows = {}
    for market in ('us', 'hk', 'cn'):
        p, ind = prepared(market)
        for cand in cands:
            s, _ = one(p, ind, market, cand, start, end)
            rows[f'{market}.{cand}'] = {k: v for k, v in s.items()}
            print(f'{market} {cand} {fmt(s)}', flush=True)
    OUT.mkdir(exist_ok=True)
    (OUT / f'r1_{seg}.json').write_text(json.dumps(rows, indent=1, default=float))


if __name__ == '__main__':
    main(sys.argv[1:])
