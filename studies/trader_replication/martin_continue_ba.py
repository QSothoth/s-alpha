"""Continuation BA: reset the unlevered REG6 and B2 accounts at year start."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import numpy as np

from . import compare, system
from .martin_continue_a import required_fields
from .martin_continue_b import support_book
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, hold_sim, longs, merge, name_score, nl_rules, pool_book2, pool_book3


def main():
    D = Data()
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    d1 = pool_book3(D, F, H, score, 8.0, False, .03)
    broad = pool_book2(D, F, H, score, True, 8.0, None, False)
    limit, _ = support_book(D, broad, d1)
    b2 = merge(d1, limit)
    reg = longs(D.reg)
    del F, M, score, H, d1, broad, limit
    reg_rules = nl_rules(D, 6)
    b2_rules = nl_rules(D, 6, trail='e9')
    b2_rules = replace(b2_rules, intraday_kinds=tuple(b2_rules.intraday_kinds) + ('lim',))
    px = D.base.px(D.A)
    result = {}
    for name, book, ru in (('REG6', reg, reg_rules), ('B2', b2, b2_rules)):
        result[name] = {}
        ema = D.base.ema_inputs(D.A, D.pool, ru)
        for start, end in (('2025-01-02', '2025-12-31'), ('2026-01-02', '2026-10-16')):
            track = {}
            curve, dates, trades = system.simulate(px, ema, ru, book, start, end, audit=True, track=track)
            i0 = int(np.searchsorted(D.A['days'], start))
            i1 = int(np.searchsorted(D.A['days'], end, side='right'))
            metrics = compare.metrics(curve, dates, trades, book, i0, i1)
            metrics['actual_entries'] = len(trades)
            metrics['average_close_positions'] = float(np.mean(track['open']))
            metrics['max_close_positions'] = max(track['open'])
            metrics['average_gross'] = float(np.mean(track['gross']))
            result[name][start[:4]] = metrics
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_b.py',
             'studies/trader_replication/martin_continue_ba.py', 'studies/trader_replication/martin_strong_scan.py',
             'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], results=result,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_ba.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
