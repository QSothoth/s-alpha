"""HN: fill-relative 2.5% protection with prior-close fixed-share sizing."""
from collections import Counter
from dataclasses import replace
import gc
import json
from pathlib import Path
import sys

import numpy as np

from studies import trader_data
from studies.trader_replication import compare, panels, preopen, system
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_fc as fc
from studies.trader_replication import martin_continue_gi as gi
from studies.trader_replication import martin_continue_hc as hc
from studies.trader_replication import martin_continue_hd as hd
from studies.trader_replication import martin_continue_hj as hj
from studies.trader_replication import martin_continue_hl as hl
from studies.trader_replication import martin_continue_hm as hm
from studies.trader_replication.martin_continue_b_check import digest
from studies.trader_replication.martin_continue_bm import describe
from studies.trader_replication.martin_continue_bt import fidelity
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import f1_rules, nl_rules


def account(d, book, rules, stop_kinds, hit):
    track = {}
    curve, dates, trades = system.simulate(d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules), rules, book,
                                           *panels.WINDOW, audit=True, track=track, preopen=True,
                                           preopen_fill_stop_pct_by_kind=stop_kinds,
                                           preopen_fill_stop_hit=hit)
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
            raise AssertionError('prior reservation exceeds account budget')
        for row in day['orders']:
            if row['type'] != 'entry' or row['status'] != 'submitted':
                continue
            expected = (row['limit'] * ((1 + rules.buy_cost) - (1 - stop_kinds[row['kind']]) * (1 - rules.sell_cost))
                        if row['kind'] in stop_kinds else row['limit'] - row['stop'])
            if row['kind'] in stop_kinds and abs(row['planned_loss_per_share'] - expected) > 1e-10:
                raise AssertionError('relative-stop planned loss differs')
            if row['shares'] * expected > row['risk_fraction'] * day['equity'] + 1e-10:
                raise AssertionError('prior risk budget exceeded')
    filled = [r for day in plans for r in day['orders'] if r.get('execution') in
              ('filled', 'gap_stress', 'preopen_filled')]
    if any(r.get('gross_after') is None for r in filled):
        raise AssertionError('non-positive opening equity')
    if rules.gross_cost and any(r.get('cash_after', 0.) < -1e-10 for r in filled):
        raise AssertionError('cash account borrowed')
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
    planned = {(day['day'], r['code'], r['kind']): r for day in plans for r in day['orders']
               if r['type'] == 'entry' and r.get('execution') in ('filled', 'gap_stress')}
    added = {(day['day'], r['code']): r for day in plans for r in day['orders']
             if r['type'] == 'add' and r.get('execution') == 'preopen_filled'}
    if len(planned) != len(trades):
        raise AssertionError('entry count differs from reservations')
    add_count = 0
    for trade in trades:
        row = planned[(trade['entry'], trade['code'], trade['kind'])]
        first = trade['executions'][0]
        if abs(first['shares'] - row['shares']) > 1e-12 or first['price'] != row['opening'] or first['price'] > row['limit']:
            raise AssertionError('entry differs from preopen plan')
        if trade['kind'] in stop_kinds:
            if abs(trade['stop'] - trade['fill'] * (1 - stop_kinds[trade['kind']])) > 1e-10:
                raise AssertionError('initial protection differs from actual fill')
            if trade['why'] == 'stop_day0' and abs(trade['executions'][-1]['price'] - trade['stop']) > 1e-10:
                raise AssertionError('day-zero stop differs from protection line')
        for execution in trade['executions']:
            if execution['action'] == 'add':
                add_count += 1
                row = added[(execution['time'], trade['code'])]
                if abs(execution['shares'] - row['shares']) > 1e-12 or execution['price'] != row['opening']:
                    raise AssertionError('add differs from preopen plan')
    if add_count != len(added):
        raise AssertionError('add count differs from plans')
    annual = {}
    for y in ('2024', '2025', '2026'):
        rows = [r for day in plans if day['day'].startswith(y) for r in day['orders']]
        annual[y] = {kind: {'attempts': sum(r['type'] == kind for r in rows),
                            'reservation': dict(Counter(r['status'] for r in rows if r['type'] == kind)),
                            'execution': dict(Counter(r.get('execution', 'not_attempted') for r in rows
                                                      if r['type'] == kind and r['status'] == 'submitted'))}
                     for kind in ('entry', 'add')}
    return {'metrics': metrics, 'fidelity': fidelity(d, trades), 'trades_digest': digest(trades),
            'trade_keys': [[t['code'], t['side'], t['kind'], t['entry'], t['exit'], t['why']] for t in trades],
            'trades': trades, 'annual_orders': annual, 'plans': plans, 'trail_audit': signal,
            'winner_loss_stats': hl.trade_stats(trades)}


