"""Continuation X: two independently funded, three-position sleeves."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import numpy as np

from . import compare, panels
from .martin_continue_a import required_fields
from .martin_continue_b import support_book
from .martin_strong import CUT, Data
from .martin_strong_scan import HOLD, active, hold_sim, longs, merge, name_score, nl_rules, pool_book2, pool_book3


def scale_trade(t, factor):
    out = dict(t)
    out['pnl'] = float(t['pnl']) * factor
    out['executions'] = [dict(e, shares=float(e['shares']) * factor) for e in t.get('executions', [])]
    return out


def fidelity(D, trades):
    located = [x for x in D.base.located(D.A, D.base.trades()) if x[0].side == 'long' and x[0].dated and x[0].entry_date >= panels.WINDOW[0]]
    opened = {(t['code'], t['entry']) for t in trades if t['side'] > 0}
    def got(subset):
        return sum(any((str(D.A['codes'][j]), str(D.A['days'][d])) in opened for d in range(a, z + 1)) for t, j, a, z in subset)
    left = [x for x in located if x[0].entry_date <= CUT]
    right = [x for x in located if x[0].entry_date > CUT]
    idx = {str(c): j for j, c in enumerate(D.A['codes'])}
    held = np.zeros(D.c.shape, bool)
    for t in trades:
        if t['side'] > 0 and t['entry'] in D.di and t['exit'] in D.di:
            held[D.di[t['entry']]:D.di[t['exit']] + 1, idx[t['code']]] = True
    board = 0
    for d, j, _, _, _ in D.big:
        peak = d + 1 + int(np.nanargmax(D.h[d + 1:d + 21, j]))
        board += bool(held[d:peak + 1, j].any())
    return dict(strict=got(left), of=len(left), strict26=got(right), of26=len(right), board=int(board))


def main():
    D = Data()
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    d1 = pool_book3(D, F, H, score, 8.0, False, .03)
    broad = pool_book2(D, F, H, score, True, 8.0, None, False)
    limits, _ = support_book(D, broad, d1)
    after_open = [[e for e in row if D.o[d,e[1]] > e[4] * 1.025] for d,row in enumerate(limits)]
    reg = longs(D.reg)
    b2 = merge(d1, after_open)
    del F, M, score, H, broad, d1, limits, after_open
    reg_rules = nl_rules(D, 3)
    b2_rules = replace(nl_rules(D, 3, trail='e9'), intraday_kinds=tuple(reg_rules.intraday_kinds) + ('lim',))
    first, tr1 = D.base.run(D.A, reg, panels.WINDOW, D.pool, reg_rules, placebo=0, audit=True)
    second, tr2 = D.base.run(D.A, b2, panels.WINDOW, D.pool, b2_rules, placebo=0, audit=True)
    curve = .5 * first['_curve'] + .5 * second['_curve']
    trades = [scale_trade(t, .5) for t in tr1 + tr2]
    i0 = int(np.searchsorted(D.A['days'], panels.WINDOW[0]))
    i1 = int(np.searchsorted(D.A['days'], panels.WINDOW[1], side='right'))
    days = D.A['days'][i0:i1]
    metrics = compare.metrics(curve, days, trades, merge(reg, b2), i0, i1)
    metrics['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in trades) for y in ('2024', '2025', '2026')}
    def sleeve(st, tr, book):
        m = compare.metrics(st['_curve'], days, tr, book, i0, i1)
        return dict(total=m['total'], by_year=m['by_year'], maxdd=m['maxdd'], trades=m['trades'])
    result = dict(metrics=metrics, fidelity=fidelity(D, trades),
                  reg_sleeve=sleeve(first,tr1,reg), b2_sleeve=sleeve(second,tr2,b2))
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_b.py',
             'studies/trader_replication/martin_continue_x.py', 'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), result=result,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_x.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
