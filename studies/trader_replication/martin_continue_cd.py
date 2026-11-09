"""CD: paired cost-protection replays for current and 11-position accounts."""
from dataclasses import replace
import gc
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from . import compare, panels, system, ticket_t4, watchlist
from .martin_continue_a import required_fields
from .martin_continue_bq import _ROLL_MEAN, activity_ranks, chunked_roll_mean
from .martin_continue_bt import fidelity
from .martin_continue_bu import describe
from .martin_continue_ca import books
from .martin_strong import Data
from .martin_strong_scan import active, f1_rules


def added(trade):
    return any(e['action'] == 'add' for e in trade['executions'])


def account(D, book, rules):
    px, em = D.base.px(D.A), D.base.ema_inputs(D.A, D.pool, rules)
    track = {}
    curve, dates, trades = system.simulate(px, em, rules, book, *panels.WINDOW, audit=True, track=track)
    lo = int(np.searchsorted(D.A['days'], panels.WINDOW[0]))
    hi = int(np.searchsorted(D.A['days'], panels.WINDOW[1], side='right'))
    metrics = compare.metrics(curve, dates, trades, book, lo, hi)
    metrics['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in trades) for y in ('2024', '2025', '2026')}
    metrics['max_close_positions'] = max(track['open'])
    groups = {}
    for year in ('2024', '2025', '2026'):
        closed = [t for t in trades if t['why'] != 'end' and t['exit'].startswith(year)]
        groups[year] = {name: describe([t for t in closed if added(t) == is_added])
                        for name, is_added in (('added', True), ('not_added', False))}
        losses = [t['ret_invested'] for t in closed if added(t) and t['ret_invested'] < 0]
        groups[year]['added_loss_invested'] = {'count': len(losses),
            'mean': float(np.mean(losses)) if losses else None,
            'median': float(np.median(losses)) if losses else None,
            'p10': float(np.quantile(losses, .1)) if losses else None}
        groups[year]['positions_added'] = sum(any(e['action'] == 'add' and e['time'].startswith(year)
                                                   for e in t['executions']) for t in trades)
    opened = [t for t in trades if t['why'] == 'end']
    return {'metrics': metrics, 'fidelity': fidelity(D, trades), 'closed_by_exit_year': groups,
            'end_added': describe([t for t in opened if added(t)]),
            'end_not_added': describe([t for t in opened if not added(t)]),
            'all_closed_invested': describe([t for t in trades if t['why'] != 'end'])['invested_basis']}


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
        raise ValueError('dataset digest differs from the registered v1')
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
    book, _ = books(D, fields, mask, 'H3')
    del fields, mask
    gc.collect()
    lever = f1_rules(D, 6, (1, 3))
    if lever.add_stop != 'fill':
        raise ValueError('baseline add-stop differs from preregistration')
    limited = replace(lever, max_open=11)
    cases = {'U1': lever, 'CD1': replace(lever, add_stop='cost'),
             'AY1': limited, 'CD2': replace(limited, add_stop='cost')}
    results = {}
    for name, rules in cases.items():
        print('account', name, flush=True)
        results[name] = account(D, book, rules)
    prior = json.loads((root / 'studies/trader_replication/reports/gap_review/strong_continue_bz.json').read_text())['results']
    for name in ('U1', 'AY1'):
        for year in ('2024', '2025', '2026'):
            actual, old = results[name]['metrics'], prior[name]['metrics']
            if abs(actual['by_year'][year] - old['by_year'][year]) > 1e-10 or actual['entries_by_year'][year] != old['entries_by_year'][year]:
                raise AssertionError(f'{name} {year} does not match previously reported baseline')
    paths = ('studies/trader_replication/martin_continue_cd.py', 'studies/trader_replication/martin_continue_ca.py',
             'studies/trader_replication/martin_continue_bu.py', 'studies/trader_replication/martin_continue_bt.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/trader_replication/system.py')
    out = {'dataset_digest': D.A['digest'], 'window': list(panels.WINDOW), 'results': results,
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}}
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_cd.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
