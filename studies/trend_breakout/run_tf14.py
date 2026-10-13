"""TF14 (notes/TF14_PREREG.md, exploratory): K1 chase rule gated by market-wide turnover expansion.

    PYTHONUTF8=1 /opt/futu-opend/venv/bin/python -m studies.trend_breakout.run_tf14
"""
from __future__ import annotations

import json

import numpy as np

from . import run_tf6, run_tf8, run_tf12, signals as S
from .run_tf1 import REPORTS


def main():
    np.seterr(invalid='ignore', divide='ignore')
    p = run_tf8.load()
    pool = run_tf6.pit_pool(p)
    ind = run_tf12.indicators(p)
    total = np.where(pool, np.nan_to_num(p['turnover']), 0).sum(axis=1)[:, None]
    expand = (S.sma(total, 20) > S.sma(total, 120))[:, 0]
    k1 = S.market_up(p['close'], pool)
    st = {'K1': k1, 'V1': expand, 'V2': expand & k1}
    out = {}
    lo, hi = run_tf6.rows(p, *run_tf8.SPANS['dev'])
    for name, up in st.items():
        print(f'--- dev {name} (allows {up[lo:hi + 1].mean():.0%})', flush=True)
        out[f'dev_{name}'], _ = run_tf12.run_one(p, ind, pool, up, lo, hi, 'K1')
        out[f'dev_{name}']['allow_share'] = float(up[lo:hi + 1].mean())
    ok = [m for m in ('V1', 'V2') if all(out[f'dev_{m}']['criteria'].values())]
    neg = {m: sum(v['mean_r'] < 0 for v in out[f'dev_{m}']['years'].values()) for m in ok}
    winner = min(ok, key=lambda m: (neg[m], -out[f'dev_{m}']['mean_r'])) if ok else None
    out['winner'] = winner
    print('winner:', winner, 'negative years', neg, flush=True)
    if winner:
        lo, hi = run_tf6.rows(p, *run_tf8.SPANS['holdout'])
        up = st[winner]
        print(f'--- validation (already used, exploratory) {winner} (allows {up[lo:hi + 1].mean():.0%})', flush=True)
        out[f'val_{winner}'], _ = run_tf12.run_one(p, ind, pool, up, lo, hi, 'K1')
    (REPORTS / 'tf14.json').write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float) + '\n',
                                       encoding='utf-8')
    print('DONE', flush=True)


if __name__ == '__main__':
    main()
