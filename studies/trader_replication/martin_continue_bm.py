"""Continuation BM: 2025 closed-position statistics under two return bases."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import numpy as np

from . import panels, system
from .martin_continue_a import required_fields
from .martin_continue_b import support_book
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, longs, merge, name_score, nl_rules, pool_book2, pool_book3, u1_entries


def describe(rows, key):
    values = np.asarray([t[key] for t in rows], dtype=float)
    win = values > 0
    wins, losses = values[win], values[~win]
    mean_win = float(wins.mean()) if len(wins) else None
    mean_loss = float(losses.mean()) if len(losses) else None
    return {'n': len(rows), 'wins': len(wins), 'nonwins': len(losses), 'zeros': int(np.sum(values == 0)),
            'win_rate': float(win.mean()) if len(rows) else None,
            'avg_win': mean_win, 'avg_loss': mean_loss,
            'payoff': mean_win / -mean_loss if mean_win is not None and mean_loss is not None and mean_loss < 0 else None,
            'mean_ret': float(values.mean()) if len(values) else None,
            'avg_days_win': float(np.mean([t['days'] for t, w in zip(rows, win) if w])) if len(wins) else None,
            'avg_days_nonwin': float(np.mean([t['days'] for t, w in zip(rows, win) if not w])) if len(losses) else None}


def main():
    root = Path(__file__).resolve().parents[2]
    prior = json.loads((root / 'studies/trader_replication/reports/gap_review/strong_continue_bl.json').read_text())
    D = Data()
    if D.A['digest'] != prior['dataset_digest']:
        raise ValueError('frozen dataset differs from BL')
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
        curve, dates, trades = system.simulate(px, ema, ru, book, *panels.WINDOW)
        years = system.stats(curve, dates, trades)['by_year']
        if any(abs(years[y] - prior['results'][name]['by_year'][y]) > 1e-10 for y in years):
            raise AssertionError(f'{name} path differs from BL')
        closed = [t for t in trades if t['exit'].startswith('2025') and t['why'] != 'end']
        groups = {'all': closed, 'long': [t for t in closed if t['side'] > 0],
                  'short': [t for t in closed if t['side'] < 0]}
        result[name] = {k: {'initial_basis': describe(rows, 'ret'), 'invested_basis': describe(rows, 'ret_invested')}
                        for k, rows in groups.items()}
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_b.py',
             'studies/trader_replication/martin_continue_bm.py', 'studies/trader_replication/martin_strong_scan.py',
             'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), results=result,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_bm.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
