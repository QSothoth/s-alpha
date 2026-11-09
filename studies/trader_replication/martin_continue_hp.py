"""HP: the fixed H3/H4 blend with the same fill-relative protective stop."""
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
from studies.trader_replication import martin_continue_hh as hh
from studies.trader_replication import martin_continue_hm as hm
from studies.trader_replication import martin_continue_hn as hn
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import f1_rules, nl_rules


def paths():
    return {'HM': du.REPORTS / 'strong_continue_hm.json', 'HN': du.REPORTS / 'strong_continue_hn.json',
            'HN_inputs': du.REPORTS / 'strong_continue_hn_inputs.json', 'hm_script': Path(hm.__file__),
            'hn_script': Path(hn.__file__), 'system': Path(system.__file__), 'planner': Path(preopen.__file__),
            'script': Path(__file__)}


def prepare():
    p = paths()
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    n = json.loads(p['HN'].read_text())
    if (n['dataset_digest'] != ds.digest() or n['source_sha256']['HM'] != sha(p['HM']) or
            n['inputs_sha256'] != sha(p['HN_inputs']) or n['source_sha256']['system'] != sha(p['system']) or
            n['source_sha256']['planner'] != sha(p['planner']) or n['source_sha256']['script'] != sha(p['hn_script'])):
        raise ValueError('HN inputs or engine differ')
    references = {f'{name}:{scenario}': hd.compact_reference(n['results'][f'low:{name}:both:{scenario}'])
                  for name in ('cash6', 'cash11', 'lever') for scenario in ('hit', 'nohit')}
    old_system, old_planner = n['source_sha256']['old_system'], n['source_sha256']['old_planner']
    del n
    gc.collect()
    m = json.loads(p['HM'].read_text())
    if (m['dataset_digest'] != ds.digest() or m['script_sha256'] != sha(p['hm_script']) or
            m['system_sha256'] != old_system or m['planner_sha256'] != old_planner):
        raise ValueError('HM inputs or historical engine differ')
    blend = m['blend_orders']
    del m
    gc.collect()
    prior = json.loads(p['HN_inputs'].read_text())
    out = {'dataset_digest': ds.digest(), 'source_sha256': {k: sha(v) for k, v in p.items()},
           'blend_orders': blend, 'h4_orders': prior['orders'], 'h4_observations': prior['observations'],
           'references': references}
    target = du.REPORTS / 'strong_continue_hp_inputs.json'
    with target.open('w', encoding='utf-8') as output:
        json.dump(out, output, ensure_ascii=False, separators=(',', ':'), allow_nan=False, default=json_default)
        output.write('\n')
    print('prepared', target, flush=True)


def run():
    ip = du.REPORTS / 'strong_continue_hp_inputs.json'
    data = json.loads(ip.read_text())
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    p = paths()
    if data['dataset_digest'] != ds.digest() or any(data['source_sha256'][k] != sha(v) for k, v in p.items()):
        raise ValueError('prepared inputs differ')
    blend, h4, h4obs, references = (data[k] for k in ('blend_orders', 'h4_orders', 'h4_observations', 'references'))
    del data
    gc.collect()
    d = du.make_data(ds)
    del d.fp, d.fwd, d.raw
    gc.collect()
    obs = hh.observations(d, blend)
    cash = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True, no_rebuy_day=True)
    cash = replace(cash, intraday_kinds=tuple(sorted(set(cash.intraday_kinds) | {'n1', 'list'})))
    cash11 = replace(cash, max_open=11, max_position=1 / 11)
    lever = f1_rules(d, 6, (1, 3))
    lever = replace(lever, intraday_kinds=tuple(lever.intraday_kinds) + ('n1', 'list'),
                    trail_next_open=True, add_next_open=True, no_rebuy_day=True, feedback_prior_close=True)
    stop = {'n1': .025, 'list': .025}
    results = {}
    for hit, scenario in ((True, 'hit'), (False, 'nohit')):
        reference_book, _, _ = hc.make_books(d, h4, h4obs, hit)
        book, _, _ = hc.make_books(d, blend, obs, hit)
        for name, rules in (('cash6', cash), ('cash11', cash11), ('lever', lever)):
            print(scenario, name, 'original H4', flush=True)
            ref = hn.account(d, reference_book, rules, stop, hit)
            if hd.compact_reference(ref) != references[f'{name}:{scenario}']:
                raise AssertionError('HN account differs: ' + name + ':' + scenario)
            print(scenario, name, 'blend', flush=True)
            results[f'{name}:{scenario}'] = hn.account(d, book, rules, stop, hit)
    out = {'dataset_digest': ds.digest(), 'inputs_sha256': sha(ip),
           'source_sha256': {k: sha(v) for k, v in p.items()}, 'results': results}
    target = du.REPORTS / 'strong_continue_hp.json'
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
