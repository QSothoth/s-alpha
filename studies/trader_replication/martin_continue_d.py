"""Continuation D: pair D1 and B2 by actual entry; accounting values are initial equity units."""
from __future__ import annotations

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


def key(trade):
    return trade['code'], trade['entry'], trade['kind']


def reconcile(first, second):
    a, b = {key(t): t for t in first}, {key(t): t for t in second}
    if len(a) != len(first) or len(b) != len(second):
        raise ValueError('Duplicate code, entry date and kind; one-to-one pairing is ambiguous')
    common = a.keys() & b.keys()
    def measure(rows):
        return dict(count=len(rows), positive=int(sum(t['pnl'] > 0 for t in rows)),
                    negative=int(sum(t['pnl'] < 0 for t in rows)),
                    end=sum(t['why'] == 'end' for t in rows), pnl=float(sum(t['pnl'] for t in rows)))
    result = {}
    for year in ('2024', '2025', '2026'):
        co = [k for k in common if k[1].startswith(year)]
        only_a = [t for k, t in a.items() if k not in b and k[1].startswith(year)]
        only_b = [t for k, t in b.items() if k not in a and k[1].startswith(year)]
        result[year] = dict(common=measure([a[k] for k in co]),
                            common_pnl_delta=float(sum(b[k]['pnl'] - a[k]['pnl'] for k in co)),
                            d1_only=measure(only_a), b2_only=measure(only_b),
                            b2_limit_only=measure([t for t in only_b if t['kind'] == 'lim']))
    def winners(rows):
        wins = sorted((t for t in rows if t['pnl'] > 0), key=lambda t: -t['pnl'])
        total = sum(t['pnl'] for t in wins)
        return dict(top2_share=float(sum(t['pnl'] for t in wins[:2]) / total) if total else None,
                    top10_share=float(sum(t['pnl'] for t in wins[:10]) / total) if total else None,
                    top=[dict(code=t['code'], entry=t['entry'], exit=t['exit'], kind=t['kind'],
                              why=t['why'], pnl=float(t['pnl']), ret=float(t['ret'])) for t in wins[:10]])
    return dict(by_entry_year=result, d1=winners(first), b2=winners(second),
                pnl_d1=float(sum(t['pnl'] for t in first)), pnl_b2=float(sum(t['pnl'] for t in second)))


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
    ru = nl_rules(D, 6, trail='e9')
    ru = replace(ru, intraday_kinds=tuple(ru.intraday_kinds) + ('lim',))
    first_stats, first = D.base.run(D.A, d1, panels.WINDOW, D.pool, ru, placebo=0, audit=True)
    second_stats, second = D.base.run(D.A, b2, panels.WINDOW, D.pool, ru, placebo=0, audit=True)
    result = reconcile(first, second)
    result['dataset_digest'] = D.A['digest']
    result['account_total'] = dict(d1=float(first_stats['_curve'][-1] - 1), b2=float(second_stats['_curve'][-1] - 1))
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_b.py',
             'studies/trader_replication/martin_continue_d.py', 'studies/trader_replication/system.py')
    result['code_sha256'] = {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_d.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
