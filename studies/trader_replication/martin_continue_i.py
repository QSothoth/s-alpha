"""Continuation I: pair actual B2 and H1 entries, and inspect the 2025 equity path."""
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
    del F, M, score, H, broad, d1, limits
    results, trades_by_name = {}, {}
    for name, trail in (('B2', 'e9'), ('H1', 'e21')):
        ru = nl_rules(D, 6, trail=trail)
        ru = replace(ru, intraday_kinds=tuple(ru.intraday_kinds) + ('lim',))
        track = {}
        st, trades = D.base.run(D.A, book, panels.WINDOW, D.pool, ru, placebo=0, audit=True, track=track)
        trades_by_name[name] = trades
        start = int(np.searchsorted(D.A['days'], panels.WINDOW[0]))
        dates = [str(x) for x in D.A['days'][start:start + len(st['_curve'])]]
        curve = st['_curve']
        def boundary(date):
            i = dates.index(date)
            held = [t for t in trades if t['entry'] <= date and (t['exit'] > date or (t['exit'] == date and t['why'] == 'end'))]
            return dict(equity=float(curve[i]), gross=float(track['gross'][i]), open=int(track['open'][i]),
                        carried=len(held), carried_from_2024=sum(t['entry'].startswith('2024') for t in held))
        monthly = {}
        for month in range(1, 13):
            ix = [i for i, date in enumerate(dates) if date.startswith(f'2025-{month:02d}')]
            monthly[f'{month:02d}'] = float(curve[ix[-1]] / (curve[ix[0]-1] if ix[0] else 1) - 1)
        entry_year = {}
        for y in ('2024', '2025', '2026'):
            tr = [t for t in trades if t['entry'].startswith(y)]
            entry_year[y] = dict(count=len(tr), end=sum(t['why'] == 'end' for t in tr),
                                 pnl=float(sum(t['pnl'] for t in tr)))
        results[name] = dict(monthly_2025=monthly, start_2025=boundary('2024-12-31'),
                             end_2025=boundary('2025-12-31'), entry_year=entry_year)
    a, b = ({key(t): t for t in trades_by_name[name] if t['entry'].startswith('2025')} for name in ('B2', 'H1'))
    if len(a) != sum(t['entry'].startswith('2025') for t in trades_by_name['B2']) or len(b) != sum(t['entry'].startswith('2025') for t in trades_by_name['H1']):
        raise ValueError('Duplicate pairing key')
    both = a.keys() & b.keys()
    winners = [k for k in both if a[k]['why'] != 'end' and b[k]['why'] != 'end' and a[k]['ret'] > 0]
    pair = dict(common=len(both), b2_only=len(a.keys() - b.keys()), h1_only=len(b.keys() - a.keys()),
                b2_winners_common=len(winners), winners_still_positive=sum(b[k]['ret'] > 0 for k in winners),
                h1_higher_return=sum(b[k]['ret'] > a[k]['ret'] for k in winners),
                mean_b2_ret=float(np.mean([a[k]['ret'] for k in winners])) if winners else None,
                mean_h1_ret=float(np.mean([b[k]['ret'] for k in winners])) if winners else None,
                mean_b2_days=float(np.mean([a[k]['days'] for k in winners])) if winners else None,
                mean_h1_days=float(np.mean([b[k]['days'] for k in winners])) if winners else None)
    pair = {k: int(v) if isinstance(v, np.integer) else v for k, v in pair.items()}
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_b.py',
             'studies/trader_replication/martin_continue_i.py', 'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), accounts=results, paired_2025=pair,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_i.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
