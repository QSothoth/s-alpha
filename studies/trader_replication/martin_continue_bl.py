"""Continuation BL: distinguish position counts from simulated execution legs."""
from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path

from . import panels, system
from .martin_continue_a import required_fields
from .martin_continue_b import support_book
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, longs, merge, name_score, nl_rules, pool_book2, pool_book3, u1_entries


def counts(trades, year):
    sides = {'long': Counter(), 'short': Counter()}
    for t in trades:
        row = sides['long' if t['side'] > 0 else 'short']
        if t['entry'].startswith(year):
            row['positions_opened'] += 1
        if t['exit'].startswith(year) and t['why'] != 'end':
            row['positions_closed'] += 1
        executions = t['executions']
        for i, execution in enumerate(executions):
            if not execution['time'].startswith(year):
                continue
            action = execution['action']
            if action == 'entry':
                row['entry'] += 1
            elif action == 'add':
                row['add'] += 1
            elif action == 'end':
                row['mark_end'] += 1
            elif t['why'] != 'end' and i == len(executions) - 1:
                row['final_exit'] += 1
            else:
                row['partial_exit'] += 1
    result = {}
    for side, row in sides.items():
        result[side] = {k: int(row[k]) for k in ('positions_opened', 'positions_closed', 'entry', 'add',
                                                  'partial_exit', 'final_exit', 'mark_end')}
        result[side]['exit_legs'] = int(row['partial_exit'] + row['final_exit'])
        result[side]['execution_events'] = int(row['entry'] + row['add'] + row['partial_exit'] + row['final_exit'])
    return result


def main():
    root = Path(__file__).resolve().parents[2]
    prior = json.loads((root / 'studies/trader_replication/reports/gap_review/strong_continue_ay.json').read_text())
    D = Data()
    if D.A['digest'] != prior['dataset_digest']:
        raise ValueError('frozen dataset differs from AY')
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    original = u1_entries(D, F, H, score)
    d1 = pool_book3(D, F, H, score, 8.0, False, .03)
    broad = pool_book2(D, F, H, score, True, 8.0, None, False)
    limits, _ = support_book(D, broad, d1)
    b2, reg = merge(d1, limits), longs(D.reg)
    del F, M, score, H, d1, broad, limits
    rules = f1_rules(D, 6, (1, 3))
    reg_rules = nl_rules(D, 6)
    b2_rules = nl_rules(D, 6, trail='e9')
    b2_rules = replace(b2_rules, intraday_kinds=tuple(b2_rules.intraday_kinds) + ('lim',))
    px = D.base.px(D.A)
    result = {}
    for name, book, ru in (('U1', original, rules), ('AY1', original, replace(rules, max_open=11)),
                           ('REG6', reg, reg_rules), ('B2', b2, b2_rules)):
        ema = D.base.ema_inputs(D.A, D.pool, ru)
        curve, dates, trades = system.simulate(px, ema, ru, book, *panels.WINDOW, audit=True)
        years = system.stats(curve, dates, trades)['by_year']
        if name in ('U1', 'AY1') and any(abs(years[y] - prior['results'][name]['metrics']['by_year'][y]) > 1e-10 for y in years):
            raise AssertionError(f'{name} path differs from AY')
        result[name] = {'by_year': years, '2025': counts(trades, '2025')}
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_b.py',
             'studies/trader_replication/martin_continue_bl.py', 'studies/trader_replication/martin_strong_scan.py',
             'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), results=result,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_bl.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
