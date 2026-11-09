"""Continuation Z: prior-close candidate orders filled at the next session's close."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import numpy as np

from . import compare, panels
from .martin_continue_a import required_fields
from .martin_continue_b import support_book
from .martin_continue_w import priority
from .martin_strong import Data, lag
from .martin_strong_scan import HOLD, account, active, forward_close, hold_sim, longs, merge, name_score, nl_rules, pool_book2, pool_book3


def waiting_book(D, broad):
    """Select at prior close; only the closing fill price is read on the entry date."""
    width = np.maximum(.01, np.minimum(.025, lag(D.adr) / 2))
    out = [[] for _ in D.days]
    for d in range(1, len(D.days)):
        es = sorted((e for e in broad[d-1] if np.isfinite(width[d,e[1]])), key=lambda e: e[0])[:6]
        for e in es:
            j = e[1]
            fill = D.A['close'][d,j]
            if np.isfinite(fill) and fill > 0:
                out[d].append((e[0], j, 1, float(fill), float(fill * (1-width[d,j])), 'wait'))
    return out


def main():
    D = Data()
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    d1 = pool_book3(D, F, H, score, 8.0, False, .03)
    broad = pool_book2(D, F, H, score, True, 8.0, None, False)
    limits, _ = support_book(D, broad, d1)
    wait = waiting_book(D, broad)
    b2 = merge(d1, limits)
    combined = merge(priority(b2, 0.0), priority(wait, 1.0))
    reg = longs(D.reg)
    del F, M, score, H, broad, d1, limits
    forward_close(D)
    reg_rules = nl_rules(D, 6)
    other_rules = replace(nl_rules(D, 6, trail='e9'), intraday_kinds=tuple(reg_rules.intraday_kinds) + ('lim',))
    result = {}
    for name, book, ru in (('REG6', reg, reg_rules), ('B2', b2, other_rules), ('Z1', wait, other_rules), ('Z2', combined, other_rules)):
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
             'studies/trader_replication/martin_continue_w.py', 'studies/trader_replication/martin_continue_z.py',
             'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), results=result,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_z.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
