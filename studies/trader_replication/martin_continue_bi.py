"""Continuation BI: factorial control of position cap and stale rotation."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import numpy as np

from . import compare, panels
from .martin_continue_a import required_fields
from .martin_continue_bh import after_rotation, window_held
from .martin_strong import Data
from .martin_strong_scan import HOLD, account, active, f1_rules, forward_close, hold_sim, name_score, u1_entries


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
    cases = {'U1': rules, 'AY1': replace(rules, max_open=11),
             'BH1': replace(rules, rotate_below=.02, rotate_min_days=3),
             'BI1': replace(rules, max_open=11, rotate_below=.02, rotate_min_days=3)}
    i0 = int(np.searchsorted(D.A['days'], panels.WINDOW[0]))
    i1 = int(np.searchsorted(D.A['days'], panels.WINDOW[1], side='right'))
    result = {}
    for name, ru in cases.items():
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
             'studies/trader_replication/martin_continue_bi.py', 'studies/trader_replication/martin_strong_scan.py',
             'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), results=result,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_bi.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
