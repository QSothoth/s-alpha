"""Continuation AZ: reset U1 and the eleven-position variant at year start."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import numpy as np

from . import compare, system
from .martin_continue_a import required_fields
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, name_score, u1_entries


def main():
    D = Data()
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    entries = u1_entries(D, F, H, score)
    del F, M, score, H
    rules = f1_rules(D, 6, (1, 3))
    px = D.base.px(D.A)
    result = {}
    for name, ru in (('U1', rules), ('AY1', replace(rules, max_open=11))):
        result[name] = {}
        ema = D.base.ema_inputs(D.A, D.pool, ru)
        for start, end in (('2025-01-02', '2025-12-31'), ('2026-01-02', '2026-10-16')):
            track = {}
            curve, dates, trades = system.simulate(px, ema, ru, entries, start, end, audit=True, track=track)
            i0 = int(np.searchsorted(D.A['days'], start))
            i1 = int(np.searchsorted(D.A['days'], end, side='right'))
            metrics = compare.metrics(curve, dates, trades, entries, i0, i1)
            metrics['actual_entries'] = len(trades)
            metrics['average_close_positions'] = float(np.mean(track['open']))
            metrics['max_close_positions'] = max(track['open'])
            metrics['average_gross'] = float(np.mean(track['gross']))
            result[name][start[:4]] = metrics
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_az.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], results=result,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_az.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
