"""Continuation AL: fixed cost and financing stress scenarios for U1."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import numpy as np

from . import panels, system
from .martin_continue_a import required_fields
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, name_score, u1_entries


def main():
    D = Data()
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    entries = u1_entries(D, F, H, score)
    del F, M, score, H
    rules = f1_rules(D, 6, (1, 3))
    scenarios = {'U1': rules,
                 'AL1': replace(rules, buy_cost=rules.buy_cost * 2, sell_cost=rules.sell_cost * 2),
                 'AL2': replace(rules, margin_rate=rules.margin_rate * 2),
                 'AL3': replace(rules, buy_cost=rules.buy_cost * 2, sell_cost=rules.sell_cost * 2,
                                margin_rate=rules.margin_rate * 2)}
    px = D.base.px(D.A)
    result = {}
    for name, ru in scenarios.items():
        ema = D.base.ema_inputs(D.A, D.pool, ru)
        track = {}
        curve, dates, trades = system.simulate(px, ema, ru, entries, *panels.WINDOW, track=track)
        st = system.stats(curve, dates, trades)
        result[name] = {'total': st['total'], 'by_year': st['by_year'], 'maxdd': st['maxdd'],
                        'entries_2025': sum(t['entry'].startswith('2025') for t in trades),
                        'average_gross': float(np.mean(track['gross'])), 'margin_paid': track['margin'],
                        'buy_cost': ru.buy_cost, 'sell_cost': ru.sell_cost, 'margin_rate': ru.margin_rate,
                        'borrow_rate': ru.borrow_rate}
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_al.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), results=result,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_al.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
