"""DO: add a preselected first-EMA50-retest short to a preselected Z15 book."""
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
from .martin_continue_bv import daily_name_score, daily_pool_book, level_z15, martin_rules
from .martin_continue_bw import positions
from .martin_continue_cr import json_default
from .martin_continue_dc import account_summary
from .martin_continue_dn import first_retest
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, merge, sized


STAGES = ('ready', 'pool', 'slopes', 'gate', 'touched', 'selected', 'filled', 'actual')


def first_ready(close, high, e50):
    """The row for day d is formed before inspecting any of day's d prices."""
    n, m = close.shape
    ready = np.zeros((n, m), bool)
    state = np.zeros(m, dtype=np.int8)
    for d in range(1, n):
        ready[d] = state == 1
        valid = (np.isfinite(close[d - 1]) & np.isfinite(close[d]) & np.isfinite(high[d]) &
                 np.isfinite(e50[d - 1]) & np.isfinite(e50[d]) & (close[d - 1] > 0) &
                 (close[d] > 0) & (high[d] > 0) & (e50[d - 1] > 0) & (e50[d] > 0))
        state[~valid] = 0
        touch = valid & (state == 1) & (high[d] >= .99 * e50[d - 1])
        state[touch] = 2
        state[valid & (close[d] >= e50[d])] = 0
        crossed = valid & (close[d - 1] > e50[d - 1]) & (close[d] < e50[d])
        state[crossed] = 1
    return ready


def choose_preopen(z15, f50, turnover):
    """Choose by previous turnover, then code index, then original setup; no day-d bars."""
    selected_z = np.zeros(z15.shape, bool)
    selected_f = np.zeros(z15.shape, bool)
    for d in range(1, len(z15)):
        choices = []
        for tag, mask in ((0, z15), (1, f50)):
            for j in np.flatnonzero(mask[d]):
                value = turnover[d - 1, j]
                priority = -float(value) if np.isfinite(value) else 0.0
                choices.append((priority, int(j), tag))
        if choices:
            _, j, tag = min(choices)
            (selected_z if tag == 0 else selected_f)[d, j] = True
    return selected_z, selected_f


def order_book(A, sc, selected_z, selected_f, level_z, level_f):
    masks = {'Z15': {'armed': selected_z, 'level': level_z},
             'Z50': {'armed': selected_f, 'level': level_f}}
    rows = shorts.short_entries(A, masks, sc)
    if any(len(r) > 1 for r in rows):
        raise AssertionError('more than one preselected order per day')
    return [[((1, e[0]),) + tuple(e[1:]) for e in row] for row in rows]


def selected_info(A, days, selected_z, selected_f, level_z, level_f):
    rows = []
    for d in range(1, len(days)):
        if not panels.WINDOW[0] <= days[d] <= panels.WINDOW[1]:
            continue
        for tag, mask, levels in (('Z15', selected_z, level_z), ('Z50', selected_f, level_f)):
            for j in np.flatnonzero(mask[d]):
                op, hi, level = A['open'][d, j], A['high'][d, j], levels[d, j]
                if not (np.isfinite(op) and np.isfinite(hi) and op > 0 and hi > 0 and hi >= op):
                    status = 'unknown_bar'
                elif op >= level:
                    status = 'open_at_or_above_limit'
                elif hi < level:
                    status = 'untouched'
                else:
                    status = 'touched'
                rows.append({'day': days[d], 'code': str(A['codes'][j]), 'setup': tag,
                             'level': float(level), 'status': status})
    return rows


def summarize_ledger(evidence, trades):
    actual = {(t['entry'], t['code']) for t in trades if t['side'] < 0 and t['kind'] == 's_Z50'}
    rows = []
    for row in evidence:
        daily = []
        for d in row['days']:
            flags = list(d['stages'])
            flags.append(bool(flags[-1] and (d['day'], 'US.' + row['ticker']) in actual))
            daily.append({'day': d['day'], 'stages': flags})
        rows.append({'id': row['id'], 'ticker': row['ticker'], 'entry_date': row['entry_date'], 'days': daily})
    result = {}
    for year in ('2024', '2025', '2026', 'all'):
        sample = [r for r in rows if year == 'all' or r['entry_date'].startswith(year)]
        result[year] = {'located': len(sample), 'funnel': {stage: sum(any(d['stages'][i] for d in r['days']) for r in sample)
                                                           for i, stage in enumerate(STAGES)},
                        'actual_ids': [r['id'] for r in sample if any(d['stages'][-1] for d in r['days'])]}
    return {'years': result, 'records': rows}


