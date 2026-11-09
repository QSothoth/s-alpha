"""Continuation P: preregistered within-peer strength, tightness, then liquidity rank."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from . import panels
from .martin_continue_a import required_fields
from .martin_strong import Data, lag
from .martin_strong_scan import HOLD, active, hold_sim, name_score


def rank_peers(near, candidate_gain, leader_gain, tight, turnover, codes):
    """Order already-known candidate features, with missing values sorted last at each step."""
    valid = near & np.isfinite(leader_gain)[None, :] & np.isfinite(candidate_gain)[:, None]
    count = valid.sum(1)
    strength = np.full(len(candidate_gain), np.nan)
    ok = count > 0
    strength[ok] = ((candidate_gain[:, None] >= leader_gain[None, :]) & valid).sum(1)[ok] / count[ok]
    strength_key = np.where(np.isfinite(strength), -strength, np.inf)
    tight_key = np.where(np.isfinite(tight), tight, np.inf)
    turnover_key = np.where(np.isfinite(turnover), -turnover, np.inf)
    return np.lexsort((np.asarray(codes).astype(str), turnover_key, tight_key, strength_key))


def main():
    D = Data()
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    g21 = F['g21']
    del F, score
    with np.errstate(all='ignore'):
        r = D.c / lag(D.c) - 1
        rr = np.nan_to_num(r - np.nanmedian(np.where(D.rk < 300, r, np.nan), axis=1, keepdims=True)).astype(np.float32)
    root = Path(__file__).resolve().parents[2]
    prior_path = root / 'studies/trader_replication/reports/gap_review/strong_continue_o.json'
    prior = json.loads(prior_path.read_text(encoding='utf-8'))
    if prior['dataset_digest'] != D.A['digest']:
        raise ValueError('Prior report has a different dataset digest')
    ref = {(r['day'], r['ticker']): r for r in prior['rows']}
    cache, rows = {}, []
    for d, j, ticker, _, day in D.his:
        if not (D.U[d, j] and M[d, j] and not H[d, j]):
            continue
        if d not in cache:
            pool, leaders = np.flatnonzero(M[d] & ~H[d]), np.flatnonzero(H[d])
            w, b = rr[d-40:d, pool], rr[d-40:d, leaders]
            w, b = w - w.mean(0), b - b.mean(0)
            near = ((w.T @ b) / len(w) / np.outer(w.std(0) + 1e-6, b.std(0) + 1e-6)) >= .5
            has = near.any(1)
            names, near = pool[has], near[has]
            with np.errstate(all='ignore'):
                tight = (np.max(D.h[d-3:d, names], axis=0) / np.min(D.l[d-3:d, names], axis=0) - 1) / D.adr[d-1, names]
            order = rank_peers(near, g21[d-1, names], g21[d-1, leaders], tight, D.to20[d-1, names], D.A['codes'][names])
            cache[d] = {int(names[pos]): i + 1 for i, pos in enumerate(order)}
        ranks = cache[d]
        old = ref[(day, ticker)]
        if (j in ranks) != (old['rank'] is not None) or len(ranks) != old['n1_count']:
            raise ValueError('N1 does not match the preregistered ranking sample')
        rows.append(dict(day=day, ticker=ticker, big=old['big'], n1_count=len(ranks), h3_rank=old['rank'], p1_rank=ranks.get(j)))
    years = {}
    for y in ('2024', '2025', '2026'):
        groups = {}
        for group in ('all', 'big'):
            sample = [r for r in rows if r['day'].startswith(y) and (group == 'all' or r['big'] is True)]
            groups[group] = dict(n=len(sample), in_n1=sum(r['p1_rank'] is not None for r in sample),
                                 p1={str(n): sum(r['p1_rank'] is not None and r['p1_rank'] <= n for r in sample) for n in (1, 2, 4)},
                                 original={str(n): sum(r['h3_rank'] is not None and r['h3_rank'] <= n for r in sample) for n in (1, 2, 4)},
                                 random_expected={str(n): float(sum(min(n, r['n1_count']) / r['n1_count'] for r in sample if r['p1_rank'] is not None)) for n in (1, 2, 4)})
        years[y] = groups
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_p.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/martin_luk/notes/trades.csv')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), years=years, rows=rows,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths},
               prior_report_sha256=hashlib.sha256(prior_path.read_bytes()).hexdigest())
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_p.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in out.items() if k != 'rows'}, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
