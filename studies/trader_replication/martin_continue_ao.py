"""Continuation AO: compare U1 and SAT's actual list-trade paths."""
from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np

from . import panels, system
from .martin_continue_a import required_fields
from .martin_continue_ak import describe
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, name_score, u1_entries


def summarize(rows):
    closed = [t for t in rows if t['why'] != 'end']
    out = describe(closed)
    out.update(open_at_end=len(rows) - len(closed),
               mean_ret=float(np.mean([t['ret'] for t in closed])) if closed else None,
               pnl_in_initial_equity=float(sum(t['pnl'] for t in closed)),
               exit_reasons=dict(Counter(t['why'] for t in closed)))
    return out


def main():
    D = Data()
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    original = u1_entries(D, F, H, score)
    satellite = [[e for e in row if e[5] == 'list'] for row in original]
    del F, M, score, H
    rules = f1_rules(D, 6, (1, 3))
    px, ema = D.base.px(D.A), D.base.ema_inputs(D.A, D.pool, rules)
    trades = {}
    for name, book in (('U1', original), ('SAT', satellite)):
        _, _, tr = system.simulate(px, ema, rules, book, *panels.WINDOW)
        trades[name] = [t for t in tr if t['kind'] == 'list']
    result = {}
    for year in ('2024', '2025', '2026'):
        rows = {name: [t for t in tr if t['entry'].startswith(year)] for name, tr in trades.items()}
        keyed = {}
        for name, tr in rows.items():
            keyed[name] = {(t['entry'], t['code'], t['kind']): t for t in tr}
            if len(keyed[name]) != len(tr):
                raise ValueError(f'duplicate entry for {name} in {year}')
        u, s = set(keyed['U1']), set(keyed['SAT'])
        closed = [k for k in sorted(u & s) if keyed['U1'][k]['why'] != 'end' and keyed['SAT'][k]['why'] != 'end']
        result[year] = {'U1': summarize(rows['U1']), 'SAT': summarize(rows['SAT']),
                        'overlap': {'common': len(u & s), 'u1_only': len(u - s), 'sat_only': len(s - u),
                                    'both_closed': len(closed),
                                    'u1_common': summarize([keyed['U1'][k] for k in closed]),
                                    'sat_common': summarize([keyed['SAT'][k] for k in closed])}}
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_ak.py',
             'studies/trader_replication/martin_continue_ao.py', 'studies/trader_replication/martin_strong_scan.py',
             'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), by_entry_year=result,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_ao.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
