"""Continuation K: pre-entry stock states versus paired B2/H1 realized trade outcomes."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import numpy as np

from . import panels
from .martin_continue_a import required_fields
from .martin_continue_b import support_book
from .martin_continue_d import key
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, hold_sim, merge, name_score, nl_rules, pool_book2, pool_book3


def summarize(rows):
    if not rows:
        return dict(count=0)
    a = np.array([x[0]['ret'] for x in rows])
    b = np.array([x[1]['ret'] for x in rows])
    wins = a > 0
    return dict(count=len(rows), b2_mean=float(a.mean()), h1_mean=float(b.mean()),
                delta=float((b - a).mean()), b2_win=float(wins.mean()), h1_win=float((b > 0).mean()),
                b2_winners=int(wins.sum()), winner_kept=int(np.sum(wins & (b > 0))),
                b2_days=float(np.mean([x[0]['days'] for x in rows])),
                h1_days=float(np.mean([x[1]['days'] for x in rows])))


def main():
    D = Data()
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    d1 = pool_book3(D, F, H, score, 8.0, False, .03)
    broad = pool_book2(D, F, H, score, True, 8.0, None, False)
    limits, _ = support_book(D, broad, d1)
    book = merge(d1, limits)
    ext, stack = F['ext21'], F['stack']
    del F, M, score, H, broad, d1, limits
    trades = {}
    for name, trail in (('B2', 'e9'), ('H1', 'e21')):
        ru = nl_rules(D, 6, trail=trail)
        ru = replace(ru, intraday_kinds=tuple(ru.intraday_kinds) + ('lim',))
        _, t = D.base.run(D.A, book, panels.WINDOW, D.pool, ru, placebo=0, audit=True)
        rows = {key(x): x for x in t}
        if len(rows) != len(t):
            raise ValueError('Duplicate pairing key')
        trades[name] = rows
    a, b = trades['B2'], trades['H1']
    codes = {str(c): i for i, c in enumerate(D.A['codes'])}
    results = {}
    for year in ('2024', '2025', '2026'):
        ka = {k for k in a if k[1].startswith(year)}
        kb = {k for k in b if k[1].startswith(year)}
        common = ka & kb
        both = [k for k in common if a[k]['why'] != 'end' and b[k]['why'] != 'end']
        bins = {factor: {'high': [], 'low': [], 'missing': []} for factor in ('adr5', 'extended1adr', 'stack')}
        for k in both:
            d, j = D.di[k[1]] - 1, codes[k[0]]
            vals = {'adr5': (D.adr[d, j], .05), 'extended1adr': (ext[d, j], 1.0), 'stack': (stack[d, j], 2.0)}
            for name, (v, threshold) in vals.items():
                group = 'missing' if not (np.isfinite(v) and np.isfinite(D.c[d, j])) else 'high' if v >= threshold else 'low'
                bins[name][group].append((a[k], b[k]))
        results[year] = dict(b2_entries=len(ka), h1_entries=len(kb), common=len(common), paired_closed=len(both),
                             b2_only=len(ka - kb), h1_only=len(kb - ka),
                             factors={f: {g: summarize(rows) for g, rows in groups.items()} for f, groups in bins.items()})
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_b.py',
             'studies/trader_replication/martin_continue_k.py', 'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), years=results,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_k.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
