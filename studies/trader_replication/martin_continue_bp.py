"""Continuation BP: list EMA9 exit with and without the eleven-position cap."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import numpy as np

from . import compare, panels
from .martin_continue_a import required_fields
from .martin_continue_bh import window_held
from .martin_strong import Data
from .martin_strong_scan import HOLD, account, active, f1_rules, forward_close, hold_sim, name_score, u1_entries


def list_e9(rules):
    management = dict(rules.management_by_kind)
    management['list'] = {**management.get('list', {}), 'trail': 'e9'}
    return replace(rules, management_by_kind=management)


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
    e9 = list_e9(rules)
    cases = {'U1': rules, 'AY1': replace(rules, max_open=11),
             'BP1': e9, 'BP2': replace(e9, max_open=11)}
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
        result[name] = {'metrics': metrics, 'fidelity': fidelity, 'prepeak_ten_day': window_held(D, trades)}
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_bh.py',
             'studies/trader_replication/martin_continue_bp.py', 'studies/trader_replication/martin_strong.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), results=result,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_bp.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
