"""HC: replay fixed-share preopen reservations in the existing account engine."""
from collections import Counter
from dataclasses import replace
import gc
import json
from pathlib import Path

import numpy as np

from studies import trader_data
from studies.trader_replication import compare, panels, system, preopen
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_fc as fc
from studies.trader_replication import martin_continue_fo as fo
from studies.trader_replication import martin_continue_gi as gi
from studies.trader_replication import martin_continue_gw as gw
from studies.trader_replication import martin_continue_gz as gz
from studies.trader_replication import martin_continue_hb as hb
from studies.trader_replication.martin_continue_b_check import digest
from studies.trader_replication.martin_continue_bm import describe
from studies.trader_replication.martin_continue_bt import fidelity
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import f1_rules, nl_rules


def tuple_priority(value):
    return tuple(tuple_priority(v) if isinstance(v, list) else v for v in value)


def make_books(d, orders, observations, hit):
    """Keep the full prior-selected book; a separate old book reproduces the reference."""
    full, old = [[] for _ in d.days], [[] for _ in d.days]
    columns = {str(code): j for j, code in enumerate(d.A['codes'])}
    unknown_low = []
    for row, obs in zip(orders, observations):
        if (row['day'], row['code'], row['kind']) != (obs['day'], obs['code'], obs['kind']):
            raise AssertionError('order and observation differ')
        day, j, stop = d.di[row['day']], columns[row['code']], row['stop']
        if d.days[day - 1] != row['signal_day'] or float(d.A['close'][day - 1, j]) != row['close']:
            raise AssertionError('prior close differs')
        opening, low = float(d.A['open'][day, j]), float(d.A['low'][day, j])
        valid_open = np.isfinite(opening) and opening > 0
        valid_low = np.isfinite(low) and low > 0
        if ((opening if valid_open else None), (low if valid_low else None)) != (obs['opening'], obs['low']):
            raise AssertionError('opening observation differs')
        same_low = valid_low and np.float32(low) == np.float32(stop)
        if same_low:
            unknown_low.append([row['day'], row['code'], row['kind']])
        if not valid_open or not valid_low:
            day_exit = None
        elif opening < stop:
            day_exit = low
        elif same_low:
            day_exit = stop if hit else None
        else:
            day_exit = stop if low <= stop else None
        e = (tuple_priority(row['priority']), j, 1, opening, stop, row['kind'], day_exit,
             row['size_risk'], row['max_position'], row['risk_mult'], row['add_mult'], valid_low)
        full[day].append(e)
        if obs['status'] == 'old_accepted':
            old[day].append(e)
    return full, old, unknown_low


def account(d, book, rules):
    px, ema, track = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules), {}
    curve, dates, trades = system.simulate(px, ema, rules, book, *panels.WINDOW, audit=True, track=track, preopen=True)
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
            raise AssertionError('prior reservations exceed available budget')
        for r in day['orders']:
            if r['type'] == 'entry' and r['status'] == 'submitted':
                risk = r['shares'] * (r['limit'] - r['stop'])
                if risk > r['risk_fraction'] * day['equity'] + 1e-10:
                    raise AssertionError('prior reservation exceeds the risk budget')
    planned_entries = [r for day in plans for r in day['orders'] if r['type'] == 'entry']
    planned_adds = [r for day in plans for r in day['orders'] if r['type'] == 'add']
    submitted = [r for r in planned_entries if r['status'] == 'submitted']
    if any('execution' not in r for r in submitted):
        raise AssertionError('submitted entry has no opening disposition')
    actual = sum(r.get('execution') in ('filled', 'gap_stress') for r in submitted)
    if actual != len(trades):
        raise AssertionError('entry count does not reconcile')
    adds = sum(r.get('execution') == 'preopen_filled' for r in planned_adds)
    if adds != sum(e['action'] == 'add' for t in trades for e in t['executions']):
        raise AssertionError('add count does not reconcile')
    if rules.gross_cost and any(r.get('cash_after', 0.) < -1e-10 for r in planned_entries + planned_adds):
        raise AssertionError('cash account borrowed at the open')
    if rules.max_open and max(track['open']) > rules.max_open:
        raise AssertionError('close position cap exceeded')
    filled = [r for r in planned_entries + planned_adds if r.get('execution') in
              ('filled', 'gap_stress', 'preopen_filled')]
    if any(r.get('gross_after') is None for r in filled):
        raise AssertionError('opening equity is not positive')
    if rules.max_open and any(r['positions_after'] > rules.max_open for r in filled):
        raise AssertionError('opening position cap exceeded')
    metrics['max_opening_gross'] = max((r['gross_after'] for r in filled), default=0.)
    metrics['max_opening_positions'] = max((r['positions_after'] for r in filled), default=0)
    gi.assert_no_same_day_rebuy(trades)
    signal = fc.signal_audit(d, trades)
    for day in plans:
        for r in day['orders']:
            r['code'] = str(d.A['codes'][r.pop('j')])
    planned = {(day['day'], r['code'], r['kind']): r for day in plans for r in day['orders']
               if r['type'] == 'entry' and r.get('execution') in ('filled', 'gap_stress')}
    planned_add = {(day['day'], r['code']): r for day in plans for r in day['orders']
                   if r['type'] == 'add' and r.get('execution') == 'preopen_filled'}
    columns = {str(c): i for i, c in enumerate(d.A['codes'])}
    for t in trades:
        k = (t['entry'], t['code'], t['kind'])
        r = planned[k]
        entry = t['executions'][0]
        if (abs(entry['shares'] - r['shares']) > 1e-12 or entry['price'] != r['opening'] or
                entry['price'] > r['limit']):
            raise AssertionError('filled entry differs from the prior order')
        if r['execution'] == 'gap_stress':
            j = columns[t['code']]
            if t['why'] != 'stop_day0' or t['executions'][-1]['price'] != float(d.A['low'][d.di[t['entry']], j]):
                raise AssertionError('gap stress exit differs from the daily low')
        for e in t['executions']:
            if e['action'] == 'add':
                r = planned_add[(e['time'], t['code'])]
                if abs(e['shares'] - r['shares']) > 1e-12 or e['price'] != r['opening'] or e['price'] > r['limit']:
                    raise AssertionError('filled add differs from the prior order')
    annual = {}
    for y in ('2024', '2025', '2026'):
        rows = [r for day in plans if day['day'].startswith(y) for r in day['orders']]
        annual[y] = {kind: {'attempts': sum(r['type'] == kind for r in rows),
                            'reservation': dict(Counter(r['status'] for r in rows if r['type'] == kind)),
                            'reasons': dict(Counter(r.get('reason') for r in rows if r['type'] == kind
                                                    and r['status'] != 'submitted')),
                            'execution': dict(Counter(r.get('execution', 'not_attempted') for r in rows
                                                      if r['type'] == kind and r['status'] == 'submitted'))}
                     for kind in ('entry', 'add')}
    return {'metrics': metrics, 'fidelity': fidelity(d, trades), 'trades_digest': digest(trades),
            'trade_keys': [[t['code'], t['side'], t['kind'], t['entry'], t['exit'], t['why']] for t in trades],
            'trades': trades, 'annual_orders': annual, 'plans': plans, 'trail_audit': signal}


