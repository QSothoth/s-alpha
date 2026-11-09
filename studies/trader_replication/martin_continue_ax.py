"""Continuation AX: apply Martin's fast-stock ADR proxy to U1 list signals."""
from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np

from . import compare, panels
from .martin_continue_a import required_fields
from .martin_strong import Data
from .martin_strong_scan import HOLD, account, active, f1_rules, forward_close, hold_sim, name_score, u1_entries


def fast_books(D, book):
    hard, priority, counts = [], [], Counter()
    for day, row in enumerate(book):
        a, b = [], []
        for e in row:
            if e[5] != 'list':
                a.append(e)
                b.append(e)
                continue
            value = D.adr[day - 1, e[1]] if day else float('nan')
            status = 'missing' if not np.isfinite(value) else ('eligible' if value > .05 else 'ineligible')
            if panels.WINDOW[0] <= D.days[day] <= panels.WINDOW[1]:
                counts[(D.days[day][:4], status)] += 1
            eligible = status == 'eligible'
            if eligible:
                a.append(e)
            order = e[0][:-1] + (0.0 if eligible else 1.0, e[0][-1])
            b.append((order,) + e[1:])
        hard.append(a)
        priority.append(b)
    return hard, priority, {':'.join(k): v for k, v in sorted(counts.items())}


def main():
    D = Data()
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    original = u1_entries(D, F, H, score)
    hard, priority, counts = fast_books(D, original)
    del F, M, score, H
    forward_close(D)
    rules = f1_rules(D, 6, (1, 3))
    i0 = int(np.searchsorted(D.A['days'], panels.WINDOW[0]))
    i1 = int(np.searchsorted(D.A['days'], panels.WINDOW[1], side='right'))
    result = {}
    for name, entries in (('U1', original), ('AX1', hard), ('AX2', priority)):
        fidelity = account(D, entries, rules, name)
        st, trades = D.base.run(D.A, entries, panels.WINDOW, D.pool, rules, placebo=0, audit=True)
        metrics = compare.metrics(st['_curve'], D.A['days'][i0:i1], trades, entries, i0, i1)
        metrics['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in trades) for y in ('2024', '2025', '2026')}
        result[name] = {'metrics': metrics, 'fidelity': fidelity}
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_ax.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), candidate_counts=counts, results=result,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_ax.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
