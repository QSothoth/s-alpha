"""Continuation O: prior-close H3-score rank inside the preregistered N1 peer list."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from . import panels
from .martin_continue_a import required_fields
from .martin_continue_n import peer_flags
from .martin_strong import Data, lag
from .martin_strong_scan import HOLD, active, hold_sim, name_score


def main():
    D = Data()
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    del F
    with np.errstate(all='ignore'):
        r = D.c / lag(D.c) - 1
        rr = np.nan_to_num(r - np.nanmedian(np.where(D.rk < 300, r, np.nan), axis=1, keepdims=True)).astype(np.float32)
    root = Path(__file__).resolve().parents[2]
    prior_path = root / 'studies/trader_replication/reports/gap_review/strong_continue_n.json'
    prior = json.loads(prior_path.read_text(encoding='utf-8'))
    if prior['dataset_digest'] != D.A['digest']:
        raise ValueError('N1 reference has a different dataset digest')
    by_ledger = {(r['day'], r['ticker']): r for r in prior['rows']}
    out_rows = []
    cache = {}
    for d, j, ticker, _, day in D.his:
        if not (D.U[d, j] and M[d, j] and not H[d, j]):
            continue
        if d not in cache:
            pool, leaders = np.flatnonzero(M[d] & ~H[d]), np.flatnonzero(H[d])
            with np.errstate(all='ignore'):
                rising = np.isfinite(D.c[d-1, leaders]) & np.isfinite(D.c[d-6, leaders]) & (D.c[d-1, leaders] > D.c[d-6, leaders])
            flags, _ = peer_flags(rr[d-40:d, pool], rr[d-40:d, leaders], rising)
            names = pool[flags]
            names = names[np.argsort(-score[d, names])]
            cache[d] = {int(name): i + 1 for i, name in enumerate(names)}
        ranks = cache[d]
        rank = ranks.get(j)
        old = by_ledger[(day, ticker)]
        if (rank is not None) != old['n1']:
            raise ValueError('N1 coverage differs from its saved diagnostic')
        out_rows.append(dict(day=day, ticker=ticker, big=old['big'], n1_count=len(ranks), rank=rank))
    years = {}
    for y in ('2024', '2025', '2026'):
        groups = {}
        for group in ('all', 'big'):
            sample = [r for r in out_rows if r['day'].startswith(y) and (group == 'all' or r['big'] is True)]
            hits = {str(n): sum(r['rank'] is not None and r['rank'] <= n for r in sample) for n in (1, 2, 4)}
            random = {str(n): float(sum(min(n, r['n1_count']) / r['n1_count'] for r in sample if r['rank'] is not None)) for n in (1, 2, 4)}
            groups[group] = dict(n=len(sample), in_n1=sum(r['rank'] is not None for r in sample), hits=hits, random_expected_within_n1=random)
        years[y] = dict(n1_width=prior['years'][y]['widths']['n1'], groups=groups)
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_n.py',
             'studies/trader_replication/martin_continue_o.py', 'studies/martin_luk/notes/trades.csv')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), years=years, rows=out_rows,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths},
               prior_report_sha256=hashlib.sha256(prior_path.read_bytes()).hexdigest())
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_o.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in out.items() if k != 'rows'}, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
