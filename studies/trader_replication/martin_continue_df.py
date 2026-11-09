"""DF: compare the existing short gate with a previous-close QQQ EMA50 gate."""
from collections import Counter
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
from .martin_continue_dc import STAGES, account_summary, classify
from .martin_strong import BENCH, Data, bench
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, merge, sized


def qqq_gate(prices):
    under = prices < shorts.ema1(prices, 50)
    gate = np.zeros(len(prices), dtype=bool)
    gate[1:] = under[:-1]
    return gate


def capped(rows):
    return [[((1, e[0]),) + tuple(e[1:]) for e in sorted(row, key=lambda e: e[0])[:1]] for row in rows]


def ledger_result(reference, gate, raw, capped_rows, actual, days, codes):
    di = {str(day): i for i, day in enumerate(days)}
    ci = {str(code): i for i, code in enumerate(codes)}
    raw_keys = {(i, e[1]) for i, row in enumerate(raw) for e in row}
    cap_keys = {(i, e[1]) for i, row in enumerate(capped_rows) for e in row}
    entries = {(t['entry'], t['code']) for t in actual if t['side'] < 0}
    rows = []
    for row in reference:
        j = ci['US.' + row['ticker']]
        daily = []
        for old in row['days']:
            i = di[old['day']]
            s0, s1, s2 = old['stages'][:3]
            s3 = bool(s2 and gate[i])
            p, op, hi = old['prior_e21_limit'], old['open'], old['high']
            s4 = bool(s3 and p is not None and op is not None and hi is not None and op < p <= hi)
            s5 = bool(s4 and (i, j) in raw_keys)
            s6 = bool(s5 and (i, j) in cap_keys)
            s7 = bool(s6 and (old['day'], 'US.' + row['ticker']) in entries)
            daily.append({'day': old['day'], 'stages': [s0, s1, s2, s3, s4, s5, s6, s7]})
        rows.append({'id': row['id'], 'entry_date': row['entry_date'], 'ticker': row['ticker'],
                     'days': daily, **classify([d['stages'] for d in daily])})
    years = {}
    for year in ('2024', '2025', '2026', 'all'):
        selected = [r for r in rows if year == 'all' or r['entry_date'].startswith(year)]
        years[year] = {'located': len(selected),
                       'funnel': {s: sum(any(d['stages'][i] for d in r['days']) for r in selected)
                                  for i, s in enumerate(STAGES)},
                       'hit_ids': [r['id'] for r in selected if r['first_missing'] is None],
                       'first_missing': dict(Counter(r['first_missing'] or 'actual_entry' for r in selected))}
    return {'years': years, 'ledger': rows}


