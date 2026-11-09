"""Continuation J: preregistered prior-close market-state exit switches."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import numpy as np

from . import compare, panels
from .martin_continue_a import required_fields
from .martin_continue_b import support_book
from .martin_list import ema
from .martin_strong import Data, bench
from .martin_strong_scan import HOLD, account, active, breadth_scale, forward_close, hold_sim, merge, name_score, nl_rules, pool_book2, pool_book3


def market_states(D, F):
    _, breadth = breadth_scale(D, F)
    valid = np.zeros(len(D.days), bool)
    for d in range(1, len(D.days)):
        valid[d] = np.sum(D.U[d] & np.isfinite(F['act20'][d - 1])) > 100
    prior_valid = np.concatenate([[False], valid[:-1]])
    weak_breadth = prior_valid & (breadth < .5)
    q = bench(D.days, 'QQQ')
    e = ema(q[:, None], 21)[:, 0]
    weak_q = np.concatenate([[False], np.isfinite(q[:-1]) & np.isfinite(e[:-1]) & (q[:-1] < e[:-1])])
    return weak_breadth, weak_q


def main():
    D = Data()
    F = required_fields(D)
    weak_breadth, weak_q = market_states(D, F)
    D.A['weak_breadth'] = weak_breadth
    D.A['weak_qqq'] = weak_q
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    d1 = pool_book3(D, F, H, score, 8.0, False, .03)
    broad = pool_book2(D, F, H, score, True, 8.0, None, False)
    limits, _ = support_book(D, broad, d1)
    book = merge(d1, limits)
    del F, M, score, H, broad, d1, limits
    forward_close(D)
    result = {}
    for name, trail, state in (('B2', 'e9', ''), ('H1', 'e21', ''), ('J1', 'e21', 'weak_breadth'), ('J2', 'e21', 'weak_qqq')):
        ru = nl_rules(D, 6, trail=trail)
        ru = replace(ru, intraday_kinds=tuple(ru.intraday_kinds) + ('lim',),
                     trail_alt='e9' if state else '', trail_alt_days=state)
        fidelity = account(D, book, ru, name)
        st, trades = D.base.run(D.A, book, panels.WINDOW, D.pool, ru, placebo=0, audit=True)
        i0 = int(np.searchsorted(D.A['days'], panels.WINDOW[0]))
        i1 = int(np.searchsorted(D.A['days'], panels.WINDOW[1], side='right'))
        metrics = compare.metrics(st['_curve'], D.A['days'][i0:i1], trades, book, i0, i1)
        metrics['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in trades) for y in ('2024', '2025', '2026')}
        result[name] = dict(metrics=metrics, fidelity=fidelity)
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_b.py',
             'studies/trader_replication/martin_continue_j.py', 'studies/trader_replication/system.py')
    market_by_year = {}
    for y in ('2024', '2025', '2026'):
        ix = np.array([i for i, day in enumerate(D.days) if day.startswith(y) and panels.WINDOW[0] <= day <= panels.WINDOW[1]])
        market_by_year[y] = dict(breadth_weak_days=int(weak_breadth[ix].sum()), qqq_weak_days=int(weak_q[ix].sum()), sessions=len(ix))
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), market_by_year=market_by_year, results=result,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_j.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
