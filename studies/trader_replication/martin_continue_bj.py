"""Continuation BJ: describe U1 versus rotated-account trade paths."""
from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import numpy as np

from . import panels, system
from .martin_continue_a import required_fields
from .martin_continue_ap import group
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, name_score, u1_entries


def main():
    root = Path(__file__).resolve().parents[2]
    prior = json.loads((root / 'studies/trader_replication/reports/gap_review/strong_continue_bh.json').read_text())
    D = Data()
    if D.A['digest'] != prior['dataset_digest']:
        raise ValueError('frozen dataset differs from BH')
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    entries = u1_entries(D, F, H, score)
    del F, M, score, H
    rules = f1_rules(D, 6, (1, 3))
    px = D.base.px(D.A)
    keyed, all_trades = {}, {}
    for name, ru in (('U1', rules), ('BH1', replace(rules, rotate_below=.02, rotate_min_days=3))):
        ema = D.base.ema_inputs(D.A, D.pool, ru)
        curve, dates, trades = system.simulate(px, ema, ru, entries, *panels.WINDOW)
        years = system.stats(curve, dates, trades)['by_year']
        reference = prior['results'][name]['metrics']['by_year']
        if any(abs(years[y] - reference[y]) > 1e-10 for y in reference):
            raise AssertionError(f'{name} account path differs from BH')
        all_trades[name] = trades
        keyed[name] = {(t['entry'], t['code'], t['side'], t['kind']): t for t in trades}
        if len(keyed[name]) != len(trades):
            raise ValueError(f'duplicate trade key in {name}')
    u, b = set(keyed['U1']), set(keyed['BH1'])
    result = {}
    for year in ('2024', '2025', '2026'):
        year_keys = lambda x: sorted(k for k in x if k[0].startswith(year))
        groups = {}
        for label, name, keys in (('u1_common', 'U1', u & b), ('bh_common', 'BH1', u & b),
                                  ('u1_only', 'U1', u - b), ('bh_only', 'BH1', b - u)):
            rows = [keyed[name][k] for k in year_keys(keys)]
            groups[label] = {**group(rows), 'kinds': dict(Counter(t['kind'] for t in rows))}
        rotated = [t for t in all_trades['BH1'] if t['why'] == 'rotate' and t['exit'].startswith(year)]
        classes = Counter()
        paired = []
        for t in rotated:
            k = (t['entry'], t['code'], t['side'], t['kind'])
            orig = keyed['U1'].get(k)
            if orig is None:
                classes['not_opened_in_u1'] += 1
            elif orig['why'] == 'end':
                classes['u1_open_at_end'] += 1
            elif orig['exit'] <= t['exit']:
                classes['u1_exited_no_later'] += 1
            else:
                classes['u1_exited_later'] += 1
                paired.append((t, orig))
        rotation = {'rotated': len(rotated), 'classes': dict(classes),
                    'bh_paired': group([x for x, _ in paired]), 'u1_paired': group([x for _, x in paired]),
                    'median_extra_days_in_u1': float(np.median([D.di[y['exit']] - D.di[x['exit']] for x, y in paired])) if paired else None}
        result[year] = {'by_entry_year': groups, 'rotation_by_exit_year': rotation}
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_ak.py',
             'studies/trader_replication/martin_continue_ao.py', 'studies/trader_replication/martin_continue_ap.py',
             'studies/trader_replication/martin_continue_bj.py', 'studies/trader_replication/martin_strong_scan.py',
             'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), years=result,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_bj.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
