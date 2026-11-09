"""Continuation C: identical B2 signals under Martin-like position limits."""
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
from .martin_strong_scan import HOLD, account, active, forward_close, hold_sim, merge, name_score, nl_rules, pool_book2, pool_book3


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
    del F, M, score, H, broad, limits
    forward_close(D)
    def rules(n, **kw):
        ru = nl_rules(D, n, trail='e9')
        return replace(ru, intraday_kinds=tuple(ru.intraday_kinds) + ('lim',), margin_rate=.07, **kw)
    high = rules(11, risk=.005, risk_low=.005, max_position=.30, max_gross=2.8)
    fixed = rules(7, max_position=.25, max_gross=1.75)
    res = {}
    for name, book, ru in (('C0', d1, high), ('C1', b2, high), ('C2', b2, fixed)):
        fidelity = account(D, book, ru, name)
        track = {}
        st, trades = D.base.run(D.A, book, panels.WINDOW, D.pool, ru, placebo=0, audit=True, track=track)
        i0 = int(np.searchsorted(D.A['days'], panels.WINDOW[0]))
        i1 = int(np.searchsorted(D.A['days'], panels.WINDOW[1], side='right'))
        days = D.A['days'][i0:i1]
        metrics = compare.metrics(st['_curve'], days, trades, book, i0, i1)
        dates = np.asarray(days).astype(str)
        gross = np.asarray(track['gross'])[-len(days):]
        opened = np.asarray(track['open'])[-len(days):]
        metrics['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in trades) for y in ('2024', '2025', '2026')}
        metrics['gross_by_year'] = {y: float(gross[np.char.startswith(dates, y)].mean()) for y in ('2024', '2025', '2026')}
        metrics['open_by_year'] = {y: float(opened[np.char.startswith(dates, y)].mean()) for y in ('2024', '2025', '2026')}
        res[name] = dict(metrics=metrics, fidelity=fidelity)
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_b.py',
             'studies/trader_replication/martin_continue_c.py', 'studies/trader_replication/system.py')
    result = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW),
                  code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}, results=res)
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_c.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
