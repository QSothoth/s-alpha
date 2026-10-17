"""R8 single-pass results (notes/PREREG_R8.md); the in-period checks run through r3.py with LUK_DATA=r8new.

    nice -n 19 /opt/futu-opend/venv/bin/python -m studies.martin_luk.r8 new|all
"""
from __future__ import annotations

from dataclasses import replace
import json
import sys

import numpy as np

from . import intraday as I, luk
from .r1 import fmt


def main(which):
    P = I.prepare_r8(which)
    a, b = I.SEGMENTS['r8']
    rows = {}
    for cand in ('L3', 'L4', 'K3', 'M4', 'L5'):
        cfg = replace(I.Cfg(), **I.CANDIDATES[cand])
        curve, dates, tr = I.simulate(P, cfg, a, b)
        s = luk.stats(curve, dates, tr)
        s['bench'] = I.benchmark(P, cfg, a, b)
        s['calmar'] = s['cagr'] / s['maxdd'] if s['maxdd'] else 0.0
        sh = [t for t in tr if t.get('side') == -1]
        s['short_E'] = float(np.mean([t['r'] for t in sh])) if sh else None
        rows[cand] = s
        print(which, len(P['syms']), 'names', cand, fmt(s), {k: round(v, 2) for k, v in s['by_year'].items()},
              'shortE', s['short_E'] and round(s['short_E'], 2), flush=True)
    (I.OUT / f'r8_{which}.json').write_text(json.dumps(rows, indent=1, default=float))


if __name__ == '__main__':
    main(sys.argv[1])
