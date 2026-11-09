"""Continuation G: registered signals versus B2, holding account rules fixed."""
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
    reg = [[((1.0,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:6]) for e in row] for row in longs(D.reg)]
    del F, M, score, H, broad, d1, limits
    forward_close(D)
    r6 = nl_rules(D, 6)
    r9 = replace(nl_rules(D, 6, trail='e9'), intraday_kinds=tuple(r6.intraday_kinds) + ('lim',))
    result, trades_by_name = {}, {}
    for name, book, ru in (('REG6', reg, r6), ('REG9', reg, r9), ('B2', b2, r9)):
        fidelity = account(D, book, ru, name)
        st, trades = D.base.run(D.A, book, panels.WINDOW, D.pool, ru, placebo=0, audit=True)
        trades_by_name[name] = trades
        i0 = int(np.searchsorted(D.A['days'], panels.WINDOW[0]))
        i1 = int(np.searchsorted(D.A['days'], panels.WINDOW[1], side='right'))
        metrics = compare.metrics(st['_curve'], D.A['days'][i0:i1], trades, book, i0, i1)
        metrics['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in trades) for y in ('2024', '2025', '2026')}
        top = sorted((t for t in trades if t['why'] != 'end'), key=lambda t: -t['pnl'])[:10]
        result[name] = dict(metrics=metrics, fidelity=fidelity,
                            top=[{k: (float(t[k]) if k in ('pnl', 'ret') else t[k])
                                  for k in ('code', 'entry', 'exit', 'kind', 'pnl', 'ret')} for t in top])
    overlap = {}
    for y in ('2024', '2025', '2026'):
        rows = [d for d, date in enumerate(D.days) if date.startswith(y) and panels.WINDOW[0] <= date <= panels.WINDOW[1]]
        reg_signals = {(d, e[1]) for d in rows for e in reg[d]}
        b2_signals = {(d, e[1]) for d in rows for e in b2[d]}
        actual = {name: {(t['entry'], t['code']) for t in tr if t['entry'].startswith(y)} for name, tr in trades_by_name.items()}
        overlap[y] = dict(reg_signals=len(reg_signals), b2_fillable_signals=len(b2_signals),
                          common_signals=len(reg_signals & b2_signals),
                          reg6_entries=len(actual['REG6']), reg9_entries=len(actual['REG9']), b2_entries=len(actual['B2']),
                          reg6_b2_common_entries=len(actual['REG6'] & actual['B2']),
                          reg9_b2_common_entries=len(actual['REG9'] & actual['B2']))
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_b.py',
             'studies/trader_replication/martin_continue_g.py', 'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), overlap=overlap, results=result,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_g.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
