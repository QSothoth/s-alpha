"""Continuation L: dated ledger coverage and the B2 opportunity funnel."""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import numpy as np

from . import panels
from .martin_continue_a import required_fields
from .martin_continue_b import support_book
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, hold_sim, merge, name_score, nl_rules, pool_book2, pool_book3


def main():
    D = Data()
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    d1 = pool_book3(D, F, H, score, 8.0, False, .03)
    broad = pool_book2(D, F, H, score, True, 8.0, None, False)
    limits, _ = support_book(D, broad, d1)
    pending = [set() for _ in D.days]
    for d in range(1, len(D.days) - 1):
        accepted = {e[1] for e in d1[d]}
        eligible = sorted((e for e in broad[d] if e[1] not in accepted and np.isfinite(D.l[d, e[1]])
                           and D.l[d, e[1]] > 0), key=lambda e: e[0])
        if eligible:
            pending[d + 1].add(eligible[0][1])
    book = merge(d1, limits)
    del F, score
    ru = nl_rules(D, 6, trail='e9')
    ru = replace(ru, intraday_kinds=tuple(ru.intraday_kinds) + ('lim',))
    _, trades = D.base.run(D.A, book, panels.WINDOW, D.pool, ru, placebo=0, audit=True)
    actual = {(t['entry'], t['code']) for t in trades}
    all_rows = [t for t in D.base.trades() if t.side == 'long' and t.dated and panels.WINDOW[0] <= t.entry_date <= panels.WINDOW[1]]
    located = [row for row in D.base.located(D.A, all_rows) if row[0].id in {t.id for t in all_rows}]
    loc_ids = {x[0].id for x in located}
    codes = {str(code) for code in D.A['codes']}
    missing = [dict(id=t.id, ticker=t.ticker, entry_date=t.entry_date, precision=t.precision,
                    reason='not_in_panel' if 'US.' + t.ticker not in codes else 'no_bar_in_window') for t in all_rows if t.id not in loc_ids]
    rows = []
    for d, j, ticker, setup, day in D.his:
        bset = {e[1] for e in broad[d]}
        nset = {e[1] for e in d1[d]}
        lset = {e[1] for e in limits[d]}
        conditions = [bool(D.U[d, j]), bool(M[d, j]), bool(H[d, j]), j in bset, j in nset]
        first = next((name for name, ok in zip(('U', 'active', 'H3', 'setup', 'narrow_stop'), conditions) if not ok), 'passed_d1')
        trace = D.h[d + 1:d + 21, j]
        known = len(trace) == 20 and np.isfinite(trace).all() and np.isfinite(D.c[d, j]) and D.c[d, j] > 0
        big = bool(np.max(trace) / D.c[d, j] - 1 >= .5) if known else None
        code = str(D.A['codes'][j])
        held = any(t['code'] == code and t['entry'] <= day <= t['exit'] for t in trades)
        rows.append(dict(day=day, ticker=ticker, setup=setup, big=big, first_lost=first,
                         U=conditions[0], active=conditions[1], H3=conditions[2], setup_signal=conditions[3],
                         d1=conditions[4], prior_limit_order=j in pending[d], limit_touch=j in lset,
                         fillable=conditions[4] or j in lset, bought=(day, code) in actual, held_overlap=held))
    summary = {}
    for year in ('2024', '2025', '2026'):
        yearrows = [r for r in rows if r['day'].startswith(year)]
        sections = {}
        for name, group in (('all', yearrows), ('big_known', [r for r in yearrows if r['big'] is True])):
            sections[name] = dict(n=len(group), counts={k: sum(r[k] for r in group) for k in ('U', 'active', 'H3', 'setup_signal', 'd1', 'prior_limit_order', 'limit_touch', 'fillable', 'bought', 'held_overlap')},
                                  first_lost=dict(Counter(r['first_lost'] for r in group)))
        sections['future_unobservable'] = sum(r['big'] is None for r in yearrows)
        summary[year] = sections
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_b.py',
             'studies/trader_replication/martin_continue_l.py', 'studies/trader_replication/system.py',
             'studies/martin_luk/notes/trades.csv')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), ledger_rows=len(all_rows), located_rows=len(located),
               deduplicated=len(rows), precision=dict(Counter(t.precision for t in all_rows)), missing=missing,
               years=summary, rows=rows, code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_l.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in out.items() if k != 'rows'}, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
