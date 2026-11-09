"""DC: map the updated dated short ledger through the unchanged U1 short funnel."""
from collections import Counter
import gc
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from . import fidelity, ledger, panels, shorts, system, ticket_t4, watchlist
from .martin_continue_a import required_fields
from .martin_continue_b_check import digest
from .martin_continue_bm import describe
from .martin_continue_bq import _ROLL_MEAN, activity_ranks, chunked_roll_mean
from .martin_continue_bv import daily_name_score, daily_pool_book, level_z15, martin_rules
from .martin_continue_bw import positions
from .martin_continue_cr import json_default
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, merge, sized

STAGES = ('pool', 'under_falling_e21', 'z15_armed', 'market_gate', 'limit_touched',
          'raw_candidate', 'daily_cap', 'actual_entry')


def classify(day_stages):
    """Deepest common-day funnel stage, never a union of different dates."""
    depth = -1
    for statuses in day_stages:
        first_missing = next((i for i, value in enumerate(statuses) if not value), len(STAGES))
        if any(statuses[first_missing:]):
            raise AssertionError('daily stages must be cumulative')
        depth = max(depth, first_missing - 1)
    return {'deepest': STAGES[depth] if depth >= 0 else 'none',
            'first_missing': STAGES[depth + 1] if depth + 1 < len(STAGES) else None}


def account_summary(trades, year):
    selected = [t for t in trades if t['side'] < 0 and t['entry'].startswith(year)]
    closed = [t for t in selected if t['why'] != 'end']
    mark = [t for t in selected if t['why'] == 'end']
    return {'entries': len(selected), 'closed': len(closed), 'end_marked': len(mark),
            'closed_basis': describe(closed, 'ret_invested'),
            'median_closed_days': float(np.median([t['days'] for t in closed])) if closed else None,
            'closed_pnl_initial_equity_units': float(sum(t['pnl'] for t in closed)),
            'end_mark_pnl_initial_equity_units': float(sum(t['pnl'] for t in mark)),
            'exit_reasons': dict(Counter(t['why'] for t in closed))}


