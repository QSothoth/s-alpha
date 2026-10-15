"""W24 one-shot validation: fit V1 on selection, score V1 and R1 on validation."""
import json
import math
import sys

import numpy as np

import w24_analyze as a

CPS = range(8)          # 10:00 .. 15:00 (15:30 has no 31-bar future)


def prepared(F):
    el = (F['cp'] + 1) * 30.0
    ok = ((F['tpb'] >= 2) & (F['prev_range'] > 0) & (F['rv_so_far'] > 0) & (F['fut_range'] > 0)
          & (F['cp'] < 8))
    with np.errstate(divide='ignore', invalid='ignore'):
        x1 = np.log(F['rv_so_far'] / el)
        x2 = np.log(F['prev_range'])
        y = np.log(F['fut_range'])
    return ok, x1, x2, y


def fit(F):
    ok, x1, x2, y = prepared(F)
    models = {}
    for c in CPS:
        k = ok & (F['cp'] == c)
        full = np.column_stack([np.ones(k.sum()), x1[k], x2[k]])
        b, *_ = np.linalg.lstsq(full, y[k], rcond=None)
        res = y[k] - full @ b
        base = np.column_stack([np.ones(k.sum()), x2[k]])
        b0, *_ = np.linalg.lstsq(base, y[k], rcond=None)
        models[c] = dict(coef=b.tolist(), lo=float(np.quantile(res, 0.1)), hi=float(np.quantile(res, 0.9)),
                         base=b0.tolist())
    return models


def r2(y, p):
    return 1 - ((y - p) ** 2).sum() / ((y - y.mean()) ** 2).sum()


def v1(F, models):
    ok, x1, x2, y = prepared(F)
    ys, ps, bs, cover = [], [], [], []
    per = {}
    for c in CPS:
        k = ok & (F['cp'] == c)
        m = models[c]
        p = m['coef'][0] + m['coef'][1] * x1[k] + m['coef'][2] * x2[k]
        b = m['base'][0] + m['base'][1] * x2[k]
        inside = (y[k] >= p + m['lo']) & (y[k] <= p + m['hi'])
        per[c] = dict(n=int(k.sum()), r2=r2(y[k], p), r2_base=r2(y[k], b), coverage=float(inside.mean()))
        ys.append(y[k]); ps.append(p); bs.append(b); cover.append(inside)
    y, p, b, cover = map(np.concatenate, (ys, ps, bs, cover))
    lo, hi = np.quantile(p, [0.2, 0.8])
    ratio = math.exp(y[p >= hi].mean() - y[p <= lo].mean())
    total = dict(n=len(y), r2=r2(y, p), r2_base=r2(y, b), coverage=float(cover.mean()), q5_q1=ratio)
    gates = dict(r2=total['r2'] >= 0.40 and min(v['r2'] for v in per.values()) >= 0.30,
                 beats_base=total['r2'] - total['r2_base'] >= 0.10,
                 coverage=0.75 <= total['coverage'] <= 0.85,
                 spread=ratio >= 2)
    return dict(total=total, by_checkpoint=per, gates=gates, passed=all(gates.values()))


def r1(F):
    k = (F['tpb'] >= 2) & (F['prev_range'] > 0) & (F['rv_so_far'] > 0) & (F['cp'] < 8) & (F['r_open'] != 0)
    d = -np.sign(F['r_open'][k])
    gross = d * F['fclose'][k]
    mu, t, n = a.clustered(F['day'][k], gross)
    longs, shorts = gross[d > 0], gross[d < 0]
    net = mu - 0.0010
    gates = dict(positive=mu > 0 and t >= 2, both_sides=longs.mean() > 0 and shorts.mean() > 0)
    return dict(n=n, gross_bp=mu * 1e4, t=t, long_bp=longs.mean() * 1e4, short_bp=shorts.mean() * 1e4,
                net_bp=net * 1e4, gates=gates, passed=all(gates.values()),
                tradable=all(gates.values()) and net > 0)


if __name__ == '__main__':
    selection, validation = a.load(sys.argv[1]), a.load(sys.argv[2])
    models = fit(selection)
    out = dict(models=models, v1_selection=v1(selection, models), v1=v1(validation, models), r1=r1(validation))
    print(json.dumps(out, indent=2, default=float))
