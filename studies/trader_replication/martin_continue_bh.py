"""Continuation BH: test the existing stale-position rotation in U1."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import numpy as np

from . import compare, panels
from .martin_continue_a import required_fields
from .martin_strong import Data
from .martin_strong_scan import HOLD, account, active, f1_rules, forward_close, hold_sim, name_score, u1_entries


def window_held(D, trades):
    result = {}
    for d, j, _, _, date in D.big:
        peak = d + 1 + int(np.nanargmax(D.h[d + 1:d + 21, j]))
        end = min(d + 10, peak - 1)
        code = str(D.A['codes'][j])
        held = any(t['code'] == code and t['side'] > 0 and D.di[t['entry']] <= end
                   and D.di[t['exit']] >= d for t in trades)
        result.setdefault(date[:4], []).append(bool(held))
    return {year: {'held': sum(rows), 'windows': len(rows)} for year, rows in result.items()}


def after_rotation(D, trades):
    out = {}
    code_index = {str(code): j for j, code in enumerate(D.A['codes'])}
    for year in ('2024', '2025', '2026'):
        rotated = [t for t in trades if t['why'] == 'rotate' and t['exit'].startswith(year)]
        values = []
        for t in rotated:
            d, j = D.di[t['exit']], code_index[t['code']]
            if d + 20 < len(D.c) and np.isfinite(D.c[d + 20, j]) and np.isfinite(D.c[d, j]) and D.c[d, j] > 0:
                values.append(float(D.c[d + 20, j] / D.c[d, j] - 1))
        out[year] = {'rotated': len(rotated), 'observable': len(values), 'unknown': len(rotated) - len(values),
                     'mean_20d': float(np.mean(values)) if values else None,
                     'median_20d': float(np.median(values)) if values else None,
                     'at_least_30pct': sum(v >= .3 for v in values)}
    return out


def main():
    D = Data()
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    entries = u1_entries(D, F, H, score)
    del F, M, score, H
    forward_close(D)
    rules = f1_rules(D, 6, (1, 3))
    i0 = int(np.searchsorted(D.A['days'], panels.WINDOW[0]))
    i1 = int(np.searchsorted(D.A['days'], panels.WINDOW[1], side='right'))
    result = {}
    for name, ru in (('U1', rules), ('BH1', replace(rules, rotate_below=.02, rotate_min_days=3))):
        fidelity = account(D, entries, ru, name)
        track = {}
        st, trades = D.base.run(D.A, entries, panels.WINDOW, D.pool, ru, placebo=0, audit=True, track=track)
        metrics = compare.metrics(st['_curve'], D.A['days'][i0:i1], trades, entries, i0, i1)
        metrics['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in trades) for y in ('2024', '2025', '2026')}
        metrics['average_close_positions'] = float(np.mean(track['open']))
        metrics['max_close_positions'] = max(track['open'])
        result[name] = {'metrics': metrics, 'fidelity': fidelity,
                        'prepeak_ten_day': window_held(D, trades), 'rotation_20d': after_rotation(D, trades)}
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_bh.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), results=result,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_bh.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
