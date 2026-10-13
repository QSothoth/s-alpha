"""TF13 (notes/TF13_PREREG.md, exploratory): K1 chase rule with stricter market-state filters M1-M3.
Selection on the development span only; the validation span is reported as already used (not evidence).

    PYTHONUTF8=1 /opt/futu-opend/venv/bin/python -m studies.trend_breakout.run_tf13
"""
from __future__ import annotations

import json

import numpy as np

from . import run_tf6, run_tf8, run_tf12, signals as S
from .run_tf1 import REPORTS


def ew_index(close, pool):
    r = close[1:] / close[:-1] - 1
    r = np.where(pool[:-1] & ~np.isnan(r), r, np.nan)
    has = (~np.isnan(r)).any(axis=1)
    day = np.zeros(len(r))
    day[has] = np.nanmean(r[has], axis=1)
    return np.concatenate([[1.0], np.cumprod(1 + day)])


def rolling_median(x, n):
    out = np.full(len(x), np.nan)
    for t in range(n - 1, len(x)):
        out[t] = np.nanmedian(x[t - n + 1:t + 1])
    return out


def states(p, ind, pool):
    idx = ew_index(p['close'], pool)[:, None]
    m1 = ((idx > S.sma(idx, 50)) & (idx > S.sma(idx, 200)))[:, 0]
    n = pool.sum(axis=1).astype(float)
    with np.errstate(invalid='ignore', divide='ignore'):
        breadth = (pool & S._bool(ind['above200'])).sum(axis=1) / n
        highs = (pool & (ind['close'] > ind['hh55_prev'])).sum(axis=1) / n
    m2 = np.nan_to_num(breadth) > 0.5
    m3 = np.nan_to_num(highs) > np.nan_to_num(rolling_median(highs, 250), nan=np.inf)
    return {'K1': S.market_up(p['close'], pool), 'M1': m1, 'M2': m2, 'M3': m3}


def main():
    np.seterr(invalid='ignore', divide='ignore')
    p = run_tf8.load()
    pool = run_tf6.pit_pool(p)
    ind = run_tf12.indicators(p)
    st = states(p, ind, pool)
    out = {}
    lo, hi = run_tf6.rows(p, *run_tf8.SPANS['dev'])
    for name, up in st.items():
        print(f'--- dev {name} (market allows entry {up[lo:hi + 1].mean():.0%} of days)', flush=True)
        out[f'dev_{name}'], _ = run_tf12.run_one(p, ind, pool, up, lo, hi, 'K1')
        out[f'dev_{name}']['allow_share'] = float(up[lo:hi + 1].mean())
    ok = [m for m in ('M1', 'M2', 'M3') if all(out[f'dev_{m}']['criteria'].values())]
    neg = {m: sum(v['mean_r'] < 0 for v in out[f'dev_{m}']['years'].values()) for m in ok}
    winner = min(ok, key=lambda m: (neg[m], -out[f'dev_{m}']['mean_r'])) if ok else None
    out['winner'] = winner
    print('winner:', winner, 'negative years', neg, flush=True)
    if winner:
        lo, hi = run_tf6.rows(p, *run_tf8.SPANS['holdout'])
        for name in ('K1', winner):  # validation span already used for K1: exploratory reference only
            up = st[name]
            print(f'--- validation (already used, exploratory) {name} (allows {up[lo:hi + 1].mean():.0%})', flush=True)
            out[f'val_{name}'], _ = run_tf12.run_one(p, ind, pool, up, lo, hi, 'K1')
            out[f'val_{name}']['allow_share'] = float(up[lo:hi + 1].mean())
    (REPORTS / 'tf13.json').write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float) + '\n',
                                       encoding='utf-8')


if __name__ == '__main__':
    main()
