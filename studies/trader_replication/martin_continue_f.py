"""Continuation F: one preregistered change to the H3 list width."""
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
    forward_close(D)
    ru = nl_rules(D, 6, trail='e9')
    ru = replace(ru, intraday_kinds=tuple(ru.intraday_kinds) + ('lim',))
    res = {}
    for name, width in (('B2', 12), ('F1', 20)):
        H = hold_sim(score, width, width * 3)
        d1 = pool_book3(D, F, H, score, 8.0, False, .03)
        broad = pool_book2(D, F, H, score, True, 8.0, None, False)
        limits, orders = support_book(D, broad, d1)
        book = merge(d1, limits)
        fidel = account(D, book, ru, name)
        st, trades = D.base.run(D.A, book, panels.WINDOW, D.pool, ru, placebo=0, audit=True)
        i0 = int(np.searchsorted(D.A['days'], panels.WINDOW[0]))
        i1 = int(np.searchsorted(D.A['days'], panels.WINDOW[1], side='right'))
        metrics = compare.metrics(st['_curve'], D.A['days'][i0:i1], trades, book, i0, i1)
        years = {}
        for y in ('2024', '2025', '2026'):
            rows = [d for d, day in enumerate(D.days) if day.startswith(y) and panels.WINDOW[0] <= day <= panels.WINDOW[1]]
            years[y] = dict(mean_list_size=float(np.mean(H[rows].sum(axis=1))),
                            setups=sum(len(broad[d]) for d in rows), qualified=sum(len(d1[d]) for d in rows),
                            support_orders=sum(orders[d] for d in rows), support_fills=sum(len(limits[d]) for d in rows),
                            entries=sum(t['entry'].startswith(y) for t in trades),
                            limit_entries=sum(t['entry'].startswith(y) and t['kind'] == 'lim' for t in trades))
        res[name] = dict(metrics=metrics, fidelity=fidel, annual=years)
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_b.py',
             'studies/trader_replication/martin_continue_f.py', 'studies/trader_replication/system.py')
    result = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW),
                  code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}, results=res)
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_f.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
