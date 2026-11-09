"""Continuation BD: map U1's blocked SAT trades to Martin's big-move windows."""
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
    original = u1_entries(D, F, H, score)
    satellite = [[e for e in row if e[5] == 'list'] for row in original]
    del F, M, score, H
    rules = f1_rules(D, 6, (1, 3))
    px, ema = D.base.px(D.A), D.base.ema_inputs(D.A, D.pool, rules)
    trades = {}
    for name, book in (('U1', original), ('SAT', satellite)):
        _, _, trades[name] = system.simulate(px, ema, rules, book, *panels.WINDOW)
        if digest(trades[name]) != prior['results'][name]['trades_digest']:
            raise AssertionError(f'{name} path differs from AR')
    blocked = {(r['date'], r['code']) for r in prior['results']['U1']['records']
               if r['reason'] == 'open_pos: val <= 0.001 * equity'}
    sat = [t for t in trades['SAT'] if (t['entry'], t['code']) in blocked and t['kind'] == 'list']
    if len(sat) != len(blocked):
        raise AssertionError('blocked targets do not match SAT actual trades')
    outcomes = {}
    for year in ('2025', '2026'):
        rows = [t for t in sat if t['entry'].startswith(year)]
        outcomes[year] = {'blocked': len(rows), 'closed_at_least_30pct': int(sum(t['why'] != 'end' and t['ret'] >= .3 for t in rows))}
    windows = []
    for d, j, ticker, _, date in D.big:
        if date[:4] not in ('2025', '2026'):
            continue
        peak = d + 1 + int(np.nanargmax(D.h[d + 1:d + 21, j]))
        end = min(d + 10, peak - 1)
        code = str(D.A['codes'][j])
        matching = [t for t in sat if t['code'] == code and d <= D.di[t['entry']] <= end]
        held = any(t['code'] == code and t['side'] > 0 and D.di[t['entry']] <= end
                   and D.di[t['exit']] >= d for t in trades['U1'])
        windows.append({'date': date, 'ticker': ticker, 'peak': D.days[peak], 'end': D.days[end],
                        'blocked_signals': len(matching),
                        'blocked_at_least_30pct': int(sum(t['why'] != 'end' and t['ret'] >= .3 for t in matching)),
                        'u1_held_in_window': held})
    summary = {}
    for year in ('2025', '2026'):
        rows = [r for r in windows if r['date'].startswith(year)]
        summary[year] = {'windows': len(rows), 'blocked_covered': sum(r['blocked_signals'] > 0 for r in rows),
                         'blocked_big_covered': sum(r['blocked_at_least_30pct'] > 0 for r in rows),
                         'u1_held': sum(r['u1_held_in_window'] for r in rows),
                         'blocked_and_u1_held': sum(r['blocked_signals'] > 0 and r['u1_held_in_window'] for r in rows)}
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_bd.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/trader_replication/system.py',
             'studies/martin_luk/notes/trades.csv')
    out = dict(dataset_digest=D.A['digest'], blocked_outcomes=outcomes, summary=summary, windows=windows,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_bd.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'blocked_outcomes': outcomes, 'summary': summary}, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
