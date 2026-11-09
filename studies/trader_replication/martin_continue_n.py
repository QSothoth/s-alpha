"""Continuation N: prior-close correlated peer coverage, without N-by-N panels."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from . import panels
from .martin_continue_a import required_fields
from .martin_strong import Data, lag
from .martin_strong_scan import HOLD, active, hold_sim, name_score


def peer_flags(candidates, leaders, rising):
    """Rows are prior sessions; compare candidates only with current H3 names."""
    if not candidates.shape[1] or not leaders.shape[1]:
        return np.zeros(candidates.shape[1], bool), np.zeros(candidates.shape[1], bool)
    a = candidates - candidates.mean(axis=0)
    b = leaders - leaders.mean(axis=0)
    corr = (a.T @ b) / len(a) / np.outer(a.std(axis=0) + 1e-6, b.std(axis=0) + 1e-6)
    near = corr >= .5
    return near.any(axis=1), (near & rising[None, :]).sum(axis=1) >= 2


def main():
    D = Data()
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    del F, score
    with np.errstate(all='ignore'):
        returns = D.c / lag(D.c) - 1
        rr = np.nan_to_num(returns - np.nanmedian(np.where(D.rk < 300, returns, np.nan), axis=1, keepdims=True)).astype(np.float32)
    n1, n2 = np.zeros(D.c.shape, bool), np.zeros(D.c.shape, bool)
    for d in range(40, len(D.days)):
        pool = np.flatnonzero(M[d] & ~H[d])
        leaders = np.flatnonzero(H[d])
        if not len(pool) or not len(leaders):
            continue
        with np.errstate(all='ignore'):
            rising = np.isfinite(D.c[d-1, leaders]) & np.isfinite(D.c[d-6, leaders]) & (D.c[d-1, leaders] > D.c[d-6, leaders])
        n1[d, pool], n2[d, pool] = peer_flags(rr[d-40:d, pool], rr[d-40:d, leaders], rising)
    rows = []
    for d, j, ticker, _, day in D.his:
        if not (D.U[d, j] and M[d, j] and not H[d, j]):
            continue
        future = D.h[d+1:d+21, j]
        known = len(future) == 20 and np.isfinite(future).all() and np.isfinite(D.c[d, j]) and D.c[d, j] > 0
        big = bool(np.max(future) / D.c[d, j] - 1 >= .5) if known else None
        rows.append(dict(day=day, ticker=ticker, big=big, n1=bool(n1[d, j]), n2=bool(n2[d, j])))
    years = {}
    for y in ('2024', '2025', '2026'):
        dates = [d for d, day in enumerate(D.days) if day.startswith(y) and panels.WINDOW[0] <= day <= panels.WINDOW[1]]
        eligible = (M & ~H).sum(1)
        widths = {}
        for name, mask in (('n1', n1), ('n2', n2)):
            widths[name] = dict(median_count=float(np.median(mask[dates].sum(1))),
                                mean_share=float(np.mean(mask[dates].sum(1) / np.maximum(eligible[dates], 1))))
        groups = {}
        for name, sample in (('all', [r for r in rows if r['day'].startswith(y)]),
                             ('big', [r for r in rows if r['day'].startswith(y) and r['big'] is True])):
            groups[name] = dict(n=len(sample), n1=sum(r['n1'] for r in sample), n2=sum(r['n2'] for r in sample),
                                expected_n1=float(sum(n1[D.di[r['day']]].sum() / max(1, eligible[D.di[r['day']]]) for r in sample)),
                                expected_n2=float(sum(n2[D.di[r['day']]].sum() / max(1, eligible[D.di[r['day']]]) for r in sample)))
        years[y] = dict(widths=widths, groups=groups)
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_n.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/martin_luk/notes/trades.csv')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), years=years, rows=rows,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_n.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in out.items() if k != 'rows'}, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
