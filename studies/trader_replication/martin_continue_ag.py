"""Continuation AG: randomize only U1's order among same-day list candidates."""
import hashlib
import json
from pathlib import Path

import numpy as np

from . import panels, system
from .martin_continue_a import required_fields
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, name_score, u1_entries


def random_list_order(book, rng):
    out = []
    for row in book:
        new = []
        for e in row:
            if e[5] == 'list':
                e = (e[0][:-1] + (float(rng.random()),),) + e[1:]
            new.append(e)
        out.append(new)
    return out


def main():
    D = Data()
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    book = u1_entries(D, F, H, score)
    del F, M, score, H
    rules = f1_rules(D, 6, (1, 3))
    px, ema = D.base.px(D.A), D.base.ema_inputs(D.A, D.pool, rules)

    def run(entries):
        curve, dates, trades = system.simulate(px, ema, rules, entries, *panels.WINDOW)
        stats = system.stats(curve, dates, trades)
        return {'total': float(curve[-1] - 1), 'by_year': stats['by_year'],
                'maxdd': stats['maxdd'],
                'entries_2025': sum(t['entry'].startswith('2025') for t in trades)}

    result = {'seed': 20261101, 'dataset_digest': D.A['digest'], 'original': run(book), 'draws': []}
    rng = np.random.default_rng(result['seed'])
    root = Path(__file__).resolve().parents[2]
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_ag.json'
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_ag.py',
             'studies/trader_replication/martin_strong.py', 'studies/trader_replication/martin_strong_scan.py',
             'studies/trader_replication/system.py')
    result['code_sha256'] = {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}
    for i in range(100):
        result['draws'].append(run(random_list_order(book, rng)))
        if (i + 1) % 10 == 0:
            target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print(f'draws: {i + 1}/100', flush=True)
    print(json.dumps(result['original'], ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
