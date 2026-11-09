"""Continuation AC: filter B2 by the previously observed downside-gap proxy."""
from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import numpy as np

from . import compare, panels
from .martin_continue_a import required_fields
from .martin_continue_ab import gap_group
from .martin_continue_b import support_book
from .martin_strong import Data
from .martin_strong_scan import HOLD, account, active, forward_close, hold_sim, merge, name_score, nl_rules, pool_book2, pool_book3


def filter_book(D, book):
    counts = Counter()
    out = [[] for _ in D.days]
    for day, entries in enumerate(book):
        for entry in entries:
            group = gap_group(D.o, D.c, day, entry[1])
            if panels.WINDOW[0] <= D.days[day] <= panels.WINDOW[1]:
                counts[(D.days[day][:4], entry[5], group)] += 1
            if group == 'high':
                out[day].append(entry)
    return out, {':'.join(k): v for k, v in sorted(counts.items())}


def main():
    D = Data()
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    d1 = pool_book3(D, F, H, score, 8.0, False, .03)
    broad = pool_book2(D, F, H, score, True, 8.0, None, False)
    limits, _ = support_book(D, broad, d1)
    b2 = merge(d1, limits)
    book, counts = filter_book(D, b2)
    del F, M, score, H, broad, d1, limits, b2
    forward_close(D)
    rules = nl_rules(D, 6, trail='e9')
    rules = replace(rules, intraday_kinds=tuple(rules.intraday_kinds) + ('lim',))
    fidelity = account(D, book, rules, 'AC1')
    st, trades = D.base.run(D.A, book, panels.WINDOW, D.pool, rules, placebo=0, audit=True)
    i0 = int(np.searchsorted(D.A['days'], panels.WINDOW[0]))
    i1 = int(np.searchsorted(D.A['days'], panels.WINDOW[1], side='right'))
    metrics = compare.metrics(st['_curve'], D.A['days'][i0:i1], trades, book, i0, i1)
    metrics['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in trades) for y in ('2024', '2025', '2026')}
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_b.py',
             'studies/trader_replication/martin_continue_ab.py', 'studies/trader_replication/martin_continue_ac.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), candidate_counts=counts,
               metrics=metrics, fidelity=fidelity,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_ac.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
