"""DH: pair REG6 and delayed-open trades by the prior-close signal."""
from collections import Counter
from dataclasses import replace
import gc
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from . import panels, system, ticket_t4
from .martin_continue_b_check import digest
from .martin_continue_bq import activity_ranks
from .martin_continue_cr import json_default
from .martin_continue_dg import next_open
from .martin_strong import Data
from .martin_strong_scan import longs, nl_rules


def index_trades(trades, days, delayed):
    di = {d: i for i, d in enumerate(days)}
    out = {}
    for t in trades:
        day = di[t['entry']] - int(delayed)
        if day < 0:
            raise ValueError('missing signal day')
        key = (days[day], t['code'], t['side'], t['kind'])
        if key in out:
            raise ValueError('duplicate trade signal')
        out[key] = t
    return out


def summary(rows):
    closed = [t for t in rows if t['why'] != 'end']
    invested = sum(e['price'] * e['shares'] for t in closed for e in t['executions'] if e['action'] in ('entry', 'add'))
    return {'entries': len(rows), 'closed': len(closed), 'marked': len(rows) - len(closed),
            'closed_pnl': float(sum(t['pnl'] for t in closed)),
            'marked_pnl': float(sum(t['pnl'] for t in rows if t['why'] == 'end')),
            'weighted_closed_ret': float(sum(t['pnl'] for t in closed) / invested) if invested else None,
            'mean_closed_ret': float(np.mean([t['ret_invested'] for t in closed])) if closed else None,
            'median_closed_days': float(np.median([t['days'] for t in closed])) if closed else None,
            'median_initial_stop': float(np.median([t['risk_pct'] for t in closed])) if closed else None}


def paired(left, right, year):
    a = {k for k in left if year == 'all' or k[0].startswith(year)}
    b = {k for k in right if year == 'all' or k[0].startswith(year)}
    common = sorted(a & b)
    closed = [k for k in common if left[k]['why'] != 'end' and right[k]['why'] != 'end']
    outcomes = Counter(('win' if left[k]['ret_invested'] > 0 else 'nonwin') + ':' +
                       ('win' if right[k]['ret_invested'] > 0 else 'nonwin') for k in closed)
    gaps = [right[k]['fill'] / left[k]['fill'] - 1 for k in closed]
    return {'left_entries': len(a), 'right_entries': len(b), 'common': len(common),
            'left_only': summary([left[k] for k in sorted(a - b)]),
            'right_only': summary([right[k] for k in sorted(b - a)]),
            'common_with_marked': len(common) - len(closed),
            'common_all_left': summary([left[k] for k in common]),
            'common_all_right': summary([right[k] for k in common]),
            'both_closed': len(closed), 'common_left': summary([left[k] for k in closed]),
            'common_right': summary([right[k] for k in closed]), 'outcomes_left_right': dict(outcomes),
            'opening_gap_p10_median_p90': np.quantile(gaps, [.1, .5, .9]).tolist() if gaps else None}


def main():
    if os.environ.get('TRADER_DATA_MODE') != 'frozen' or os.environ.get('TRADER_DATA_TAG') != 'trader-data-v1':
        raise ValueError('explicitly select frozen v1')
    root = Path(__file__).resolve().parents[2]
    reports = root / 'studies/trader_replication/reports/gap_review'
    ref_path = reports / 'strong_continue_dg.json'
    ref = json.loads(ref_path.read_text())
    old = ticket_t4.ranks
    try:
        ticket_t4.ranks = activity_ranks
        D = Data()
    finally:
        ticket_t4.ranks = old
    pin = json.loads((root / 'studies/trader_replication/DATA_PIN.json').read_text())['trader-data-v1']['us']
    if D.A['digest'] != pin or ref['dataset_digest'] != pin:
        raise ValueError('frozen data mismatch')
    reg = [[((1.0,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:6])
            for e in row] for row in longs(D.reg)]
    delayed, counts = next_open(reg, D.A['open'], D.A['low'], D.days)
    if counts != ref['candidates']:
        raise AssertionError('candidate counts mismatch DG')
    kinds = sorted({e[5] for row in delayed for e in row})
    rules = nl_rules(D, 6)
    delayed_rules = replace(rules, intraday_kinds=tuple(sorted(set(rules.intraday_kinds) | set(kinds))))
    del D.fp, D.fwd, D.raw
    for k in ('pr21', 'pr63', 'pr126', 'rank_pool', 'stack', 'tight'):
        D.A.pop(k, None)
    D.rk = D.rk.astype(np.int32)
    gc.collect()
    px, ema = D.base.px(D.A), D.base.ema_inputs(D.A, D.pool, rules)
    indexed = []
    for name, book, ru, is_delayed in (('REG6', reg, rules, False), ('DG1', delayed, delayed_rules, True)):
        curve, dates, trades = system.simulate(px, ema, ru, book, *panels.WINDOW, audit=True)
        if digest(trades) != ref['results'][name]['trades_digest']:
            raise AssertionError(name + ' trades differ from DG')
        if hashlib.sha256(np.asarray(curve).tobytes()).hexdigest() != ref['results'][name]['curve_sha256']:
            raise AssertionError(name + ' curve differs from DG')
        index = index_trades(trades, D.days, is_delayed)
        for key, t in index.items():
            j = int(np.searchsorted(D.A['codes'], t['code']))
            if j >= len(D.A['codes']) or D.A['codes'][j] != t['code']:
                raise ValueError('code missing or unsorted')
            d = D.di[t['entry']]
            expected = D.A['open' if is_delayed else 'close'][d, j]
            if abs(t['fill'] - expected) > 1e-7 * max(1, abs(expected)):
                raise AssertionError('fill differs from expected session price')
        indexed.append(index)
    out = {'dataset_digest': pin, 'window': list(panels.WINDOW),
           'by_signal_year': {year: paired(*indexed, year) for year in ('2024', '2025', '2026', 'all')},
           'reference_sha256': hashlib.sha256(ref_path.read_bytes()).hexdigest(),
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in
                           ('studies/trader_replication/martin_continue_dh.py', 'studies/trader_replication/martin_continue_dg.py',
                            'studies/trader_replication/system.py', 'studies/trader_replication/martin_strong_scan.py')}}
    target = reports / 'strong_continue_dh.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False, default=json_default) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
