"""Continuation AA: loss mechanisms for the preregistered Z1 and B2 accounts."""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import numpy as np

from . import gate, panels
from .martin_continue_a import required_fields
from .martin_continue_b import support_book
from .martin_continue_z import waiting_book
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, hold_sim, merge, name_score, nl_rules, pool_book2, pool_book3


def summary(trades, year):
    selected = [t for t in trades if t['entry'].startswith(year)]
    closed = [t for t in selected if t['why'] != 'end']
    wins = [t for t in closed if t['ret'] > 0]
    losses = [t for t in closed if t['ret'] <= 0]
    reasons = {}
    for why in sorted({t['why'] for t in losses}):
        rows = [t for t in losses if t['why'] == why]
        reasons[why] = dict(n=len(rows), mean_ret=float(np.mean([t['ret'] for t in rows])),
                            pnl=float(sum(t['pnl'] for t in rows)))
    gaps = [t for t in losses if t['why'] == 'gap_stop']
    penetrations = []
    for t in gaps:
        ex = [e for e in t['executions'] if e['action'] == 'gap_stop']
        if len(ex) != 1:
            raise ValueError('A completed gap-stop must have exactly one gap-stop execution')
        penetrations.append(float((t['stop'] - ex[0]['price']) / t['fill']))
    return dict(entries=len(selected), open_at_end=len(selected)-len(closed), closed=len(closed),
                win=float(len(wins) / len(closed)) if closed else None,
                avg_win=float(np.mean([t['ret'] for t in wins])) if wins else None,
                avg_loss=float(np.mean([t['ret'] for t in losses])) if losses else None,
                mean_ret=float(np.mean([t['ret'] for t in closed])) if closed else None,
                stop_width_median=float(np.median([t['risk_pct'] for t in closed])) if closed else None,
                loss_days=float(np.mean([t['days'] for t in losses])) if losses else None,
                win_days=float(np.mean([t['days'] for t in wins])) if wins else None,
                loss_reasons=reasons, gap_fraction=float(len(gaps)/len(losses)) if losses else None,
                gap_penetration_median=float(np.median(penetrations)) if penetrations else None,
                gap_penetration_p90=float(np.percentile(penetrations, 90)) if penetrations else None)


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
    result = {}
    for name, book in (('B2', b2), ('Z1', wait)):
        st, trades = D.base.run(D.A, book, panels.WINDOW, D.pool, ru, placebo=0, audit=True)
        result[name] = dict(by_year=st['by_year'], years={y: summary(trades, y) for y in ('2024','2025','2026')},
                            fills=gate.check_fills(D.A, trades), win_gate=gate.check_win(trades))
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_b.py',
             'studies/trader_replication/martin_continue_z.py', 'studies/trader_replication/martin_continue_aa.py',
             'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), results=result,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_aa.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
