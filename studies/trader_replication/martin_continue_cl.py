"""CL: compare fixed accounts without mechanical same-name pyramiding."""
from collections import Counter
from dataclasses import replace
import gc
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from . import compare, panels, system, ticket_t4, watchlist
from .martin_continue_a import required_fields
from .martin_continue_bm import describe
from .martin_continue_bq import _ROLL_MEAN, activity_ranks, chunked_roll_mean
from .martin_continue_bt import fidelity
from .martin_continue_ca import books
from .martin_strong import Data
from .martin_strong_scan import active, f1_rules


def without_adds(rules, all_kinds=False):
    if rules.add_signal:
        raise ValueError('signal adds require a separate audit')
    management = {k: dict(v) for k, v in rules.management_by_kind.items()}
    if all_kinds:
        for policy in management.values():
            policy.update(add_levels=(), add_r=0.)
        return replace(rules, add_levels=(), add_r=0., management_by_kind=management)
    management['list'] = {**management.get('list', {}), 'add_levels': (), 'add_r': 0.}
    return replace(rules, management_by_kind=management)


def account(D, book, rules):
    px, em = D.base.px(D.A), D.base.ema_inputs(D.A, D.pool, rules)
    track = {}
    curve, dates, trades = system.simulate(px, em, rules, book, *panels.WINDOW, audit=True, track=track)
    lo = int(np.searchsorted(D.A['days'], panels.WINDOW[0]))
    hi = int(np.searchsorted(D.A['days'], panels.WINDOW[1], side='right'))
    metrics = compare.metrics(curve, dates, trades, book, lo, hi)
    metrics['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in trades) for y in ('2024', '2025', '2026')}
    metrics['max_close_positions'] = max(track['open'])
    metrics['average_close_positions'] = float(np.mean(track['open']))
    metrics['invested_basis'] = describe([t for t in trades if t['why'] != 'end'], 'ret_invested')
    adds = Counter((e['time'][:4], t['kind']) for t in trades for e in t['executions'] if e['action'] == 'add')
    return {'metrics': metrics, 'fidelity': fidelity(D, trades),
            'add_executions': {':'.join(k): v for k, v in sorted(adds.items())}}


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
    u1, _ = books(D, fields, mask, 'H3')
    del fields, mask
    gc.collect()
    lever = f1_rules(D, 6, (1, 3))
    limited = replace(lever, max_open=11)
    cases = {'U1': lever, 'CL1': without_adds(lever), 'CL2': without_adds(lever, True),
             'AY1': limited, 'CL3': without_adds(limited), 'CL4': without_adds(limited, True)}
    results = {}
    for name, rules in cases.items():
        print('account', name, flush=True)
        results[name] = account(D, u1, rules)
    prior = json.loads((root / 'studies/trader_replication/reports/gap_review/strong_continue_bz.json').read_text())['results']
    for name in ('U1', 'AY1'):
        for year in ('2024', '2025', '2026'):
            actual, old = results[name]['metrics'], prior[name]['metrics']
            if abs(actual['by_year'][year] - old['by_year'][year]) > 1e-10 or actual['entries_by_year'][year] != old['entries_by_year'][year]:
                raise AssertionError(f'{name} {year} baseline differs from BZ')
    for name in ('CL1', 'CL3'):
        if any(key.endswith(':list') for key in results[name]['add_executions']):
            raise AssertionError(f'{name} contains an actual list add')
    for name in ('CL2', 'CL4'):
        if results[name]['add_executions']:
            raise AssertionError(f'{name} contains an actual add')
    paths = ('studies/trader_replication/martin_continue_cl.py', 'studies/trader_replication/martin_continue_a.py',
             'studies/trader_replication/martin_continue_ca.py', 'studies/trader_replication/martin_continue_bm.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/trader_replication/system.py')
    out = {'dataset_digest': D.A['digest'], 'window': list(panels.WINDOW), 'results': results,
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}}
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_cl.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
