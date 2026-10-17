"""R3 in-period checks (notes/PREREG_R3.md) for one candidate on the 5-minute universe.

    /opt/futu-opend/venv/bin/python -m studies.martin_luk.r3 J4 [causal]
"""
from __future__ import annotations

from dataclasses import replace
import json
from multiprocessing import Pool
import os
import sys

import numpy as np

from . import intraday as I

P = None
CFG = None
DATA = os.environ.get('LUK_DATA', 'k5')          # k5 = the 84 names; r8new / r8all = PREREG_R8 panels
PREP = {'k5': I.prepare, 'r8new': lambda: I.prepare_r8('new'), 'r8all': lambda: I.prepare_r8('all')}


def _init(cfg):
    global P, CFG
    P, CFG = PREP[DATA](), cfg


def _final(args):
    start, end, keep_seed, placebo_seed = args
    keep = None
    if keep_seed is not None:
        seed, half = keep_seed
        rng = np.random.default_rng(seed)
        perm = rng.permutation(len(P['syms']))
        keep = np.zeros(len(P['syms']), bool)
        keep[perm[half::2]] = True
    pl = None if placebo_seed is None else np.random.default_rng(placebo_seed)
    curve, _, trades = I.simulate(P, CFG, start, end, placebo=pl, keep=keep)
    return float(curve[-1] - 1), [t['pnl'] for t in trades] if placebo_seed is None else None


def main(argv):
    cand = argv[0]
    over = {'confirm_close': True} if 'causal' in argv[1:] else {}
    cfg = replace(I.Cfg(), **I.CANDIDATES[cand], **over)
    full = I.SEGMENTS['full' if DATA == 'k5' else 'r8']
    segs = {'2024': ('2024-01-02', '2024-12-31'), '2025-26': ('2025-01-02', full[1])}
    jobs = [(*full, None, None)] + [(*full, None, 1000 + k) for k in range(200)]
    for name, (a, b) in segs.items():
        jobs += [(a, b, None, None)] + [(a, b, None, 2000 + k) for k in range(100)]
    for split in range(20):
        for half in (0, 1):
            jobs += [(*full, (split, half), None)] + [(*full, (split, half), 3000 + 100 * split + 50 * half + k)
                                                      for k in range(50)]
    # ponytail: one worker by default - two busy cores for hours got the 2-vCPU VPS stopped on 2026-10-16
    with Pool(int(os.environ.get('LUK_WORKERS', '1')), initializer=_init, initargs=(cfg,)) as pool:
        res = pool.map(_final, jobs, chunksize=4)
    it = iter(res)
    real, pnls = next(it)
    pl = np.array([next(it)[0] for _ in range(200)])
    seg_out = {}
    for name in segs:
        r = next(it)[0]
        ps = np.array([next(it)[0] for _ in range(100)])
        seg_out[name] = dict(real=r, placebo_median=float(np.median(ps)), rank=float((ps < r).mean()))
    halves = []
    for split in range(20):
        for half in (0, 1):
            r = next(it)[0]
            ps = np.array([next(it)[0] for _ in range(50)])
            halves.append(dict(split=split, half=half, real=r, placebo_median=float(np.median(ps)),
                               beats=bool(r > np.median(ps))))
    _init(cfg)
    s, trades, _ = I.evaluate(P, cand, full, **over)
    rr = np.array([t['r'] for t in trades])
    boots = np.random.default_rng(0).choice(rr, (2000, len(rr))).mean(axis=1)
    out = dict(candidate=cand, causal=bool(over), total=real, cagr=float(s['cagr']), maxdd=float(s['maxdd']),
               trades=len(trades), win=float(s['win']), avg_win=float(s['avg_win']), avg_loss=float(s['avg_loss']),
               exp_r=float(rr.mean()), ci=[float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))],
               by_year={k: float(v) for k, v in s['by_year'].items()}, bench=float(s['bench']),
               placebo_median=float(np.median(pl)), placebo_p90=float(np.percentile(pl, 90)),
               placebo_rank=float((pl < real).mean()), segments=seg_out,
               halves_beating=int(sum(h['beats'] for h in halves)), halves=halves,
               pnl_ex_top10=float(sum(sorted(pnls)[:-10])))
    checks = dict(placebo=out['placebo_rank'] > .9, halves=out['halves_beating'] >= 28,
                  segments=all(v['real'] > v['placebo_median'] for v in seg_out.values()),
                  top10=out['pnl_ex_top10'] > 0, bootstrap=out['ci'][0] > 0)
    out['checks'] = checks
    out['passed'] = all(checks.values())
    tag = f"{cand}{'_causal' if over else ''}{'' if DATA == 'k5' else '_' + DATA}"
    (I.OUT / f'r3_check_{tag}.json').write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != 'halves'}, indent=1))


if __name__ == '__main__':
    main(sys.argv[1:])