def prepare():
    jp, lp, mp = (du.REPORTS / f'strong_continue_{n}.json' for n in ('hj', 'hl', 'hm'))
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    old_system = du.REPORTS / 'source_pins/before_hn_system.py.txt'
    old_planner = du.REPORTS / 'source_pins/before_hn_preopen.py.txt'
    j = json.loads(jp.read_text())
    if (j['dataset_digest'] != ds.digest() or j['source_sha256']['system'] != sha(old_system) or
            j['source_sha256']['planner'] != sha(old_planner)):
        raise ValueError('HJ data or old engine pins differ')
    orders, obs = j['orders']['H4'], j['observations']['H4']
    del j
    gc.collect()
    l = json.loads(lp.read_text())
    if l['dataset_digest'] != ds.digest() or l['hj_sha256'] != sha(jp) or l['script_sha256'] != sha(Path(hl.__file__)):
        raise ValueError('HL reference differs')
    prior = {}
    for mode in ('low', 'fast'):
        for scenario in ('hit', 'nohit'):
            for label, src in (('cash6', l['results'][f'{mode}:cash:H4:{scenario}']),
                               ('lever', l['results'][f'{mode}:lever:H4:{scenario}'])):
                prior[f'{mode}:{label}:{scenario}'] = hd.compact_reference(
                    {k: v for k, v in src.items() if k != 'winner_loss_stats'})
    del l
    gc.collect()
    m = json.loads(mp.read_text())
    if (m['dataset_digest'] != ds.digest() or m['hj_sha256'] != sha(jp) or m['hl_sha256'] != sha(lp) or
            m['script_sha256'] != sha(Path(hm.__file__))):
        raise ValueError('HM reference differs')
    for mode in ('low', 'fast'):
        for scenario in ('hit', 'nohit'):
            src = m['results'][f'{mode}:cash11:{scenario}']
            prior[f'{mode}:cash11:{scenario}'] = hd.compact_reference(
                {k: v for k, v in src.items() if k != 'winner_loss_stats'})
    del m
    gc.collect()
    paths = {'HJ': jp, 'HL': lp, 'HM': mp, 'old_system': old_system, 'old_planner': old_planner,
             'system': Path(system.__file__), 'planner': Path(preopen.__file__), 'script': Path(__file__)}
    output = {'dataset_digest': ds.digest(), 'source_sha256': {k: sha(p) for k, p in paths.items()},
              'orders': orders, 'observations': obs, 'prior': prior}
    target = du.REPORTS / 'strong_continue_hn_inputs.json'
    target.write_text(json.dumps(output, ensure_ascii=False, separators=(',', ':'), allow_nan=False,
                                 default=json_default) + '\n')
    print('prepared', target, flush=True)


def run():
    ip = du.REPORTS / 'strong_continue_hn_inputs.json'
    data = json.loads(ip.read_text())
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    paths = {'HJ': du.REPORTS / 'strong_continue_hj.json', 'HL': du.REPORTS / 'strong_continue_hl.json',
             'HM': du.REPORTS / 'strong_continue_hm.json',
             'old_system': du.REPORTS / 'source_pins/before_hn_system.py.txt',
             'old_planner': du.REPORTS / 'source_pins/before_hn_preopen.py.txt',
             'system': Path(system.__file__), 'planner': Path(preopen.__file__), 'script': Path(__file__)}
    if (data['dataset_digest'] != ds.digest() or
            any(data['source_sha256'][k] != sha(path) for k, path in paths.items())):
        raise ValueError('prepared sources differ')
    orders, obs, prior = data['orders'], data['observations'], data['prior']
    del data
    gc.collect()
    d = du.make_data(ds)
    del d.fp, d.fwd, d.raw
    gc.collect()
    cash = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True, no_rebuy_day=True)
    cash = replace(cash, intraday_kinds=tuple(sorted(set(cash.intraday_kinds) | {'n1', 'list'})))
    cash11 = replace(cash, max_open=11, max_position=1 / 11)
    lever = f1_rules(d, 6, (1, 3))
    lever = replace(lever, intraday_kinds=tuple(lever.intraday_kinds) + ('n1', 'list'),
                    trail_next_open=True, add_next_open=True, no_rebuy_day=True, feedback_prior_close=True)
    results, reference = {}, {}
    for hit, scenario in ((True, 'hit'), (False, 'nohit')):
        book, _, _ = hc.make_books(d, orders, obs, hit)
        for mode, fn in (('low', hc.account), ('fast', hd.account)):
            source = book if mode == 'low' else hd.at_open_proxy(book)[0]
            for label, rules in (('cash6', cash), ('cash11', cash11), ('lever', lever)):
                print(scenario, mode, label, 'original', flush=True)
                ref = fn(d, source, rules)
                key = f'{mode}:{label}:{scenario}'
                if hd.compact_reference(ref) != prior[key]:
                    raise AssertionError('original account differs: ' + key)
                reference[key] = {k: ref[k] for k in ('metrics', 'fidelity', 'trades_digest')}
                for choice, kinds in (('both', {'n1': .025, 'list': .025}), ('trial', {'list': .025})):
                    print(scenario, mode, label, choice, flush=True)
                    results[f'{mode}:{label}:{choice}:{scenario}'] = account(d, source, rules, kinds, hit)
    for label in ('cash6', 'cash11', 'lever'):
        for scenario in ('hit', 'nohit'):
            if hd.compact_reference(results[f'low:{label}:both:{scenario}']) != hd.compact_reference(
                    results[f'fast:{label}:both:{scenario}']):
                raise AssertionError('all-relative stop differs with obsolete gap proxy')
    out = {'dataset_digest': ds.digest(), 'inputs_sha256': sha(ip), 'source_sha256': {k: sha(p) for k, p in paths.items()},
           'baseline': reference, 'results': results}
    target = du.REPORTS / 'strong_continue_hn.json'
    with target.open('w', encoding='utf-8') as output:
        json.dump(out, output, ensure_ascii=False, separators=(',', ':'), allow_nan=False, default=json_default)
        output.write('\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    if sys.argv[1:] == ['prepare']:
        prepare()
    elif sys.argv[1:] == ['run']:
        run()
    else:
        raise SystemExit('expected prepare or run')