def main():
    if os.environ.get('TRADER_DATA_MODE') != 'frozen' or os.environ.get('TRADER_DATA_TAG') != 'trader-data-v1':
        raise ValueError('explicitly select frozen v1')
    root = Path(__file__).resolve().parents[2]
    reports = root / 'studies/trader_replication/reports/gap_review'
    paths = {name: reports / f'strong_continue_{name}.json' for name in ('bz', 'cq', 'dc')}
    paths['bw'] = reports / 'strong_continue_bw_trader-data-v1.json'
    prior = {name: json.loads(path.read_text()) for name, path in paths.items()}
    benchmark_path = BENCH / 'US.QQQ.csv'
    qhash = hashlib.sha256(benchmark_path.read_bytes()).hexdigest()
    if qhash != 'cb28714aab4b77cb7509afc897aa5d23d3d6a6ad6d780829fe3e44c9e404cb30':
        raise ValueError('QQQ benchmark differs from preregistered local cache')
    original = ticket_t4.ranks
    try:
        ticket_t4.ranks = activity_ranks
        D = Data()
    finally:
        ticket_t4.ranks = original
    pin = json.loads((root / 'studies/trader_replication/DATA_PIN.json').read_text())['trader-data-v1']['us']
    if D.A['digest'] != pin or any(p['dataset_digest'] != pin for p in prior.values()):
        raise ValueError('dataset differs from frozen references')
    sc = D.cfg.get('short', {})
    if sc.get('setups') != ['Z15'] or sc.get('pool') != 'U7' or sc.get('gate') != 'below50' or sc.get('max_new') != 1:
        raise ValueError('original short settings differ')
    if [r for r in positions(D.A, D.reg) if r[2] < 0] != [r for r in prior['bw']['candidates'] if r[2] < 0]:
        raise AssertionError('original short book differs from BW')
    qgate = qqq_gate(bench(D.days, 'QQQ'))
    del D.fp, D.fwd, D.raw
    for key in ('pr63', 'pr126', 'stack', 'tight'):
        D.A.pop(key, None)
    D.rk = D.rk.astype(np.int32)
    gc.collect()
    pool = martin_rules.pool_for(D.A, sc['pool'])
    setup = level_z15(D.A, pool)
    old_gate = shorts.gate_days(D.A, sc['gate'])
    old_raw = shorts.short_entries(D.A, {'Z15': {'armed': setup['armed'] & old_gate[:, None], 'level': setup['level']}}, sc)
    new_raw = shorts.short_entries(D.A, {'Z15': {'armed': setup['armed'] & qgate[:, None], 'level': setup['level']}}, sc)
    old_cap, new_cap = capped(old_raw), capped(new_raw)
    if old_cap != [[e for e in row if e[2] < 0] for row in D.reg]:
        raise AssertionError('rebuilt original candidates differ from full original daily short book')
    gate_years = {}
    for year in ('2024', '2025', '2026'):
        indices = [i for i, d in enumerate(D.days) if panels.WINDOW[0] <= d <= panels.WINDOW[1] and d.startswith(year)]
        gate_years[year] = {'sessions': len(indices), 'old_only_days': sum(bool(old_gate[i] and not qgate[i]) for i in indices),
                            'qqq_only_days': sum(bool(qgate[i] and not old_gate[i]) for i in indices),
                            'both_days': sum(bool(old_gate[i] and qgate[i]) for i in indices),
                            'neither_days': sum(bool(not old_gate[i] and not qgate[i]) for i in indices),
                            'old_raw': sum(len(old_raw[i]) for i in indices), 'qqq_raw': sum(len(new_raw[i]) for i in indices),
                            'old_cap': sum(len(old_cap[i]) for i in indices), 'qqq_cap': sum(len(new_cap[i]) for i in indices)}
    new_reg = [[e for e in original if e[2] > 0] + replacement for original, replacement in zip(D.reg, new_cap)]
    del pool, setup
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
    additions = sized(daily_pool_book(D, fields, holding, score), .5)
    books = {'U1': merge(D.reg, additions), 'DF1': merge(new_reg, additions)}
    del fields, mask, score, holding, additions, new_reg
    gc.collect()
    rules = f1_rules(D, 6, (1, 3))
    px, ema = D.base.px(D.A), D.base.ema_inputs(D.A, D.pool, rules)
    start = int(np.searchsorted(D.A['days'], panels.WINDOW[0]))
    end = int(np.searchsorted(D.A['days'], panels.WINDOW[1], side='right'))
    results = {}
    for name, gate, raw, cap in (('U1', old_gate, old_raw, old_cap), ('DF1', qgate, new_raw, new_cap)):
        track = {}
        curve, dates, trades = system.simulate(px, ema, rules, books[name], *panels.WINDOW, audit=True, track=track)
        metrics = compare.metrics(curve, dates, trades, books[name], start, end)
        metrics['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in trades) for y in ('2024', '2025', '2026')}
        metrics['invested_basis'] = describe([t for t in trades if t['why'] != 'end'], 'ret_invested')
        ledger = ledger_result(prior['dc']['ledger'], gate, raw, cap, trades, D.days, D.A['codes'])
        if name == 'U1':
            if digest(trades) != prior['cq']['u1_trades_digest']:
                raise AssertionError('U1 trade path differs from CQ')
            for year in ('2024', '2025', '2026'):
                ref = prior['bz']['results']['U1']['metrics']
                if abs(metrics['by_year'][year] - ref['by_year'][year]) > 1e-10 or metrics['entries_by_year'][year] != ref['entries_by_year'][year]:
                    raise AssertionError('U1 differs from BZ: ' + year)
            for row, old in zip(ledger['ledger'], prior['dc']['ledger']):
                if any(a['stages'] != b['stages'] for a, b in zip(row['days'], old['days'])):
                    raise AssertionError('U1 ledger differs from DC: ' + row['id'])
        results[name] = {'metrics': metrics, 'fidelity': fidelity(D, trades), 'ledger': ledger,
                         'short_positions': {y: account_summary(trades, y) for y in ('2024', '2025', '2026')},
                         'trades_digest': digest(trades)}
    paths_code = ('studies/trader_replication/martin_continue_df.py', 'studies/trader_replication/martin_continue_dc.py',
                  'studies/trader_replication/martin_continue_bv.py', 'studies/trader_replication/martin_strong.py',
                  'studies/trader_replication/martin_strong_scan.py', 'studies/trader_replication/shorts.py',
                  'studies/trader_replication/system.py', 'studies/martin_luk/notes/trades.csv')
    out = {'dataset_digest': pin, 'window': list(panels.WINDOW), 'qqq_sha256': qhash, 'gate_years': gate_years,
           'results': results, 'references_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths.values()},
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths_code}}
    target = reports / 'strong_continue_df.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False, default=json_default) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
