"""Continuation B: next-session support limits, preregistered in PREREG_STRONG.md."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import numpy as np

from . import compare, panels
from .martin_continue_a import required_fields
from .martin_strong import Data
from .martin_strong_scan import HOLD, account, active, forward_close, hold_sim, merge, name_score, nl_rules, pool_book2, pool_book3


def limit_execution(opening, low, level, stop):
    """Return the fill and optional same-day stop for one pre-existing limit."""
    if not all(np.isfinite(v) for v in (opening, low, level, stop)) or opening <= stop:
        return None
    if opening <= level:
        fill = opening
    elif low <= level:
        fill = level
    else:
        return None
    return float(fill), float(stop) if low <= stop else None


def support_book(D, broad, accepted):
    """Prior-close signals excluded by D1 become one-session limit orders."""
    out = [[] for _ in D.days]
    orders = [0] * len(D.days)
    for previous in range(1, len(D.days) - 1):
        selected = {e[1] for e in accepted[previous]}
        d = previous + 1
        candidates = sorted((e for e in broad[previous] if e[1] not in selected
                             and np.isfinite(D.l[previous, e[1]]) and D.l[previous, e[1]] > 0), key=lambda e: e[0])
        for e in candidates[:1]:
            j = e[1]
            stop = float(D.l[previous, j])
            orders[d] += 1
            level = stop * 1.025
            execution = limit_execution(D.o[d, j], D.l[d, j], level, stop)
            if execution is None:
                continue
            fill, day_exit = execution
            out[d].append((e[0], j, 1, fill, stop, 'lim', day_exit))
    return out, orders


def main():
    D = Data()
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    d1 = pool_book3(D, F, H, score, 8.0, False, .03)
    broad = pool_book2(D, F, H, score, True, 8.0, None, False)
    limit, orders = support_book(D, broad, d1)
    del F, M, score, H, broad
    forward_close(D)
    rules = nl_rules(D, 6, trail='e9')
    rules = replace(rules, intraday_kinds=tuple(rules.intraday_kinds) + ('lim',))
    res = {}
    for name, book in (('D1', d1), ('B1', limit), ('B2', merge(d1, limit))):
        fidelity = account(D, book, rules, name)
        st, trades = D.base.run(D.A, book, panels.WINDOW, D.pool, rules, placebo=0, audit=True)
        i0 = int(np.searchsorted(D.A['days'], panels.WINDOW[0]))
        i1 = int(np.searchsorted(D.A['days'], panels.WINDOW[1], side='right'))
        metrics = compare.metrics(st['_curve'], D.A['days'][i0:i1], trades, book, i0, i1)
        metrics['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in trades) for y in ('2024', '2025', '2026')}
        metrics['limit_entries_by_year'] = {y: sum(t['entry'].startswith(y) and t['kind'] == 'lim' for t in trades) for y in ('2024', '2025', '2026')}
        res[name] = dict(metrics=metrics, fidelity=fidelity)
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_b.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/trader_replication/system.py',
             'studies/martin_luk/notes/trades.csv')
    result = dict(window=list(panels.WINDOW), actual_digest=D.A['digest'],
                  code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths},
                  orders_by_year={y: sum(orders[d] for d, day in enumerate(D.days) if day.startswith(y) and panels.WINDOW[0] <= day <= panels.WINDOW[1]) for y in ('2024', '2025', '2026')},
                  filled_candidates_by_year={y: sum(len(limit[d]) for d, day in enumerate(D.days) if day.startswith(y) and panels.WINDOW[0] <= day <= panels.WINDOW[1]) for y in ('2024', '2025', '2026')},
                  results=res)
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_b.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
