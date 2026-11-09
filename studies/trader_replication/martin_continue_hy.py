"""HY: use the registered later trial-add levels in the cash account."""
from dataclasses import replace
import gc
import json
from pathlib import Path
import sys

from studies import trader_data
from studies.trader_replication import preopen, system
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_hc as hc
from studies.trader_replication import martin_continue_hd as hd
from studies.trader_replication import martin_continue_hn as hn
from studies.trader_replication import martin_continue_hv as hv
from studies.trader_replication import martin_continue_hx as hx
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import nl_rules


def paths():
    return {'HX': du.REPORTS / 'strong_continue_hx.json', 'HX_inputs': du.REPORTS / 'strong_continue_hx_inputs.json',
            'system': Path(system.__file__), 'planner': Path(preopen.__file__),
            'hx_script': Path(hx.__file__), 'hn_script': Path(hn.__file__),
            'hv_script': Path(hv.__file__), 'script': Path(__file__)}


def later_trial_add(rules):
    management = rules.management_by_kind
    if (management != {'n1': {'add_levels': (10, 20)}, 'list': {'add_levels': (1, 3)}} or
            not rules.gross_cost or not rules.add_next_open):
        raise ValueError('unexpected registered early-add rules')
    return replace(rules, management_by_kind={**management, 'list': {'add_levels': (3, 6)}})


def prepare():
    p = paths()
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    h = json.loads(p['HX'].read_text())
    if (h['dataset_digest'] != ds.digest() or h['inputs_sha256'] != sha(p['HX_inputs']) or
            h['source_sha256']['script'] != sha(p['hx_script']) or
            h['source_sha256']['system'] != sha(p['system']) or h['source_sha256']['planner'] != sha(p['planner'])):
        raise ValueError('HX reference differs')
    refs = {f'{label}:{s}': hd.compact_reference({k: v for k, v in h['results'][f'{label}:{s}'].items()
                    if k not in ('duration_stats', 'add_confirmation_audit')})
            for label in ('hold', 'add') for s in ('hit', 'nohit')}
    del h
    gc.collect()
    inp = json.loads(p['HX_inputs'].read_text())
    for s in ('hit', 'nohit'):
        refs[f'cash6:{s}'] = inp['references'][f'cash6:hold:{s}']
    out = {'dataset_digest': ds.digest(), 'source_sha256': {k: sha(v) for k, v in p.items()},
           'orders': inp['orders'], 'observations': inp['observations'], 'references': refs}
    target = du.REPORTS / 'strong_continue_hy_inputs.json'
    with target.open('w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(',', ':'), allow_nan=False, default=json_default)
        fh.write('\n')
    print('prepared', target, flush=True)


def run():
    ip = du.REPORTS / 'strong_continue_hy_inputs.json'
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
    six_hold = hv.without_partial(cash6)
    eleven_hold = hv.without_partial(replace(cash6, max_open=11, max_position=1 / 11))
    early = hx.winner_add_rules(eleven_hold)
    later = later_trial_add(early)
    fixed, results = {'n1': .025, 'list': .025}, {}
    for hit, scenario in ((True, 'hit'), (False, 'nohit')):
        book, _, _ = hc.make_books(d, orders, obs, hit)
        for label, rules in (('cash6', six_hold), ('hold', eleven_hold), ('add', early)):
            print(scenario, label, 'reference', flush=True)
            reference = hn.account(d, book, rules, fixed, hit)
            if hd.compact_reference(reference) != refs[label + ':' + scenario]:
                raise AssertionError('reference differs: ' + label + ':' + scenario)
        print(scenario, 'later trial adds', flush=True)
        result = hn.account(d, book, later, fixed, hit)
        result['duration_stats'] = hv.duration_stats(result['trades'])
        result['add_confirmation_audit'] = hx.audit_adds(d, book, later, hit, result['trades_digest'])
        results[scenario] = result
    out = {'dataset_digest': ds.digest(), 'inputs_sha256': sha(ip),
           'source_sha256': {k: sha(v) for k, v in p.items()}, 'results': results}
    target = du.REPORTS / 'strong_continue_hy.json'
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
