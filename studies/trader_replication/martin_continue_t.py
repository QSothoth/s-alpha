"""Continuation T: prior-close breakout-order coverage under pessimistic daily-bar ordering."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from . import panels
from .martin_continue_a import required_fields
from .martin_strong import Data, lag
from .martin_strong_scan import HOLD, active, hold_sim, name_score


def main():
    D = Data()
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    del F, M
    level, adr = lag(D.h), lag(D.adr)
    width = np.maximum(.01, np.minimum(.025, adr / 2))
    order = H & np.isfinite(level) & (level > 0) & np.isfinite(width)
    chosen = np.zeros(H.shape, bool)
    for d in range(len(H)):
        ix = np.flatnonzero(order[d] & np.isfinite(score[d]))
        if len(ix):
            chosen[d, ix[np.argmax(score[d, ix])]] = True
    touched = order & np.isfinite(D.o) & np.isfinite(D.h) & np.isfinite(D.l) & (D.o < level) & (D.h >= level)
    survive = touched & (D.l > level * (1 - width))
    chosen_touch, chosen_survive = touched & chosen, survive & chosen
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
                         ordered=any(order[s,j] for s in times), touched=any(touched[s,j] for s in times),
                         survived=any(survive[s,j] for s in times), selected=any(chosen[s,j] for s in times),
                         selected_touched=any(chosen_touch[s,j] for s in times),
                         selected_survived=any(chosen_survive[s,j] for s in times)))
    years = {}
    for y in ('2024','2025','2026','all'):
        subset = rows if y == 'all' else [r for r in rows if r['day'].startswith(y)]
        ds = [d for d, day in enumerate(D.days) if (y == 'all' or day.startswith(y)) and panels.WINDOW[0] <= day <= panels.WINDOW[1]]
        years[y] = dict(n=len(subset), counts={k: sum(r[k] for r in subset) for k in ('ordered','touched','survived','selected','selected_touched','selected_survived')},
                        median_daily_orders=float(np.median(order[ds].sum(1))),
                        median_daily_touches=float(np.median(touched[ds].sum(1))),
                        median_daily_survived=float(np.median(survive[ds].sum(1))))
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_t.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/martin_luk/notes/trades.csv')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), years=years, rows=rows,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths},
               prior_report_sha256=hashlib.sha256(prior_path.read_bytes()).hexdigest())
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_t.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k,v in out.items() if k != 'rows'}, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
