"""CJ: compare EMA9 stop-only exits with fixed account baselines."""
from dataclasses import replace
import gc
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from . import panels, ticket_t4, watchlist
from .martin_continue_a import required_fields
from .martin_continue_bq import _ROLL_MEAN, activity_ranks, chunked_roll_mean
from .martin_continue_bz import run
from .martin_continue_ca import books
from .martin_strong import Data
from .martin_strong_scan import active, f1_rules, nl_rules


def list_ema_stop(rules):
    if rules.trail_after_trim or rules.trail_alt or rules.stop_ema_buffer >= 0:
        raise ValueError('baseline has an incompatible global trail override')
    management = dict(rules.management_by_kind)
    management['list'] = {**management.get('list', {}), 'trail': 'e9', 'stop_ema_only': True,
                          'stop_ema_buffer': .03, 'arm_trail_on_entry': True}
    return replace(rules, management_by_kind=management)


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
    u1, sat = books(D, fields, mask, 'H3')
    del fields, mask
    gc.collect()
    lever = f1_rules(D, 6, (1, 3))
    limited = replace(lever, max_open=11)
    plain = nl_rules(D, 6)
    cases = {'U1': (u1, lever), 'CJ1': (u1, list_ema_stop(lever)),
             'AY1': (u1, limited), 'CJ2': (u1, list_ema_stop(limited)),
             'SAT6': (sat, plain), 'CJ3': (sat, list_ema_stop(plain))}
    results = {}
    for name, (book, rules) in cases.items():
        print('account', name, flush=True)
        results[name] = run(D, book, rules)
    prior = json.loads((root / 'studies/trader_replication/reports/gap_review/strong_continue_bz.json').read_text())['results']
    for name in ('U1', 'AY1', 'SAT6'):
        for year in ('2024', '2025', '2026'):
            actual, old = results[name]['metrics'], prior[name]['metrics']
            if abs(actual['by_year'][year] - old['by_year'][year]) > 1e-10 or actual['entries_by_year'][year] != old['entries_by_year'][year]:
                raise AssertionError(f'{name} {year} baseline differs from BZ')
    paths = ('studies/trader_replication/martin_continue_cj.py', 'studies/trader_replication/martin_continue_a.py',
             'studies/trader_replication/martin_continue_ca.py', 'studies/trader_replication/martin_continue_bz.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/trader_replication/system.py',
             'studies/trader_replication/runner.py')
    old_source = root / 'studies/trader_replication/reports/gap_review/source_pins/system_pre_cj.py.txt'
    out = {'dataset_digest': D.A['digest'], 'window': list(panels.WINDOW), 'results': results,
           'prior_system_sha256': hashlib.sha256(old_source.read_bytes()).hexdigest(),
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}}
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_cj.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
