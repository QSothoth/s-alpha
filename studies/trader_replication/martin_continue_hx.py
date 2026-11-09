"""HX: eleven cash-funded trials and confirmed winner adds."""
from collections import Counter
from dataclasses import replace
import gc
import json
from pathlib import Path
import sys

from studies import trader_data
from studies.trader_replication import panels, preopen, system
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_hc as hc
from studies.trader_replication import martin_continue_hd as hd
from studies.trader_replication import martin_continue_hn as hn
from studies.trader_replication import martin_continue_hv as hv
from studies.trader_replication.martin_continue_b_check import digest
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import nl_rules


def paths():
    return {'HN': du.REPORTS / 'strong_continue_hn.json', 'HN_inputs': du.REPORTS / 'strong_continue_hn_inputs.json',
            'HV': du.REPORTS / 'strong_continue_hv.json', 'HV_inputs': du.REPORTS / 'strong_continue_hv_inputs.json',
            'system': Path(system.__file__), 'planner': Path(preopen.__file__),
            'hn_script': Path(hn.__file__), 'hv_script': Path(hv.__file__), 'script': Path(__file__)}


def winner_add_rules(rules):
    if (not rules.gross_cost or rules.max_open != 11 or abs(rules.max_position - 1 / 11) > 1e-12 or
            rules.max_gross != 1.0 or rules.trims or rules.add_levels or rules.add_r or
            rules.management_by_kind or rules.cap_adds_entry):
        raise ValueError('unexpected cash baseline')
    return replace(rules, add_next_open=True, add_frac=1., add_cap_mult=2., add_cap_limit=2 / 11,
                   management_by_kind={'n1': {'add_levels': (10, 20)}, 'list': {'add_levels': (1, 3)}})


def audit_adds(d, book, rules, hit, expected_digest):
    track = {}
    _, _, trades = system.simulate(d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules), rules, book,
                                   *panels.WINDOW, audit=True, track=track, preopen=True,
                                   preopen_fill_stop_pct_by_kind={'n1': .025, 'list': .025},
                                   preopen_fill_stop_hit=hit)
    if digest(trades) != expected_digest:
        raise AssertionError('independent add replay differs')
    days = {str(day): i for i, day in enumerate(d.days)}
    codes = {str(code): i for i, code in enumerate(d.A['codes'])}
    events = track.get('add_orders', [])
    confirmations = set()
    for e in events:
        if e['status'] == 'confirmed':
            if e['signal_day'] != e['day'] or d.c[days[e['day']], codes[e['code']]] < e['level']:
                raise AssertionError('add signal is not confirmed by close')
            confirmations.add((e['code'], e['entry_day'], e['signal_day'], e['level']))
    for e in events:
        if e['status'] == 'preopen_filled':
            if e['signal_day'] >= e['day'] or (e['code'], e['entry_day'], e['signal_day'], e['level']) not in confirmations:
                raise AssertionError('add execution precedes confirmation')
    return {y: dict(Counter(e['status'] for e in events if e['day'].startswith(y)))
            for y in ('2024', '2025', '2026')}


def prepare():
    p = paths()
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    n = json.loads(p['HN'].read_text())
    if (n['dataset_digest'] != ds.digest() or n['inputs_sha256'] != sha(p['HN_inputs']) or
            n['source_sha256']['script'] != sha(p['hn_script']) or
            n['source_sha256']['system'] != sha(p['system']) or n['source_sha256']['planner'] != sha(p['planner'])):
        raise ValueError('HN reference differs')
    refs = {f'{a}:partial:{s}': hd.compact_reference(n['results'][f'low:{a}:both:{s}'])
            for a in ('cash6', 'cash11') for s in ('hit', 'nohit')}
    del n
    gc.collect()
    v = json.loads(p['HV'].read_text())
    if (v['dataset_digest'] != ds.digest() or v['inputs_sha256'] != sha(p['HV_inputs']) or
            v['source_sha256']['script'] != sha(p['hv_script']) or v['source_sha256']['HN'] != sha(p['HN']) or
            v['source_sha256']['system'] != sha(p['system']) or v['source_sha256']['planner'] != sha(p['planner'])):
        raise ValueError('HV reference differs')
    for s in ('hit', 'nohit'):
        refs[f'cash6:hold:{s}'] = hd.compact_reference({k: x for k, x in v['results'][f'cash_h4:{s}'].items()
                                                        if k != 'duration_stats'})
    del v
    gc.collect()
    source = json.loads(p['HN_inputs'].read_text())
    out = {'dataset_digest': ds.digest(), 'source_sha256': {k: sha(v) for k, v in p.items()},
           'orders': source['orders'], 'observations': source['observations'], 'references': refs}
    target = du.REPORTS / 'strong_continue_hx_inputs.json'
    with target.open('w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(',', ':'), allow_nan=False, default=json_default)
        fh.write('\n')
    print('prepared', target, flush=True)


def run():
    ip = du.REPORTS / 'strong_continue_hx_inputs.json'
    data = json.loads(ip.read_text())
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    p = paths()
    if data['dataset_digest'] != ds.digest() or any(data['source_sha256'][k] != sha(v) for k, v in p.items()):
        raise ValueError('prepared inputs differ')
    orders, obs, refs = data['orders'], data['observations'], data['references']
    del data
    gc.collect()
    d = du.make_data(ds)
    del d.fp, d.fwd, d.raw
    gc.collect()
    cash6 = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True, no_rebuy_day=True)
    cash6 = replace(cash6, intraday_kinds=tuple(sorted(set(cash6.intraday_kinds) | {'n1', 'list'})))
    cash11 = replace(cash6, max_open=11, max_position=1 / 11)
    six_hold = hv.without_partial(cash6)
    eleven_hold = hv.without_partial(cash11)
    add = winner_add_rules(eleven_hold)
    fixed, results = {'n1': .025, 'list': .025}, {}
    for hit, scenario in ((True, 'hit'), (False, 'nohit')):
        book, _, _ = hc.make_books(d, orders, obs, hit)
        for label, rules in (('cash6:partial', cash6), ('cash6:hold', six_hold), ('cash11:partial', cash11)):
            print(scenario, label, 'reference', flush=True)
            reference = hn.account(d, book, rules, fixed, hit)
            if hd.compact_reference(reference) != refs[label + ':' + scenario]:
                raise AssertionError('reference differs: ' + label + ':' + scenario)
        for label, rules in (('hold', eleven_hold), ('add', add)):
            print(scenario, 'cash11', label, flush=True)
            result = hn.account(d, book, rules, fixed, hit)
            result['duration_stats'] = hv.duration_stats(result['trades'])
            if label == 'add':
                result['add_confirmation_audit'] = audit_adds(d, book, rules, hit, result['trades_digest'])
            results[label + ':' + scenario] = result
    out = {'dataset_digest': ds.digest(), 'inputs_sha256': sha(ip),
           'source_sha256': {k: sha(v) for k, v in p.items()}, 'results': results}
    target = du.REPORTS / 'strong_continue_hx.json'
    with target.open('w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(',', ':'), allow_nan=False, default=json_default)
        fh.write('\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    if sys.argv[1:] == ['prepare']:
        prepare()
    elif sys.argv[1:] == ['run']:
        run()
    else:
        raise SystemExit('expected prepare or run')
