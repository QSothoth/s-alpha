"""Continuation W: preserve REG6 management and add the B2 opportunity stream."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import numpy as np

from . import compare, panels
from .martin_continue_a import required_fields
from .martin_continue_b import support_book
from .martin_strong import Data
from .martin_strong_scan import HOLD, account, active, forward_close, hold_sim, longs, merge, name_score, nl_rules, pool_book2, pool_book3


def priority(book, value):
    return [[((value,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:]) for e in row] for row in book]


def main():
    D = Data()
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    d1 = pool_book3(D, F, H, score, 8.0, False, .03)
    broad = pool_book2(D, F, H, score, True, 8.0, None, False)
    limits, _ = support_book(D, broad, d1)
    after_open = [[e for e in row if D.o[d, e[1]] > e[4] * 1.025] for d, row in enumerate(limits)]
    b2 = merge(d1, limits)
    reg = priority(longs(D.reg), 0.0)
    combined = merge(reg, priority(merge(d1, after_open), 1.0))
    del F, M, score, H, broad, d1, limits, after_open
    forward_close(D)
    reg_rules = nl_rules(D, 6)
    b2_rules = replace(nl_rules(D, 6, trail='e9'), intraday_kinds=tuple(reg_rules.intraday_kinds) + ('lim',))
    combined_rules = replace(reg_rules, intraday_kinds=tuple(reg_rules.intraday_kinds) + ('lim',),
                             management_by_kind={'list': {'trail': 'e9'}, 'lim': {'trail': 'e9'}})
    result = {}
    for name, book, ru in (('REG6', reg, reg_rules), ('B2', b2, b2_rules), ('W1', combined, combined_rules)):
        fidelity = account(D, book, ru, name)
        st, trades = D.base.run(D.A, book, panels.WINDOW, D.pool, ru, placebo=0, audit=True)
        i0 = int(np.searchsorted(D.A['days'], panels.WINDOW[0]))
        i1 = int(np.searchsorted(D.A['days'], panels.WINDOW[1], side='right'))
        metrics = compare.metrics(st['_curve'], D.A['days'][i0:i1], trades, book, i0, i1)
        metrics['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in trades) for y in ('2024', '2025', '2026')}
        metrics['entries_by_kind_year'] = {y: {kind: sum(t['entry'].startswith(y) and t['kind'] == kind for t in trades)
                                                     for kind in sorted({t['kind'] for t in trades})} for y in ('2024', '2025', '2026')}
        result[name] = dict(metrics=metrics, fidelity=fidelity)
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_b.py',
             'studies/trader_replication/martin_continue_w.py', 'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), results=result,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_w.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
