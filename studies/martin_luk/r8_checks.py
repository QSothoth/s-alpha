"""R8 follow-up: placebo + bootstrap for L3 on the new names, and a minimum-stop sensitivity on both name sets.

    nice -n 19 /opt/futu-opend/venv/bin/python -m studies.martin_luk.r8_checks
"""
from __future__ import annotations

from dataclasses import replace
import json

import numpy as np

from . import intraday as I


def run(P, cfg, a, b, placebo=None):
    curve, _, tr = I.simulate(P, cfg, a, b, placebo=placebo)
    return float(curve[-1] - 1), tr


def main():
    out = {}
    P = I.prepare_r8('new')
    a, b = I.SEGMENTS['r8']
    cfg = replace(I.Cfg(), **I.CANDIDATES['L3'])
    real, tr = run(P, cfg, a, b)
    r = np.array([t['r'] for t in tr])
    boots = np.random.default_rng(0).choice(r, (2000, len(r))).mean(axis=1)
    rng = np.random.default_rng(1)
    pl = np.array([run(P, cfg, a, b, placebo=rng)[0] for _ in range(100)])
    out['L3_new'] = dict(total=real, exp_r=float(r.mean()), ci=[float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))],
                         placebo_median=float(np.median(pl)), placebo_p90=float(np.percentile(pl, 90)),
                         placebo_rank=float((pl < real).mean()))
    print('L3 new', out['L3_new'], flush=True)
    for name, P2, seg in (('new', P, I.SEGMENTS['r8']), ('k84', None, I.SEGMENTS['full'])):
        P2 = P2 if P2 is not None else I.prepare()
        for cand in ('L3', 'J4'):
            for floor in (0.0, 0.01):
                c = replace(I.Cfg(), **I.CANDIDATES[cand])
                total, tr = run(P2, _with_floor(c, floor), *seg)
                out[f'{cand}_{name}_minstop{floor}'] = dict(total=total, trades=len(tr))
                print(name, cand, 'min stop', floor, 'total', round(total, 3), 'trades', len(tr), flush=True)
    (I.OUT / 'r8_checks.json').write_text(json.dumps(out, indent=1))


def _with_floor(cfg, floor):
    return replace(cfg, min_stop=floor)


if __name__ == '__main__':
    main()
