"""HE: replay a post-opening, market-on-close gap exit proxy."""
from collections import Counter
from dataclasses import replace
import gc
import json
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trader_replication import compare, panels, preopen, system
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_fc as fc
from studies.trader_replication import martin_continue_gi as gi
from studies.trader_replication import martin_continue_hb as hb
from studies.trader_replication import martin_continue_hc as hc
from studies.trader_replication import martin_continue_hd as hd
from studies.trader_replication.martin_continue_b_check import digest
from studies.trader_replication.martin_continue_bm import describe
from studies.trader_replication.martin_continue_bt import fidelity
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import f1_rules, nl_rules


def at_close_proxy(d, book):
    """Record the future close only as an exit, after a gap is observed at the open."""
    result, changed = [], []
    for day, row in enumerate(book):
        current = []
        for e in row:
            if np.isfinite(e[3]) and e[3] > 0 and e[3] < e[4]:
                close = float(d.A['close'][day, e[1]])
                current.append(tuple(e[:6]) + (close,) + tuple(e[7:]))
                changed.append((day, e[1], e[5]))
            else:
                current.append(e)
        result.append(current)
    return result, changed


def account(d, book, rules):
    px, ema, track = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules), {}
    curve, dates, trades = system.simulate(px, ema, rules, book, *panels.WINDOW, audit=True, track=track, preopen=True, preopen_gap_moc=True)
    lo = int(np.searchsorted(d.A['days'], panels.WINDOW[0]))
    hi = int(np.searchsorted(d.A['days'], panels.WINDOW[1], side='right'))
    metrics = compare.metrics(curve, dates, trades, book, lo, hi)
    metrics['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in trades) for y in ('2024', '2025', '2026')}
    metrics['invested_basis'] = describe([t for t in trades if t['why'] != 'end'], 'ret_invested')
    metrics['max_close_positions'] = max(track['open'])
    metrics['max_close_gross'] = float(max(track['gross']))
    metrics['margin_paid'] = float(track['margin'])
    metrics['add_executions_by_year'] = {y: sum(e['action'] == 'add' and e['time'].startswith(y)
                                               for t in trades for e in t['executions'])
                                         for y in ('2024', '2025', '2026')}
    plans = track['preopen_plans']
    for day in plans:
        if day['unreserved_gross'] < -1e-10 or (rules.gross_cost and day['unreserved_cash'] < -1e-10):
            raise AssertionError('prior reservations exceed budget')
        for r in day['orders']:
            if r['type'] == 'entry' and r['status'] == 'submitted':
                if r['shares'] * (r['limit'] - r['stop']) > r['risk_fraction'] * day['equity'] + 1e-10:
                    raise AssertionError('prior risk reservation exceeded')
    all_rows = [r for day in plans for r in day['orders']]
    submitted = [r for r in all_rows if r['type'] == 'entry' and r['status'] == 'submitted']
    if any('execution' not in r for r in submitted):
        raise AssertionError('submitted opening has no disposition')
    filled = [r for r in all_rows if r.get('execution') in ('filled', 'gap_moc', 'preopen_filled')]
    if any(r.get('gross_after') is None for r in filled):
        raise AssertionError('non-positive opening equity')
    if rules.gross_cost and any(r.get('cash_after', 0.) < -1e-10 for r in all_rows):
        raise AssertionError('cash account borrowed at opening')
    if rules.max_open and (max(track['open']) > rules.max_open or
                           any(r['positions_after'] > rules.max_open for r in filled)):
        raise AssertionError('position cap exceeded')
    metrics['max_opening_gross'] = max((r['gross_after'] for r in filled), default=0.)
    metrics['max_opening_positions'] = max((r['positions_after'] for r in filled), default=0)
    gi.assert_no_same_day_rebuy(trades)
    signal = fc.signal_audit(d, trades)
    for day in plans:
        for row in day['orders']:
            row['code'] = str(d.A['codes'][row.pop('j')])
    entry_plan = {(day['day'], r['code'], r['kind']): r for day in plans for r in day['orders']
                  if r['type'] == 'entry' and r.get('execution') in ('filled', 'gap_moc')}
    add_plan = {(day['day'], r['code']): r for day in plans for r in day['orders']
                if r['type'] == 'add' and r.get('execution') == 'preopen_filled'}
    if len(entry_plan) != len(trades):
        raise AssertionError('opening entries do not reconcile')
    columns = {str(c): i for i, c in enumerate(d.A['codes'])}
    add_count = 0
    for t in trades:
        r = entry_plan[(t['entry'], t['code'], t['kind'])]
        e = t['executions'][0]
        if abs(e['shares'] - r['shares']) > 1e-12 or e['price'] != r['opening'] or e['price'] > r['limit']:
            raise AssertionError('opening differs from reservation')
        if r['execution'] == 'gap_moc':
            j = columns[t['code']]
            if (t['why'] != 'gap_moc' or t['exit'] != t['entry'] or
                    t['executions'][-1]['price'] != float(d.A['close'][d.di[t['entry']], j])):
                raise AssertionError('gap exit is not the same-day closing price')
        for e in t['executions']:
            if e['action'] == 'add':
                add_count += 1
                r = add_plan[(e['time'], t['code'])]
                if abs(e['shares'] - r['shares']) > 1e-12 or e['price'] != r['opening'] or e['price'] > r['limit']:
                    raise AssertionError('add differs from reservation')
    if add_count != len(add_plan):
        raise AssertionError('add executions do not reconcile')
    gap_days = {t['exit'] for t in trades if t['why'] == 'gap_moc'}
    for day in gap_days:
        same_day = [t for t in trades if t['exit'] == day and t['why'] != 'end']
        first_gap = next(i for i, t in enumerate(same_day) if t['why'] == 'gap_moc')
        if any(t['why'] != 'gap_moc' for t in same_day[first_gap:]):
            raise AssertionError('market-on-close gap exit preceded another actual exit')
    annual = {}
    for y in ('2024', '2025', '2026'):
        rows = [r for day in plans if day['day'].startswith(y) for r in day['orders']]
        annual[y] = {kind: {'attempts': sum(r['type'] == kind for r in rows),
                            'reservation': dict(Counter(r['status'] for r in rows if r['type'] == kind)),
                            'reasons': dict(Counter(r.get('reason') for r in rows if r['type'] == kind and
                                                    r['status'] != 'submitted')),
                            'execution': dict(Counter(r.get('execution', 'not_attempted') for r in rows
                                                      if r['type'] == kind and r['status'] == 'submitted'))}
                     for kind in ('entry', 'add')}
    return {'metrics': metrics, 'fidelity': fidelity(d, trades), 'trades_digest': digest(trades),
            'trade_keys': [[t['code'], t['side'], t['kind'], t['entry'], t['exit'], t['why']] for t in trades],
            'trades': trades, 'annual_orders': annual, 'plans': plans, 'trail_audit': signal}



def main():
    root = du.REPORTS
    hp, dp, bp = (root / f'strong_continue_{n}.json' for n in ('hc', 'hd', 'hb'))
    h, previous, source = (json.loads(p.read_text()) for p in (hp, dp, bp))
    old_engine = root / 'source_pins/system_pre_he.py.txt'
    if (h['script_sha256'] != sha(Path(hc.__file__)) or previous['script_sha256'] != sha(Path(hd.__file__)) or
            h['system_sha256'] != sha(old_engine) or previous['system_sha256'] != sha(old_engine) or
            h['planner_sha256'] != sha(Path(preopen.__file__)) or previous['planner_sha256'] != sha(Path(preopen.__file__)) or
            h['hb_sha256'] != sha(bp) or previous['hc_sha256'] != sha(hp) or
            source['script_sha256'] != sha(Path(hb.__file__)) or hb.sha_bytes(source['orders']) != source['preorders_digest']):
        raise ValueError('HC / HD / HB source differs')
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    data_digest = ds.digest()
    if any(x['dataset_digest'] != data_digest for x in (h, previous, source)):
        raise ValueError('frozen data differs')
    expected_low = {n: hd.compact_reference(r) for n, r in h['results'].items()}
    expected_open = {n: hd.compact_reference(r) for n, r in previous['same_open'].items()}
    baseline = {n: {'metrics': h['results'][n]['metrics'], 'fidelity': h['results'][n]['fidelity'],
                    'trade_keys': h['results'][n]['trade_keys']} for n in h['results']}
    optimistic = {n: {'metrics': r['metrics'], 'fidelity': r['fidelity'], 'trade_keys': r['trade_keys']}
                  for n, r in previous['same_open'].items()}
    original_comparators = {n: {'metrics': r['metrics'], 'fidelity': r['fidelity']}
                            for n, r in h['baseline'].items()}
    old_unknown, orders, observations = h['unknown_low'], source['orders'], source['observations']
    del h, previous, source
    gc.collect()
    d = du.make_data(ds)
    del d.fp, d.fwd, d.raw
    gc.collect()
    cash = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True, no_rebuy_day=True)
    cash = replace(cash, intraday_kinds=tuple(sorted(set(cash.intraday_kinds) | {'n1', 'list'})))
    lever = f1_rules(d, 6, (1, 3))
    lever = replace(lever, intraday_kinds=tuple(lever.intraday_kinds) + ('n1', 'list'),
                    trail_next_open=True, add_next_open=True, no_rebuy_day=True, feedback_prior_close=True)
    results, changed = {}, {}
    for hit, scenario in ((True, 'hit'), (False, 'nohit')):
        book, _, unknown = hc.make_books(d, orders, observations, hit)
        if unknown != old_unknown[scenario]:
            raise AssertionError('prior precision list differs')
        for name, rules in (('cash', cash), ('lever', lever)):
            prior = book if name == 'lever' else [[e for e in row if e[5] == 'n1'] for row in book]
            key = name + ':' + scenario
            print('account', key, 'stress', flush=True)
            stress = hc.account(d, prior, rules)
            if hd.compact_reference(stress) != expected_low[key]:
                raise AssertionError('HC reference differs: ' + key)
            ideal, _ = hd.at_open_proxy(prior)
            print('account', key, 'same-open', flush=True)
            ideal_result = hd.account(d, ideal, rules)
            if hd.compact_reference(ideal_result) != expected_open[key]:
                raise AssertionError('HD reference differs: ' + key)
            closing, changes = at_close_proxy(d, prior)
            print('account', key, 'close', flush=True)
            results[key] = account(d, closing, rules)
            changed[key] = len(changes)
    out = {'dataset_digest': data_digest, 'hc_sha256': sha(hp), 'hd_sha256': sha(dp), 'hb_sha256': sha(bp),
           'old_engine_sha256': sha(old_engine), 'system_sha256': sha(Path(system.__file__)),
           'planner_sha256': sha(Path(preopen.__file__)), 'script_sha256': sha(Path(__file__)),
           'candidate_gap_keys': changed, 'old_comparators': original_comparators,
           'stress': baseline, 'same_open': optimistic, 'market_close': results}
    target = root / 'strong_continue_he.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False,
                                 default=json_default) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
