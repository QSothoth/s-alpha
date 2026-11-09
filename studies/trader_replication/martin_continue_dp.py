"""DP: allow pre-existing sell limits to fill at a marketable opening price."""
from collections import Counter
from dataclasses import replace
import gc
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from . import compare, panels, shorts, system, ticket_t4, watchlist
from .martin_continue_a import required_fields
from .martin_continue_b_check import digest
from .martin_continue_bm import describe
from .martin_continue_bq import _ROLL_MEAN, activity_ranks, chunked_roll_mean
from .martin_continue_bt import fidelity
from .martin_continue_bv import daily_name_score, daily_pool_book
from .martin_continue_cr import json_default
from .martin_continue_dc import account_summary
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, merge, sized


def opening_fill(op, high, limit, width, marketable):
    """A pre-existing sell limit fills at its limit or, if enabled, at the opening price."""
    if not all(np.isfinite(v) and v > 0 for v in (op, high, limit, width)) or high < op:
        return 'unknown', None, None, None
    if op >= limit:
        if not marketable:
            return 'legacy_open_skipped', None, None, None
        fill = op
        status = 'marketable_open'
    elif high >= limit:
        fill = limit
        status = 'intraday_limit'
    else:
        return 'untouched', None, None, None
    stop = float(fill * (1 + width))
    return status, float(fill), stop, stop if high >= stop else None


def orders_from_saved(A, days, saved, sc, marketable):
    di = {day: i for i, day in enumerate(days)}
    ci = {str(code): j for j, code in enumerate(A['codes'])}
    book = [[] for _ in days]
    audit = []
    seen = set()
    for row in saved:
        d, j = di[row['day']], ci[row['code']]
        if d in seen:
            raise ValueError('more than one preselected order')
        seen.add(d)
        level = row['level']
        width = shorts.level_width(A, sc, d, j)
        op, high = A['open'][d, j], A['high'][d, j]
        status, fill, stop, day_exit = opening_fill(op, high, level, width, marketable)
        if fill is not None and shorts.too_wide(A, sc, d, j, fill, stop):
            status, fill, stop, day_exit = 'width_rejected', None, None, None
        if fill is not None:
            prev_turnover = A['to20'][d - 1, j]
            pr = -float(prev_turnover) if np.isfinite(prev_turnover) else 0.0
            mult = sc.get('risk_mult', 1.0)
            risk = width / mult if mult != 1.0 else None
            book[d].append(((1, pr), int(j), -1, fill, stop, 's_' + row['setup'], day_exit, risk))
        audit.append({'day': row['day'], 'code': row['code'], 'setup': row['setup'],
                      'prior_status': row['status'], 'status': status, 'level': level,
                      'open': float(op) if np.isfinite(op) else None, 'width': float(width),
                      'fill': fill, 'stop': stop, 'day_exit': day_exit})
    return book, audit


def ledger_view(A, days, evidence, selected_orders, trades):
    di = {day: i for i, day in enumerate(days)}
    ci = {str(code): j for j, code in enumerate(A['codes'])}
    selected = {(r['day'], r['code']): r for r in selected_orders if r['setup'] == 'Z50'}
    actual = {(t['entry'], t['code']) for t in trades if t['side'] < 0 and t['kind'] == 's_Z50'}
    records = []
    for row in evidence['records']:
        j = ci['US.' + row['ticker']]
        out = []
        for old in row['days']:
            day = old['day']
            d = di[day]
            flags = list(old['stages'][:4])
            op, high = A['open'][d, j], A['high'][d, j]
            level = .99 * A['e50'][d - 1, j] if d else np.nan
            known = all(np.isfinite(x) and x > 0 for x in (op, high, level)) and high >= op
            fillable = bool(flags[-1] and known and high >= level)
            choice = selected.get((day, 'US.' + row['ticker']))
            picked = bool(fillable and choice is not None)
            filled = bool(picked and choice['fill'] is not None)
            actual_entry = bool(filled and (day, 'US.' + row['ticker']) in actual)
            out.append({'day': day, 'stages': flags + [fillable, picked, filled, actual_entry],
                        'fillable_unknown': bool(flags[-1] and not known)})
        records.append({'id': row['id'], 'ticker': row['ticker'], 'entry_date': row['entry_date'], 'days': out})
    years = {}
    labels = ('ready', 'pool', 'slopes', 'gate', 'potential_fill', 'selected', 'filled', 'actual')
    for year in ('2024', '2025', '2026', 'all'):
        subset = [r for r in records if year == 'all' or r['entry_date'].startswith(year)]
        years[year] = {'located': len(subset),
                       'funnel': {k: sum(any(d['stages'][i] for d in r['days']) for r in subset)
                                  for i, k in enumerate(labels)},
                       'potential_fill_ids': [r['id'] for r in subset if any(d['stages'][4] for d in r['days'])],
                       'actual_ids': [r['id'] for r in subset if any(d['stages'][7] for d in r['days'])],
                       'unknown_ids': [r['id'] for r in subset if any(d['fillable_unknown'] for d in r['days'])]}
    return {'years': years, 'records': records}


