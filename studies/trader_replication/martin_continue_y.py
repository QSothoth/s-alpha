"""Continuation Y: preselected next-close entries; no entry-day stop lookahead."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from . import panels
from .martin_continue_a import required_fields
from .martin_strong import Data, lag
from .martin_strong_scan import HOLD, active, hold_sim, name_score, pool_book2


def main():
    D = Data()
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    broad = pool_book2(D, F, H, score, True, 8.0, None, False)
    del F, M, score, H
    width = np.maximum(.01, np.minimum(.025, lag(D.adr) / 2))
    chosen = np.zeros(D.c.shape, bool)
    for d in range(1, len(D.days)):
        es = sorted((e for e in broad[d-1] if np.isfinite(width[d,e[1]])), key=lambda e: e[0])
        for e in es[:6]:
            chosen[d,e[1]] = True
    filled = chosen & np.isfinite(D.c) & (D.c > 0)
    next_valid = np.zeros(D.c.shape, bool)
    next_valid[:-1] = np.isfinite(D.o[1:]) & (D.o[1:] > 0) & np.isfinite(D.l[1:]) & (D.l[1:] > 0)
    survive = np.zeros(D.c.shape, bool)
    stop = D.c[:-1] * (1 - width[:-1])
    survive[:-1] = filled[:-1] & next_valid[:-1] & (D.o[1:] > stop) & (D.l[1:] > stop)
    unknown = filled & ~next_valid
    root = Path(__file__).resolve().parents[2]
    prior_path = root / 'studies/trader_replication/reports/gap_review/strong_continue_r.json'
    prior = json.loads(prior_path.read_text(encoding='utf-8'))
    if prior['dataset_digest'] != D.A['digest']:
        raise ValueError('R has a different dataset digest')
    codes = {str(code): j for j, code in enumerate(D.A['codes'])}
    rows = []
    for p in prior['rows']:
        if p['first_gap'] != 'no_narrow':
            continue
        d, peak, j = D.di[p['day']], D.di[p['peak_day']], codes['US.' + p['ticker']]
        last = min(d + 10, peak - 1)
        times = range(d, last + 1)
        rows.append(dict(day=p['day'], ticker=p['ticker'], peak_day=p['peak_day'],
                         chosen=any(chosen[s,j] for s in times), filled=any(filled[s,j] for s in times),
                         survived=any(survive[s,j] for s in times),
                         unknown_next=any(unknown[s,j] for s in times)))
    years = {}
    for y in ('2024','2025','2026','all'):
        subset = rows if y == 'all' else [r for r in rows if r['day'].startswith(y)]
        ds = [d for d, day in enumerate(D.days) if (y == 'all' or day.startswith(y)) and panels.WINDOW[0] <= day <= panels.WINDOW[1]]
        years[y] = dict(n=len(subset), counts={k: sum(r[k] for r in subset) for k in ('chosen','filled','survived','unknown_next')},
                        median_daily_orders=float(np.median(chosen[ds].sum(1))),
                        median_daily_filled=float(np.median(filled[ds].sum(1))),
                        median_daily_survived=float(np.median(survive[ds].sum(1))))
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_y.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/martin_luk/notes/trades.csv')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), years=years, rows=rows,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths},
               prior_report_sha256=hashlib.sha256(prior_path.read_bytes()).hexdigest())
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_y.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k,v in out.items() if k != 'rows'}, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
