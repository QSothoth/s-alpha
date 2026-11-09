"""Continuation BE: U1's opportunity funnel for Martin's big-move windows."""
from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np

from . import panels, system
from .martin_continue_a import required_fields
from .martin_continue_b_check import digest
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, name_score, u1_entries


def main():
    root = Path(__file__).resolve().parents[2]
    prior = json.loads((root / 'studies/trader_replication/reports/gap_review/strong_continue_ar.json').read_text())
    D = Data()
    if D.A['digest'] != prior['dataset_digest']:
        raise ValueError('frozen dataset differs from AR')
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    entries = u1_entries(D, F, H, score)
    del F, M, score
    rules = f1_rules(D, 6, (1, 3))
    px, ema = D.base.px(D.A), D.base.ema_inputs(D.A, D.pool, rules)
    _, _, trades = system.simulate(px, ema, rules, entries, *panels.WINDOW)
    if digest(trades) != prior['results']['U1']['trades_digest']:
        raise AssertionError('U1 path differs from AR')
    windows = []
    for d, j, ticker, setup, date in D.big:
        peak = d + 1 + int(np.nanargmax(D.h[d + 1:d + 21, j]))
        end = min(d + 10, peak - 1)
        code = str(D.A['codes'][j])
        held = any(t['code'] == code and t['side'] > 0 and D.di[t['entry']] <= end
                   and D.di[t['exit']] >= d for t in trades)
        candidates = [(day, e[5]) for day in range(d, end + 1) for e in entries[day] if e[1] == j and e[2] > 0]
        in_pool = bool(H[d:end + 1, j].any())
        stage = 'held' if held else 'candidate_no_hold' if candidates else 'pool_no_candidate' if in_pool else 'no_pool_or_candidate'
        windows.append({'date': date, 'ticker': ticker, 'setup': setup, 'peak': D.days[peak], 'end': D.days[end],
                        'stage': stage, 'h3_in_window': in_pool, 'candidate_count': len(candidates),
                        'first_candidate': D.days[min(day for day, _ in candidates)] if candidates else None,
                        'has_core_candidate': any(kind != 'list' for _, kind in candidates),
                        'has_list_candidate': any(kind == 'list' for _, kind in candidates)})
    summary = {}
    for year in ('2024', '2025', '2026', 'all'):
        rows = [r for r in windows if year == 'all' or r['date'].startswith(year)]
        missed = [r for r in rows if r['stage'] == 'candidate_no_hold']
        summary[year] = {'windows': len(rows), 'stages': dict(Counter(r['stage'] for r in rows)),
                         'candidate_no_hold_core': sum(r['has_core_candidate'] for r in missed),
                         'candidate_no_hold_list': sum(r['has_list_candidate'] for r in missed)}
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_be.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/trader_replication/system.py',
             'studies/martin_luk/notes/trades.csv')
    out = dict(dataset_digest=D.A['digest'], summary=summary, windows=windows,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_be.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