def main():
    root = du.REPORTS
    hb_path, gz_path, gw_path = (root / f'strong_continue_{n}.json' for n in ('hb', 'gz', 'gw'))
    b, z, w = (json.loads(p.read_text()) for p in (hb_path, gz_path, gw_path))
    old_engine = root / 'source_pins/system_pre_hc.py.txt'
    if (b['script_sha256'] != sha(Path(hb.__file__)) or b['system_sha256'] != sha(old_engine) or
            z['script_sha256'] != sha(Path(gz.__file__)) or z['system_sha256'] != sha(old_engine) or
            w['script_sha256'] != sha(Path(gw.__file__))):
        raise ValueError('reference source differs')
    if hb.sha_bytes(b['orders']) != b['preorders_digest']:
        raise AssertionError('prior order digest differs')
    dataset = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    data_digest = dataset.digest()
    if any(x['dataset_digest'] != data_digest for x in (b, z, w)):
        raise ValueError('frozen dataset differs')
    expected_cash = {s: w['results']['C0:' + s] for s in ('hit', 'nohit')}
    expected_lever = {s: z['results']['L0:' + s + ':prior'] for s in ('hit', 'nohit')}
    orders, observations = b['orders'], b['observations']
    del b, z, w
    gc.collect()
    d = du.make_data(dataset)
    del d.fp, d.fwd, d.raw
    gc.collect()
    cash = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True, no_rebuy_day=True)
    cash = replace(cash, intraday_kinds=tuple(sorted(set(cash.intraday_kinds) | {'n1', 'list'})))
    lever = f1_rules(d, 6, (1, 3))
    lever = replace(lever, intraday_kinds=tuple(lever.intraday_kinds) + ('n1', 'list'),
                    trail_next_open=True, add_next_open=True, no_rebuy_day=True, feedback_prior_close=True)
    results, baselines, unknowns = {}, {}, {}
    for hit, scenario in ((True, 'hit'), (False, 'nohit')):
        book, old, unknowns[scenario] = make_books(d, orders, observations, hit)
        for name, rules in (('cash', cash), ('lever', lever)):
            current = book if name == 'lever' else [[e for e in row if e[5] == 'n1'] for row in book]
            original = old if name == 'lever' else [[e for e in row if e[5] == 'n1'] for row in old]
            baseline = fo.account(d, original, rules)
            expected = expected_lever[scenario] if name == 'lever' else expected_cash[scenario]
            if baseline != expected:
                raise AssertionError('existing account differs: ' + name + ':' + scenario)
            baselines[name + ':' + scenario] = baseline
            print('account', name, scenario, flush=True)
            results[name + ':' + scenario] = account(d, current, rules)
    out = {'dataset_digest': data_digest, 'hb_sha256': sha(hb_path), 'gz_sha256': sha(gz_path),
           'old_engine_sha256': sha(old_engine), 'system_sha256': sha(Path(system.__file__)),
           'planner_sha256': sha(Path(preopen.__file__)), 'script_sha256': sha(Path(__file__)),
           'baseline': baselines, 'unknown_low': unknowns, 'results': results}
    target = root / 'strong_continue_hc.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False,
                                 default=json_default) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
