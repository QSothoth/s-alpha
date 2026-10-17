"""R16 (notes/PREREG_R16.md): stop placement for W2-gated trades on the unbiased R8 subset.

    nice -n 19 /opt/futu-opend/venv/bin/python -m studies.martin_luk.r16
"""
from __future__ import annotations

from dataclasses import replace
import json

import numpy as np

from . import intraday as I, luk, selection as S
from .r10 import allow_for
from .r12 import w2_matrix

SEL, VAL = ('2024-01-02', '2024-12-31'), ('2025-01-02', '2026-10-16')


def one(P, cand, seg, placebo=0):
    cfg = replace(I.Cfg(), **I.CANDIDATES[cand])
    curve, dates, tr = I.simulate(P, cfg, *seg)
    st = luk.stats(curve, dates, tr)
    r = np.array([t['r'] for t in tr]) if tr else np.zeros(1)
    res = dict(total=float(st['total']), maxdd=float(st['maxdd']), trades=len(tr), win=float(st['win']),
               avg_win=float(st['avg_win']), avg_loss=float(st['avg_loss']), exp_r=float(r.mean()),
               day0_exit=float(np.mean([t['days'] == 0 for t in tr])) if tr else 0.0)
    if placebo:
        boots = np.random.default_rng(0).choice(r, (2000, len(r))).mean(axis=1)
        rng = np.random.default_rng(1)
        pl = np.array([I.simulate(P, cfg, *seg, placebo=rng)[0][-1] - 1 for _ in range(placebo)])
        res.update(ci=[float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))],
                   placebo_median=float(np.median(pl)), placebo_p90=float(np.percentile(pl, 90)),
                   placebo_rank=float((pl < st['total']).mean()))
    P.pop('_burst', None)
    return res


def main():
    b = S.broad()
    w2 = w2_matrix(b)
    P = I.prepare_r8('new')
    P['_allow'] = allow_for(P, b, w2)
    out = {'select': {}, 'validate': {}, 'full': {}}
    cands = ['X1', 'X2', 'X3', 'X4', 'X5']
    for c in cands + ['L3']:
        out['select'][c] = one(P, c, SEL)
        print('select', c, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in out['select'][c].items()}, flush=True)
    best = max(cands, key=lambda c: out['select'][c]['total'])
    out['validate'][best] = one(P, best, VAL, placebo=100)
    out['validate']['L3'] = one(P, 'L3', VAL)
    for c in (best, 'L3'):
        print('validate', c, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in out['validate'][c].items()}, flush=True)
    v = out['validate'][best]
    out['chosen'] = best
    out['passed'] = bool(v['total'] > 0 and v['ci'][0] > 0 and v['total'] > v['placebo_p90'])
    out['full'][best] = one(P, best, I.SEGMENTS['r8'])
    Pall = I.prepare_r8('all')
    Pall['_allow'] = allow_for(Pall, b, w2)
    out['full'][best + '_all283'] = one(Pall, best, I.SEGMENTS['r8'])
    print('chosen', best, 'passed', out['passed'], 'full', out['full'])
    (I.OUT / 'r16_stops.json').write_text(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