def main():
    if os.environ.get('TRADER_DATA_MODE') != 'frozen' or os.environ.get('TRADER_DATA_TAG') != 'trader-data-v1':
        raise ValueError('explicitly select frozen v1')
    root = Path(__file__).resolve().parents[2]
    reports = root / 'studies/trader_replication/reports/gap_review'
    paths = {k: reports / f'strong_continue_{k}.json' for k in ('bz', 'cq', 'dc', 'dn')}
    paths['bw'] = reports / 'strong_continue_bw_trader-data-v1.json'
    prior = {k: json.loads(p.read_text()) for k, p in paths.items()}
    old = ticket_t4.ranks
    try:
        ticket_t4.ranks = activity_ranks
        D = Data()
    finally:
        ticket_t4.ranks = old
    pin = json.loads((root / 'studies/trader_replication/DATA_PIN.json').read_text())['trader-data-v1']['us']
    if D.A['digest'] != pin or any(p['dataset_digest'] != pin for p in prior.values()):
        raise ValueError('frozen dataset differs from references')
    A, sc = D.A, D.cfg.get('short', {})
    if sc.get('setups') != ['Z15'] or sc.get('pool') != 'U7' or sc.get('gate') != 'below50' or sc.get('max_new') != 1:
        raise ValueError('registered short settings differ')
    if [r for r in positions(A, D.reg) if r[2] < 0] != [r for r in prior['bw']['candidates'] if r[2] < 0]:
        raise AssertionError('original short entries differ from BW')
    del D.fp, D.fwd, D.raw
    for k in ('pr63', 'pr126', 'stack', 'tight'):
        A.pop(k, None)
    D.rk = D.rk.astype(np.int32)
    gc.collect()
    pool = martin_rules.pool_for(A, 'U7')
    gate = shorts.gate_days(A, 'below50')
    setup = level_z15(A, pool)
    original_armed = setup['armed'] & gate[:, None]
    legacy_raw = shorts.short_entries(A, {'Z15': {'armed': original_armed, 'level': setup['level']}}, sc)
    legacy = [[((1, e[0]),) + tuple(e[1:]) for e in sorted(row, key=lambda e: e[0])[:1]] for row in legacy_raw]
    if legacy != [[e for e in row if e[2] < 0] for row in D.reg]:
        raise AssertionError('reconstructed original short book differs')
    del legacy_raw, legacy
    ready = first_ready(A['close'], A['high'], A['e50'])
    first, _ = first_retest(A['close'], A['high'], A['e50'])
    valid = (np.isfinite(A['close'][:-1]) & np.isfinite(A['close'][1:]) & np.isfinite(A['high'][1:]) &
             np.isfinite(A['e50'][:-1]) & np.isfinite(A['e50'][1:]) & (A['close'][:-1] > 0) &
             (A['close'][1:] > 0) & (A['high'][1:] > 0) & (A['e50'][:-1] > 0) & (A['e50'][1:] > 0))
    replay_first = np.zeros_like(ready)
    replay_first[1:] = ready[1:] & valid & (A['high'][1:] >= .99 * A['e50'][:-1])
    if not np.array_equal(first, replay_first):
        raise AssertionError('first-retest timing differs from DN')
    del first, replay_first, valid
    slope = np.zeros_like(ready)
    slope[2:] = (A['e9'][1:-1] < A['e9'][:-2]) & (A['e21'][1:-1] < A['e21'][:-2])
    eligible_f = ready & pool & slope & gate[:, None]
    level_f = martin_rules.prev(A['e50']) * .99
    none = np.zeros_like(ready)
    c0_z, c0_f = choose_preopen(original_armed, none, A['to20'])
    c1_z, c1_f = choose_preopen(original_armed, eligible_f, A['to20'])
    if c0_f.any():
        raise AssertionError('control unexpectedly contains F50')
    short0 = order_book(A, sc, c0_z, c0_f, setup['level'], level_f)
    short1 = order_book(A, sc, c1_z, c1_f, setup['level'], level_f)
    infos = {'DO0': selected_info(A, D.days, c0_z, c0_f, setup['level'], level_f),
             'DO1': selected_info(A, D.days, c1_z, c1_f, setup['level'], level_f)}
    year_counts = {}
    for year in ('2024', '2025', '2026'):
        d = np.array([x.startswith(year) and panels.WINDOW[0] <= x <= panels.WINDOW[1] for x in D.days])
        touch = (A['open'] < level_f) & (level_f <= A['high'])
        year_counts[year] = {'ready': int(ready[d].sum()), 'ready_pool': int((ready & pool)[d].sum()),
                             'ready_pool_slopes': int((ready & pool & slope)[d].sum()),
                             'eligible': int(eligible_f[d].sum()), 'eligible_touched': int((eligible_f & touch)[d].sum()),
                             'overlap_original_stock_days': int((eligible_f & original_armed)[d].sum()),
                             'f50_eligible_days': int(np.count_nonzero(np.any(eligible_f[d], axis=1))),
                             'z15_eligible_days': int(np.count_nonzero(np.any(original_armed[d], axis=1))),
                             'both_eligible_days': int(np.count_nonzero(np.any(eligible_f[d], axis=1) & np.any(original_armed[d], axis=1))),
                             'f50_preselected': int(c1_f[d].sum()),
                             'f50_filled_candidate': sum(len(row) for day, row in enumerate(short1) if d[day] and row and row[0][5] == 's_Z50')}
    ci = {str(c): j for j, c in enumerate(A['codes'])}
    f_keys = {(d, e[1]) for d, row in enumerate(short1) for e in row if e[5] == 's_Z50'}
    evidence = []
    for row in prior['dc']['ledger']:
        j = ci['US.' + row['ticker']]
        daily = []
        for old_day in row['days']:
            d = D.di[old_day['day']]
            s0 = bool(ready[d, j])
            s1 = bool(s0 and pool[d, j])
            s2 = bool(s1 and slope[d, j])
            s3 = bool(s2 and gate[d])
            s4 = bool(s3 and A['open'][d, j] < level_f[d, j] <= A['high'][d, j])
            s5 = bool(s4 and c1_f[d, j])
            s6 = bool(s5 and (d, j) in f_keys)
            daily.append({'day': D.days[d], 'stages': [s0, s1, s2, s3, s4, s5, s6]})
        evidence.append({'id': row['id'], 'ticker': row['ticker'], 'entry_date': row['entry_date'], 'days': daily})
    longs = [[e for e in row if e[2] > 0] for row in D.reg]
    reg0 = [l + s for l, s in zip(longs, short0)]
    reg1 = [l + s for l, s in zip(longs, short1)]
    del pool, setup, ready, slope, eligible_f, level_f, none, c0_z, c0_f, c1_z, c1_f, original_armed
    for k in ('pr21', 'rank_pool'):
        A.pop(k, None)
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
    books = {'U1': merge(D.reg, additions), 'DO0': merge(reg0, additions), 'DO1': merge(reg1, additions)}
    del fields, mask, score, holding, additions, reg0, reg1, longs
    gc.collect()
    base_rules = f1_rules(D, 6, (1, 3))
    mg = dict(base_rules.management_by_kind)
    if 's_Z15' not in mg:
        raise ValueError('original Z15 management policy missing')
    mg['s_Z50'] = dict(mg['s_Z15'])
    rules = replace(base_rules, management_by_kind=mg, intraday_kinds=tuple(base_rules.intraday_kinds) + ('s_Z50',))
    px, ema = D.base.px(A), D.base.ema_inputs(A, D.pool, rules)
    start = int(np.searchsorted(A['days'], panels.WINDOW[0]))
    end = int(np.searchsorted(A['days'], panels.WINDOW[1], side='right'))
    results = {}
    for name in ('U1', 'DO0', 'DO1'):
        curve, dates, trades = system.simulate(px, ema, rules, books[name], *panels.WINDOW, audit=True)
        m = compare.metrics(curve, dates, trades, books[name], start, end)
        m['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in trades) for y in ('2024', '2025', '2026')}
        m['invested_basis'] = describe([t for t in trades if t['why'] != 'end'], 'ret_invested')
        if name == 'U1':
            if digest(trades) != prior['cq']['u1_trades_digest']:
                raise AssertionError('U1 differs from CQ')
            ref = prior['bz']['results']['U1']['metrics']
            for y in ('2024', '2025', '2026'):
                if abs(m['by_year'][y] - ref['by_year'][y]) > 1e-10 or m['entries_by_year'][y] != ref['entries_by_year'][y]:
                    raise AssertionError('U1 differs from BZ: ' + y)
        actual_short = {(t['entry'], t['code']) for t in trades if t['side'] < 0}
        existing_hits = [r['id'] for r in prior['dc']['ledger'] if any((x['day'], 'US.' + r['ticker']) in actual_short for x in r['days'])]
        results[name] = {'metrics': m, 'fidelity': fidelity(D, trades), 'trade_sha256': digest(trades),
                         'original_ledger_hit_ids': existing_hits,
                         'shorts': {y: account_summary(trades, y) for y in ('2024', '2025', '2026')},
                         'f50_ledger': summarize_ledger(evidence, trades) if name == 'DO1' else None,
                         'f50_positions': [t for t in trades if t['kind'] == 's_Z50']}
    code = ('studies/trader_replication/martin_continue_do.py', 'studies/trader_replication/martin_continue_dn.py',
            'studies/trader_replication/martin_continue_dc.py', 'studies/trader_replication/martin_continue_bv.py',
            'studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_bq.py',
            'studies/trader_replication/martin_continue_bt.py', 'studies/trader_replication/martin_strong_scan.py',
            'studies/trader_replication/shorts.py', 'studies/trader_replication/system.py',
            'studies/martin_luk/replicate.py', 'studies/martin_luk/notes/trades.csv')
    out = {'dataset_digest': pin, 'window': list(panels.WINDOW), 'stages': list(STAGES), 'candidate_counts': year_counts,
           'preselected_orders': infos, 'results': results,
           'references_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths.values()},
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in code}}
    target = reports / 'strong_continue_do.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False, default=json_default) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
