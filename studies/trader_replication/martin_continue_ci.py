"""CI: prioritize the existing R50 higher-low condition within fixed H3 signals."""
from collections import Counter
import gc
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from . import panels, ticket_t4, watchlist
from .martin_continue_a import required_fields
from .martin_continue_bq import _ROLL_MEAN, activity_ranks, chunked_roll_mean
from .martin_continue_bv import daily_name_score, daily_pool_book
from .martin_continue_bz import run
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, merge, nl_rules, sized


def higher_low(lows):
    """R50's prior-low comparison: 1 yes, 0 no, -1 when either interval is empty."""
    out = np.full(lows.shape, -1, dtype=np.int8)
    for day in range(6, len(lows)):
        recent = np.fmin.reduce(lows[max(0, day - 5):day], axis=0)
        older = np.fmin.reduce(lows[max(0, day - 20):day - 5], axis=0)
        valid = ~np.isnan(recent) & ~np.isnan(older)
        out[day, valid] = (recent[valid] > older[valid]).astype(np.int8)
    return out


def prefer_higher_low(book, states):
    out = []
    for day, row in enumerate(book):
        new = []
        for entry in row:
            priority = entry[0]
            ordered = priority[:-1] + (0.0 if states[day, entry[1]] == 1 else 1.0, priority[-1])
            new.append((ordered,) + entry[1:])
        out.append(new)
    return out


def plain(book):
    return [[((2.0,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:6])
             for e in row] for row in book]


def main():
    if os.environ.get('TRADER_DATA_MODE') != 'frozen' or os.environ.get('TRADER_DATA_TAG') != 'trader-data-v1':
        raise ValueError('explicitly select the registered frozen v1 dataset')
    root = Path(__file__).resolve().parents[2]
    old = ticket_t4.ranks
    try:
        ticket_t4.ranks = activity_ranks
        D = Data()
    finally:
        ticket_t4.ranks = old
    pin = json.loads((root / 'studies/trader_replication/DATA_PIN.json').read_text())['trader-data-v1']['us']
    if D.A['digest'] != pin:
        raise ValueError('dataset digest differs from registered v1')
    del D.fp, D.fwd, D.raw
    for key in ('pr21', 'pr63', 'pr126', 'rank_pool', 'stack', 'tight'):
        D.A.pop(key, None)
    D.rk = D.rk.astype(np.int32)
    gc.collect()
    try:
        watchlist.roll_mean = chunked_roll_mean
        fields = required_fields(D)
    finally:
        watchlist.roll_mean = _ROLL_MEAN
    mask = active(D, fields)
    score = daily_name_score(fields, mask, HOLD['H3'])
    holding = hold_sim(score, 12, 36)
    raw = daily_pool_book(D, fields, holding, score)
    del fields, mask, score, holding
    gc.collect()
    states = higher_low(D.A['low'])
    counts = Counter()
    for day, row in enumerate(raw):
        if panels.WINDOW[0] <= D.days[day] <= panels.WINDOW[1]:
            for e in row:
                label = {1: 'eligible', 0: 'other', -1: 'unknown'}[int(states[day, e[1]])]
                counts[(D.days[day][:4], label)] += 1
    preferred = prefer_higher_low(raw, states)
    del states
    lever, unlevered = f1_rules(D, 6, (1, 3)), nl_rules(D, 6)
    cases = {'U1': (merge(D.reg, sized(raw, .5)), lever),
             'CI1': (merge(D.reg, sized(preferred, .5)), lever),
             'SAT6': (plain(raw), unlevered), 'CI2': (plain(preferred), unlevered)}
    del raw, preferred
    gc.collect()
    results = {}
    for name, (book, rules) in cases.items():
        print('account', name, flush=True)
        results[name] = run(D, book, rules)
    prior = json.loads((root / 'studies/trader_replication/reports/gap_review/strong_continue_bz.json').read_text())['results']
    for name in ('U1', 'SAT6'):
        for year in ('2024', '2025', '2026'):
            old, actual = prior[name]['metrics'], results[name]['metrics']
            if abs(actual['by_year'][year] - old['by_year'][year]) > 1e-10 or actual['entries_by_year'][year] != old['entries_by_year'][year]:
                raise AssertionError(f'{name} {year} baseline differs from BZ')
    paths = ('studies/trader_replication/martin_continue_ci.py', 'studies/trader_replication/martin_continue_a.py',
             'studies/trader_replication/martin_continue_bv.py', 'studies/trader_replication/martin_continue_bz.py',
             'studies/martin_luk/replicate.py', 'studies/trader_replication/martin_strong_scan.py',
             'studies/trader_replication/system.py')
    out = {'dataset_digest': D.A['digest'], 'window': list(panels.WINDOW),
           'candidate_counts': {':'.join(k): v for k, v in sorted(counts.items())}, 'results': results,
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}}
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_ci.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
