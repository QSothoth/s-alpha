"""Continuation AB: past downside-gap frequency and later realized outcomes."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import numpy as np

from . import panels
from .martin_continue_a import required_fields
from .martin_continue_b import support_book
from .martin_continue_z import waiting_book
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, hold_sim, merge, name_score, nl_rules, pool_book2, pool_book3


def gap_group(opening, close, day, j):
    if day < 61:
        return 'missing'
    op, previous = opening[day-60:day, j], close[day-61:day-1, j]
    valid = np.isfinite(op) & np.isfinite(previous) & (op > 0) & (previous > 0)
    if valid.sum() < 45:
        return 'missing'
    return 'high' if np.sum(valid & (op <= previous * .97)) >= 3 else 'low'


def describe(rows):
    if not rows:
        return dict(n=0)
    ret = np.array([t['ret'] for t in rows])
    win = ret > 0
    losses = ret[~win]
    return dict(n=len(rows), gap_stop_rate=float(np.mean([t['why'] == 'gap_stop' for t in rows])),
                win=float(win.mean()), mean_ret=float(ret.mean()),
                avg_win=float(ret[win].mean()) if win.any() else None,
                avg_loss=float(losses.mean()) if len(losses) else None,
                stop_width_median=float(np.median([t['risk_pct'] for t in rows])))


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
    del F, M, score, H, d1, broad, limits
    ru = nl_rules(D, 6, trail='e9')
    ru = replace(ru, intraday_kinds=tuple(ru.intraday_kinds) + ('lim',))
    codes = {str(code): j for j, code in enumerate(D.A['codes'])}
    result = {}
    for name, book in (('B2', b2), ('Z1', wait)):
        _, trades = D.base.run(D.A, book, panels.WINDOW, D.pool, ru, placebo=0, audit=True)
        years = {}
        for year in ('2024','2025','2026'):
            tr = [t for t in trades if t['entry'].startswith(year) and t['why'] != 'end']
            groups = {g: [] for g in ('high','low','missing')}
            for t in tr:
                groups[gap_group(D.o, D.c, D.di[t['entry']], codes[t['code']])].append(t)
            years[year] = {g: describe(rows) for g, rows in groups.items()}
        result[name] = years
    ledger = {}
    for year in ('2024','2025','2026'):
        rows = [x for x in D.his if x[4].startswith(year)]
        groups = {g: {'all': 0, 'big': 0, 'unobservable': 0} for g in ('high','low','missing')}
        for d,j,_,_,_ in rows:
            group = gap_group(D.o,D.c,d,j)
            groups[group]['all'] += 1
            future = D.h[d+1:d+21,j]
            if len(future) != 20 or not np.isfinite(future).all() or not (np.isfinite(D.c[d,j]) and D.c[d,j] > 0):
                groups[group]['unobservable'] += 1
            elif np.max(future) / D.c[d,j] - 1 >= .5:
                groups[group]['big'] += 1
        ledger[year] = groups
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py','studies/trader_replication/martin_continue_b.py',
             'studies/trader_replication/martin_continue_z.py','studies/trader_replication/martin_continue_ab.py',
             'studies/trader_replication/system.py','studies/martin_luk/notes/trades.csv')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), results=result, ledger=ledger,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_ab.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
