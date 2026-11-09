"""CB: describe matched and unique actual trades in the fixed CA accounts."""
import gc
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from . import compare, panels, system, ticket_t4, watchlist
from .martin_continue_a import required_fields
from .martin_continue_bq import _ROLL_MEAN, activity_ranks, chunked_roll_mean
from .martin_continue_bs import key_trades
from .martin_continue_bu import describe
from .martin_continue_ca import books, coil_fields
from .martin_strong import Data
from .martin_strong_scan import active, f1_rules, nl_rules


def group_pair(left, right):
    a, b = key_trades(left), key_trades(right)
    common = a.keys() & b.keys()
    selections = {'left_common': (a, common), 'right_common': (b, common),
                  'left_only': (a, a.keys() - b.keys()), 'right_only': (b, b.keys() - a.keys())}
    result = {}
    for year in ('2024', '2025', '2026'):
        result[year] = {}
        for group, (source, keys) in selections.items():
            rows = [source[key] for key in sorted(keys) if key[0].startswith(year)]
            result[year][group] = {kind: describe([t for t in rows if (t['kind'] == 'list') == (kind == 'list')])
                                   for kind in ('list', 'other')}
        for side, source in (('left', a), ('right', b)):
            rows = [t for t in source.values() if t['entry'].startswith(year)]
            pieces = [result[year][side + suffix][kind] for suffix in ('_common', '_only') for kind in ('list', 'other')]
            if sum(x['entries'] for x in pieces) != len(rows):
                raise AssertionError('group counts do not reconcile')
            if abs(sum(x['closed_pnl'] + x['open_mark_pnl'] for x in pieces) - sum(t['pnl'] for t in rows)) > 1e-8:
                raise AssertionError('group trade PnL does not reconcile')
    return result


def main():
    if os.environ.get('TRADER_DATA_MODE') != 'frozen' or os.environ.get('TRADER_DATA_TAG') != 'trader-data-v1':
        raise ValueError('explicitly select the registered frozen v1 dataset')
    root = Path(__file__).resolve().parents[2]
    original = ticket_t4.ranks
    try:
        ticket_t4.ranks = activity_ranks
        D = Data()
    finally:
        ticket_t4.ranks = original
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
    u1, sat = books(D, fields, mask, 'H3')
    fields.update(coil_fields(D))
    u1_coil, sat_coil = books(D, fields, mask, 'H4')
    del fields, mask
    gc.collect()
    lever, plain = f1_rules(D, 6, (1, 3)), nl_rules(D, 6)
    cases = {'U1': (u1, lever), 'CA1': (u1_coil, lever),
             'SAT6': (sat, plain), 'CA2': (sat_coil, plain)}
    reference = json.loads((root / 'studies/trader_replication/reports/gap_review/strong_continue_ca.json').read_text())['results']
    trades_by_account = {}
    for name, (book, rules) in cases.items():
        print('account', name, flush=True)
        px, em = D.base.px(D.A), D.base.ema_inputs(D.A, D.pool, rules)
        curve, dates, trades = system.simulate(px, em, rules, book, *panels.WINDOW, audit=True)
        lo = int(np.searchsorted(D.A['days'], panels.WINDOW[0]))
        hi = int(np.searchsorted(D.A['days'], panels.WINDOW[1], side='right'))
        metrics = compare.metrics(curve, dates, trades, book, lo, hi)
        for year in ('2024', '2025', '2026'):
            prior = reference[name]['metrics']
            if abs(metrics['by_year'][year] - prior['by_year'][year]) > 1e-10:
                raise AssertionError(f'{name} {year} annual return differs from CA')
            if sum(t['entry'].startswith(year) for t in trades) != prior['entries_by_year'][year]:
                raise AssertionError(f'{name} {year} entry count differs from CA')
        trades_by_account[name] = trades
    results = {'U1_vs_CA1': group_pair(trades_by_account['U1'], trades_by_account['CA1']),
               'SAT6_vs_CA2': group_pair(trades_by_account['SAT6'], trades_by_account['CA2'])}
    paths = ('studies/trader_replication/martin_continue_cb.py', 'studies/trader_replication/martin_continue_ca.py',
             'studies/trader_replication/martin_continue_bs.py', 'studies/trader_replication/martin_continue_bu.py',
             'studies/trader_replication/system.py')
    out = {'dataset_digest': D.A['digest'], 'window': list(panels.WINDOW), 'results': results,
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}}
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_cb.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