def main():
    if os.environ.get('TRADER_DATA_MODE') != 'frozen' or os.environ.get('TRADER_DATA_TAG') != 'trader-data-v1':
        raise ValueError('explicitly select frozen v1')
    root = Path(__file__).resolve().parents[2]
    reports = root / 'studies/trader_replication/reports/gap_review'
    paths = {n: reports / f'strong_continue_{n}.json' for n in ('bz', 'cq')}
    paths['bw'] = reports / 'strong_continue_bw_trader-data-v1.json'
    prev = {n: json.loads(p.read_text()) for n, p in paths.items()}
    old = ticket_t4.ranks
    try:
        ticket_t4.ranks = activity_ranks
        D = Data()
    finally:
        ticket_t4.ranks = old
    pin = json.loads((root / 'studies/trader_replication/DATA_PIN.json').read_text())['trader-data-v1']['us']
    if D.A['digest'] != pin or any(p['dataset_digest'] != pin for p in prev.values()):
        raise ValueError('dataset digest mismatch')
    sc = D.cfg.get('short', {})
    if sc.get('setups') != ['Z15'] or sc.get('pool') != 'U7' or sc.get('gate') != 'below50' or sc.get('max_new') != 1:
        raise ValueError('registered short setup differs from preregistration')
    all_short = [t for t in D.base.trades() if t.side == 'short' and t.dated
                 and ledger.market(t.ticker) == 'us' and panels.WINDOW[0] <= t.entry_date <= panels.WINDOW[1]]
    located, missing = fidelity.locate(all_short, D.A['days'], D.A['codes'], prefix='US.', has=D.A['has'])
    del D.fp, D.fwd, D.raw
    for key in ('pr63', 'pr126', 'stack', 'tight'):
        D.A.pop(key, None)
    D.rk = D.rk.astype(np.int32)
    gc.collect()
    pool = martin_rules.pool_for(D.A, sc['pool'])
    setup = level_z15(D.A, pool)
    gate = shorts.gate_days(D.A, sc['gate'])
    fired = shorts.fired(D.A, {'armed': setup['armed'] & gate[:, None], 'level': setup['level']})
    raw = shorts.short_entries(D.A, {'Z15': {'armed': setup['armed'] & gate[:, None], 'level': setup['level']}}, sc)
    raw_keys = {(d, e[1]) for d, entries in enumerate(raw) for e in entries}
    capped_keys = {(d, e[1]) for d, entries in enumerate(D.reg) for e in entries if e[2] < 0}
    codes = {str(code): j for j, code in enumerate(D.A['codes'])}
    missing_details = []
    for t in all_short:
        if t.id in missing:
            code = 'US.' + t.ticker
            missing_details.append({'id': t.id, 'ticker': t.ticker, 'entry_date': t.entry_date,
                                    'precision': t.precision,
                                    'reason': 'code_absent' if code not in codes else 'no_bar_in_window'})
    previous_short = [r for r in prev['bw']['candidates'] if r[2] < 0]
    current_short = [r for r in positions(D.A, D.reg) if r[2] < 0]
    if current_short != previous_short:
        raise AssertionError('entire registered short book differs from BW')
    c, e21 = D.A['close'], D.A['e21']
    evidence = []
    for t, j, a, b in located:
        a = max(a, int(np.searchsorted(D.A['days'], panels.WINDOW[0])))
        b = min(b, int(np.searchsorted(D.A['days'], panels.WINDOW[1], side='right')) - 1)
        daily = []
        for d in range(a, b + 1):
            s0 = bool(pool[d, j])
            s1 = bool(s0 and d >= 2 and c[d - 1, j] < e21[d - 1, j] < e21[d - 2, j])
            s2 = bool(s1 and setup['armed'][d, j])
            s3 = bool(s2 and gate[d])
            s4 = bool(s3 and fired[d, j])
            s5 = bool(s4 and (d, j) in raw_keys)
            s6 = bool(s5 and (d, j) in capped_keys)
            def number(x):
                return float(x) if np.isfinite(x) else None
            daily.append({'day': D.days[d], 'stages': [s0, s1, s2, s3, s4, s5, s6],
                          'prior_e21_limit': number(setup['level'][d, j]),
                          'open': number(D.A['open'][d, j]), 'high': number(D.A['high'][d, j])})
        evidence.append({'id': t.id, 'ticker': t.ticker, 'entry_date': t.entry_date, 'precision': t.precision,
                         'window_lo': t.window_lo, 'window_hi': t.window_hi, 'days': daily})
    del pool, setup, gate, fired, raw, raw_keys, capped_keys
    for key in ('pr21', 'rank_pool'):
        D.A.pop(key, None)
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
    book = merge(D.reg, sized(raw, .5))
    del fields, mask, score, holding, raw
    gc.collect()
    rules = f1_rules(D, 6, (1, 3))
    curve, dates, trades = system.simulate(D.base.px(D.A), D.base.ema_inputs(D.A, D.pool, rules),
                                           rules, book, *panels.WINDOW, audit=True)
    if digest(trades) != prev['cq']['u1_trades_digest']:
        raise AssertionError('U1 trade path differs from CQ')
    annual = system.stats(curve, dates, trades)['by_year']
    for year in ('2024', '2025', '2026'):
        ref = prev['bz']['results']['U1']['metrics']
        if (abs(annual[year] - ref['by_year'][year]) > 1e-10
                or sum(t['entry'].startswith(year) for t in trades) != ref['entries_by_year'][year]):
            raise AssertionError('U1 baseline differs from BZ: ' + year)
    actual = {(t['entry'], t['code']): t for t in trades if t['side'] < 0}
    for row in evidence:
        for day in row['days']:
            position = actual.get((day['day'], 'US.' + row['ticker']))
            day['stages'].append(position is not None)
            day['actual_fill'] = float(position['fill']) if position else None
        row.update(classify([d['stages'] for d in row['days']]))
    result = {}
    for year in ('2024', '2025', '2026', 'all'):
        entries = [t for t in all_short if year == 'all' or t.entry_date.startswith(year)]
        rows = [r for r in evidence if year == 'all' or r['entry_date'].startswith(year)]
        cum = {stage: sum(any(d['stages'][i] for d in r['days']) for r in rows) for i, stage in enumerate(STAGES)}
        result[year] = {'ledger_total': len(entries), 'located': len(rows),
                        'missing_ids': [t.id for t in entries if t.id in missing],
                        'missing_details': [x for x in missing_details if year == 'all' or x['entry_date'].startswith(year)],
                        'precision': dict(Counter(t.precision for t in entries)),
                        'by_precision': {precision: {
                            'located': sum(r['precision'] == precision for r in rows),
                            'actual_entry': sum(r['precision'] == precision and r['first_missing'] is None for r in rows)}
                            for precision in ('exact', 'chart')},
                        'funnel': cum, 'first_missing': dict(Counter(r['first_missing'] or 'actual_entry' for r in rows))}
        if year != 'all':
            result[year]['u1_short_positions'] = account_summary(trades, year)
    code_paths = ('studies/trader_replication/martin_continue_dc.py', 'studies/trader_replication/martin_continue_bv.py',
                  'studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_bq.py',
                  'studies/trader_replication/martin_continue_bm.py', 'studies/trader_replication/martin_continue_bw.py',
                  'studies/trader_replication/shorts.py', 'studies/trader_replication/system.py',
                  'studies/martin_luk/replicate.py', 'studies/martin_luk/notes/trades.csv')
    out = {'dataset_digest': pin, 'window': list(panels.WINDOW), 'stages': list(STAGES),
           'years': result, 'ledger': evidence, 'u1_year_returns': annual,
           'u1_trades_digest': digest(trades), 'previous_short_candidates': len(previous_short),
           'references_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths.values()},
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in code_paths}}
    target = reports / 'strong_continue_dc.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False, default=json_default) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