def main():
    if os.environ.get('TRADER_DATA_MODE') != 'frozen' or os.environ.get('TRADER_DATA_TAG') != 'trader-data-v1':
        raise ValueError('explicitly select frozen v1')
    root = Path(__file__).resolve().parents[2]
    reports = root / 'studies/trader_replication/reports/gap_review'
    ref_path = reports / 'strong_continue_do.json'
    ref = json.loads(ref_path.read_text())
    for path in ('studies/trader_replication/martin_continue_do.py', 'studies/trader_replication/shorts.py',
                 'studies/trader_replication/system.py', 'studies/martin_luk/replicate.py'):
        if hashlib.sha256((root / path).read_bytes()).hexdigest() != ref['code_sha256'][path]:
            raise ValueError('DO source differs: ' + path)
    old = ticket_t4.ranks
    try:
        ticket_t4.ranks = activity_ranks
        D = Data()
    finally:
        ticket_t4.ranks = old
    pin = json.loads((root / 'studies/trader_replication/DATA_PIN.json').read_text())['trader-data-v1']['us']
    if D.A['digest'] != pin or ref['dataset_digest'] != pin:
        raise ValueError('frozen data mismatch')
    A, sc = D.A, D.cfg.get('short', {})
    if sc.get('setups') != ['Z15'] or sc.get('pool') != 'U7' or sc.get('gate') != 'below50' or sc.get('max_new') != 1:
        raise ValueError('original short configuration differs')
    all_shorts, audit = {}, {}
    for orig in ('DO0', 'DO1'):
        for marketable in (False, True):
            name = orig + ('_open' if marketable else '')
            all_shorts[name], audit[name] = orders_from_saved(A, D.days, ref['preselected_orders'][orig], sc, marketable)
    evidence = ref['results']['DO1']['f50_ledger']
    del D.fp, D.fwd, D.raw
    for k in ('pr21', 'pr63', 'pr126', 'rank_pool', 'stack', 'tight'):
        A.pop(k, None)
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
    additions = sized(daily_pool_book(D, fields, holding, score), .5)
    longs = [[e for e in row if e[2] > 0] for row in D.reg]
    books = {name: merge([l + s for l, s in zip(longs, sb)], additions) for name, sb in all_shorts.items()}
    del fields, mask, score, holding, additions, longs
    gc.collect()
    base = f1_rules(D, 6, (1, 3))
    mg = dict(base.management_by_kind)
    if 's_Z15' not in mg:
        raise ValueError('original Z15 management missing')
    mg['s_Z50'] = dict(mg['s_Z15'])
    rules = replace(base, management_by_kind=mg, intraday_kinds=tuple(base.intraday_kinds) + ('s_Z50',))
    px, ema = D.base.px(A), D.base.ema_inputs(A, D.pool, rules)
    start = int(np.searchsorted(A['days'], panels.WINDOW[0]))
    end = int(np.searchsorted(A['days'], panels.WINDOW[1], side='right'))
    results = {}
    for name in ('DO0', 'DO0_open', 'DO1', 'DO1_open'):
        curve, dates, trades = system.simulate(px, ema, rules, books[name], *panels.WINDOW, audit=True)
        m = compare.metrics(curve, dates, trades, books[name], start, end)
        m['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in trades) for y in ('2024', '2025', '2026')}
        m['invested_basis'] = describe([t for t in trades if t['why'] != 'end'], 'ret_invested')
        if not name.endswith('_open'):
            if digest(trades) != ref['results'][name]['trade_sha256']:
                raise AssertionError(name + ' trade path differs from DO')
            old_m = ref['results'][name]['metrics']
            for year in ('2024', '2025', '2026'):
                if abs(m['by_year'][year] - old_m['by_year'][year]) > 1e-10 or m['entries_by_year'][year] != old_m['entries_by_year'][year]:
                    raise AssertionError(name + ' annual results differ from DO')
        new_orders = {(r['day'], r['code'], 's_' + r['setup']) for r in audit[name] if r['status'] == 'marketable_open'}
        new_positions = [t for t in trades if (t['entry'], t['code'], t['kind']) in new_orders]
        actual_short = {(t['entry'], t['code']) for t in trades if t['side'] < 0}
        baseline_ledger = ref['results']['DO1']['f50_ledger']['records']
        hits = [r['id'] for r in baseline_ledger if any((d['day'], 'US.' + r['ticker']) in actual_short for d in r['days'])]
        results[name] = {'metrics': m, 'fidelity': fidelity(D, trades), 'trades_sha256': digest(trades),
                         'shorts': {y: account_summary(trades, y) for y in ('2024', '2025', '2026')},
                         'all_ledger_hit_ids': hits,
                         'f50_ledger': ledger_view(A, D.days, evidence, audit[name], trades) if name.startswith('DO1') else None,
                         'marketable_positions': new_positions}
    code = ('studies/trader_replication/martin_continue_dp.py', 'studies/trader_replication/martin_continue_do.py',
            'studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_bq.py',
            'studies/trader_replication/martin_continue_bv.py', 'studies/trader_replication/martin_continue_bt.py',
            'studies/trader_replication/shorts.py', 'studies/trader_replication/system.py',
            'studies/martin_luk/replicate.py', 'studies/martin_luk/notes/trades.csv')
    out = {'dataset_digest': pin, 'window': list(panels.WINDOW), 'orders': audit, 'results': results,
           'reference_sha256': hashlib.sha256(ref_path.read_bytes()).hexdigest(),
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in code}}
    target = reports / 'strong_continue_dp.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False, default=json_default) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
