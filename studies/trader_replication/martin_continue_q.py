"""Continuation Q: ex-post opportunity ceiling; peak labels never generate decisions."""
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
    cache = {}
    def n1_top4(d):
        if d not in cache:
            pool, leaders = np.flatnonzero(M[d] & ~H[d]), np.flatnonzero(H[d])
            with np.errstate(all='ignore'):
                rising = np.isfinite(D.c[d-1, leaders]) & np.isfinite(D.c[d-6, leaders]) & (D.c[d-1, leaders] > D.c[d-6, leaders])
            yes, _ = peer_flags(rr[d-40:d, pool], rr[d-40:d, leaders], rising)
            names = pool[yes]
            names = names[np.argsort(-score[d, names])[:4]]
            cache[d] = set(int(j) for j in names)
        return cache[d]
    rows = []
    for d, j, ticker, _, day in D.his:
        future = D.h[d+1:d+21, j]
        if len(future) != 20 or not np.isfinite(future).all() or not (np.isfinite(D.c[d,j]) and D.c[d,j] > 0):
            continue
        if float(np.max(future) / D.c[d,j] - 1) < .5:
            continue
        peak = d + 1 + int(np.argmax(future))
        end = min(d + 10, peak - 1)
        base = extra = None
        for s in range(d, end + 1):
            if not np.isfinite(D.c[s,j]) or D.c[s,j] <= 0:
                continue
            if base is None and H[s,j]:
                base = s
            if extra is None and j in n1_top4(s):
                extra = s
        any_date = min((x for x in (base, extra) if x is not None), default=None)
        def detail(s):
            if s is None:
                return None
            return dict(date=D.days[s], delay=s-d, remaining=float(D.h[peak,j] / D.c[s,j] - 1),
                        gain_since_his_close=float(D.c[s,j] / D.c[d,j] - 1))
        rows.append(dict(day=day, ticker=ticker, peak_day=D.days[peak], h3=detail(base), n1=detail(extra), union=detail(any_date)))
    years = {}
    for y in ('2024','2025','2026','all'):
        subset = rows if y == 'all' else [r for r in rows if r['day'].startswith(y)]
        fields = {}
        for key in ('h3','n1','union'):
            details = [r[key] for r in subset if r[key] is not None]
            fields[key] = dict(n=len(details), median_delay=float(np.median([x['delay'] for x in details])) if details else None,
                               median_remaining=float(np.median([x['remaining'] for x in details])) if details else None,
                               median_since_his_close=float(np.median([x['gain_since_his_close'] for x in details])) if details else None)
        years[y] = dict(n=len(subset), **fields)
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_n.py',
             'studies/trader_replication/martin_continue_q.py', 'studies/martin_luk/notes/trades.csv')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), years=years, rows=rows,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_q.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in out.items() if k != 'rows'}, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
