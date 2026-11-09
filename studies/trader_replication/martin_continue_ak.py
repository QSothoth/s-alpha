"""Continuation AK: pair actual AJ/AH list trades by their original signal."""
from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import numpy as np

from . import panels
from .martin_continue_a import required_fields
from .martin_continue_ah import delayed_list
from .martin_continue_aj import fixed_six
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, name_score, u1_entries


def describe(rows):
    ret = np.asarray([t['ret'] for t in rows], dtype=float)
    wins, losses = ret[ret > 0], ret[ret <= 0]
    return {'n': len(rows), 'win': float((ret > 0).mean()) if len(ret) else None,
            'avg_win': float(wins.mean()) if len(wins) else None,
            'avg_loss': float(losses.mean()) if len(losses) else None,
            'avg_days': float(np.mean([t['days'] for t in rows])) if rows else None,
            'median_risk_pct': float(np.median([t['risk_pct'] for t in rows])) if rows else None}


def main():
    D = Data()
    F = required_fields(D)
    M = active(D, F)
    S = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(S, 12, 36)
    original = u1_entries(D, F, H, S)
    aj, (ah, _) = fixed_six(original), delayed_list(D, original)
    del F, M, S, H, original
    rules = f1_rules(D, 6, (1, 3))
    early_rules = replace(rules, intraday_kinds=tuple(rules.intraday_kinds) + ('list',))
    pairs = []
    for book, ru, delayed in ((aj, rules, False), (ah, early_rules, True)):
        _, tr = D.base.run(D.A, book, panels.WINDOW, D.pool, ru, placebo=0, audit=False)
        keyed = {}
        for t in tr:
            if t['kind'] != 'list':
                continue
            d = D.di[t['entry']] - int(delayed)
            key = (D.days[d], t['code'])
            if key in keyed:
                raise ValueError(f'duplicate signal: {key}')
            keyed[key] = t
        pairs.append(keyed)
    left, right = pairs
    result = {}
    for year in ('2024', '2025', '2026'):
        a = {k for k in left if k[0].startswith(year)}
        b = {k for k in right if k[0].startswith(year)}
        common = a & b
        closed = [k for k in sorted(common) if left[k]['why'] != 'end' and right[k]['why'] != 'end']
        gaps = [right[k]['fill'] / left[k]['fill'] - 1 for k in closed]
        outcomes = Counter(('win' if left[k]['ret'] > 0 else 'loss') + ':' +
                           ('win' if right[k]['ret'] > 0 else 'loss') for k in closed)
        result[year] = {'aj_entries': len(a), 'ah_entries': len(b), 'common': len(common),
                        'aj_only': len(a-b), 'ah_only': len(b-a), 'both_closed': len(closed),
                        'opening_gap_p10_median_p90': np.quantile(gaps, [.1, .5, .9]).tolist() if gaps else None,
                        'outcomes_aj_ah': dict(outcomes), 'aj': describe([left[k] for k in closed]),
                        'ah': describe([right[k] for k in closed])}
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_ah.py',
             'studies/trader_replication/martin_continue_aj.py', 'studies/trader_replication/martin_continue_ak.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), by_signal_year=result,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_ak.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
