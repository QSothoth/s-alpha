"""Continuation S: upper-bound touch tests for prior-close support levels."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from . import panels
from .martin_continue_a import required_fields
from .martin_list import ema
from .martin_strong import Data, lag
from .martin_strong_scan import HOLD, active, hold_sim, name_score


def support_levels(D):
    """Levels indexed by order day, computed exclusively through its previous close."""
    e21 = ema(D.c.astype(float), 21).astype(np.float32)
    return dict(S1=lag(D.e9), S2=lag(e21), S3=lag(D.h, 2))


def main():
    D = Data()
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    del F, M, score
    levels = support_levels(D)
    previous = lag(D.c)
    for key in levels:
        levels[key] = np.where(np.isfinite(levels[key]) & (levels[key] > 0) & (levels[key] <= previous), levels[key], np.nan)
    levels['S4'] = np.fmax(np.fmax(levels['S1'], levels['S2']), levels['S3'])
    root = Path(__file__).resolve().parents[2]
    prior_path = root / 'studies/trader_replication/reports/gap_review/strong_continue_r.json'
    prior = json.loads(prior_path.read_text(encoding='utf-8'))
    if prior['dataset_digest'] != D.A['digest']:
        raise ValueError('R has a different dataset digest')
    codes = {str(code): j for j, code in enumerate(D.A['codes'])}
    all_orders, all_touches, all_survived = {}, {}, {}
    for name, level in levels.items():
        order = H & np.isfinite(level)
        touch = order & np.isfinite(D.o) & np.isfinite(D.l) & (D.o > level) & (D.l <= level)
        survive = touch & (D.l > level * .975)
        all_orders[name], all_touches[name], all_survived[name] = order, touch, survive
    rows = []
    for p in prior['rows']:
        if p['first_gap'] != 'no_narrow':
            continue
        d, peak, j = D.di[p['day']], D.di[p['peak_day']], codes['US.' + p['ticker']]
        last = min(d + 10, peak - 1)
        rec = dict(day=p['day'], ticker=p['ticker'], peak_day=p['peak_day'], levels={})
        for name in levels:
            times = range(d, last + 1)
            rec['levels'][name] = dict(ordered=any(all_orders[name][s,j] for s in times),
                                       touched=any(all_touches[name][s,j] for s in times),
                                       survived_day=any(all_survived[name][s,j] for s in times))
        rows.append(rec)
    years = {}
    for y in ('2024','2025','2026','all'):
        sample = rows if y == 'all' else [r for r in rows if r['day'].startswith(y)]
        date_idx = [d for d, day in enumerate(D.days) if (y == 'all' or day.startswith(y)) and panels.WINDOW[0] <= day <= panels.WINDOW[1]]
        outputs = {}
        for name in levels:
            outputs[name] = dict(ordered=sum(r['levels'][name]['ordered'] for r in sample),
                                 touched=sum(r['levels'][name]['touched'] for r in sample),
                                 survived_day=sum(r['levels'][name]['survived_day'] for r in sample),
                                 median_daily_orders=float(np.median(all_orders[name][date_idx].sum(1))),
                                 median_daily_touches=float(np.median(all_touches[name][date_idx].sum(1))),
                                 median_daily_survived=float(np.median(all_survived[name][date_idx].sum(1))))
        years[y] = dict(n=len(sample), levels=outputs)
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_s.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/martin_luk/notes/trades.csv')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), years=years, rows=rows,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths},
               prior_report_sha256=hashlib.sha256(prior_path.read_bytes()).hexdigest())
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_s.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in out.items() if k != 'rows'}, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
