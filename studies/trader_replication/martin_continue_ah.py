"""Continuation AH: delay U1's list entries to the next open."""
from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import numpy as np

from . import compare, panels
from .martin_continue_a import required_fields
from .martin_strong import Data
from .martin_strong_scan import HOLD, account, active, f1_rules, forward_close, hold_sim, name_score, u1_entries


def delayed_list(D, book):
    out = [[e for e in row if e[5] != 'list'] for row in book]
    counts = Counter()
    for day in range(1, len(book)):
        selected = sorted((e for e in book[day - 1] if e[5] == 'list'), key=lambda e: e[0])[:6]
        year = D.days[day][:4]
        in_window = panels.WINDOW[0] <= D.days[day] <= panels.WINDOW[1]
        for e in selected:
            j, stop = e[1], e[4]
            op, low = D.A['open'][day, j], D.A['low'][day, j]
            def count(label):
                if in_window:
                    counts[(year, label)] += 1
            count('preselected')
            if not np.isfinite(op) or not np.isfinite(low) or op <= 0:
                count('missing')
                continue
            if op <= stop:
                count('open_below_stop')
                continue
            count('fillable')
            day_exit = float(stop) if low <= stop else None
            if day_exit is not None:
                count('day_stop')
            out[day].append((e[0], j, e[2], float(op), stop, 'list', day_exit) + e[7:])
    return out, {':'.join(k): v for k, v in sorted(counts.items())}


def main():
    D = Data()
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    book = u1_entries(D, F, H, score)
    delayed, counts = delayed_list(D, book)
    del F, M, score, H
    forward_close(D)
    rules = f1_rules(D, 6, (1, 3))
    early_rules = replace(rules, intraday_kinds=tuple(rules.intraday_kinds) + ('list',))
    result = {}
    for name, entries, ru in (('U1', book, rules), ('AH1', delayed, early_rules)):
        fidelity = account(D, entries, ru, name)
        st, trades = D.base.run(D.A, entries, panels.WINDOW, D.pool, ru, placebo=0, audit=True)
        i0 = int(np.searchsorted(D.A['days'], panels.WINDOW[0]))
        i1 = int(np.searchsorted(D.A['days'], panels.WINDOW[1], side='right'))
        metrics = compare.metrics(st['_curve'], D.A['days'][i0:i1], trades, entries, i0, i1)
        metrics['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in trades) for y in ('2024', '2025', '2026')}
        result[name] = {'metrics': metrics, 'fidelity': fidelity}
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_ah.py',
             'studies/trader_replication/martin_strong.py', 'studies/trader_replication/martin_strong_scan.py',
             'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), candidate_counts=counts, results=result,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_ah.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
