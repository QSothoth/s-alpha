"""HW: cap only initial core orders while leaving winner adds unchanged."""
from collections import Counter
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
from studies.trader_replication import martin_continue_hn as hn
from studies.trader_replication import martin_continue_hp as hp
from studies.trader_replication import martin_continue_ht as ht
from studies.trader_replication import martin_continue_hv as hv
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import f1_rules


def paths():
    return {'HV': du.REPORTS / 'strong_continue_hv.json', 'HV_inputs': du.REPORTS / 'strong_continue_hv_inputs.json',
            'HT': du.REPORTS / 'strong_continue_ht.json', 'HP': du.REPORTS / 'strong_continue_hp.json',
            'system': Path(system.__file__), 'planner': Path(preopen.__file__),
            'hv_script': Path(hv.__file__), 'ht_script': Path(ht.__file__), 'hp_script': Path(hp.__file__),
            'hn_script': Path(hn.__file__), 'script': Path(__file__)}


def cap_core(orders, cap=.25):
    result = []
    for order in orders:
        if order['kind'] != 'n1':
            result.append(order)
        else:
            old = order['max_position']
            result.append({**order, 'max_position': min(old, cap) if old is not None else cap})
    return result


def assert_caps(plans):
    count = Counter()
    for day in plans:
        for order in day['orders']:
            if order['type'] == 'entry' and order['kind'] == 'n1' and order['status'] == 'submitted':
                if order['shares'] * order['limit'] > .25 * day['equity'] + 1e-10:
                    raise AssertionError('initial core reservation exceeds cap')
                count[day['day'][:4]] += 1
    return dict(count)


def prepare():
    p = paths()
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    v = json.loads(p['HV'].read_text())
    if (v['dataset_digest'] != ds.digest() or v['inputs_sha256'] != sha(p['HV_inputs']) or
            v['source_sha256']['script'] != sha(p['hv_script']) or
            v['source_sha256']['system'] != sha(p['system']) or v['source_sha256']['planner'] != sha(p['planner']) or
            v['source_sha256']['HT'] != sha(p['HT']) or v['source_sha256']['HP'] != sha(p['HP'])):
        raise ValueError('HV reference differs')
    refs = {f'{label}:hold:{s}': hd.compact_reference({k: val for k, val in v['results'][f'lever_{label}:{s}'].items()
                                                       if k != 'duration_stats'})
            for label in ('ht', 'hp') for s in ('hit', 'nohit')}
    del v
    gc.collect()
    for label in ('ht', 'hp'):
        report = json.loads(p[label.upper()].read_text())
        if (report['dataset_digest'] != ds.digest() or report['source_sha256']['script'] != sha(p[label + '_script']) or
                report['source_sha256']['system'] != sha(p['system']) or report['source_sha256']['planner'] != sha(p['planner'])):
            raise ValueError('original report differs')
        for s in ('hit', 'nohit'):
            refs[f'{label}:partial:{s}'] = hd.compact_reference(report['results'][f'lever:{s}'])
        del report
        gc.collect()
    data = json.loads(p['HV_inputs'].read_text())
    cases = {label: {k: data['cases']['lever_' + label][k] for k in ('orders', 'observations')}
             for label in ('ht', 'hp')}
    out = {'dataset_digest': ds.digest(), 'source_sha256': {k: sha(v) for k, v in p.items()},
           'cases': cases, 'references': refs}
    target = du.REPORTS / 'strong_continue_hw_inputs.json'
    with target.open('w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(',', ':'), allow_nan=False, default=json_default)
        fh.write('\n')
    print('prepared', target, flush=True)


def run():
    ip = du.REPORTS / 'strong_continue_hw_inputs.json'
    data = json.loads(ip.read_text())
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    p = paths()
    if data['dataset_digest'] != ds.digest() or any(data['source_sha256'][k] != sha(v) for k, v in p.items()):
        raise ValueError('prepared inputs differ')
    cases, refs = data['cases'], data['references']
    del data
    gc.collect()
    d = du.make_data(ds)
    del d.fp, d.fwd, d.raw
    gc.collect()
    lever = f1_rules(d, 6, (1, 3))
    lever = replace(lever, intraday_kinds=tuple(lever.intraday_kinds) + ('n1', 'list'),
                    trail_next_open=True, add_next_open=True, no_rebuy_day=True, feedback_prior_close=True)
    if lever.cap_adds_entry:
        raise AssertionError('entry cap would restrict adds')
    hold = hv.without_partial(lever)
    fixed, results, submitted = {'n1': .025, 'list': .025}, {}, {}
    for label in ('ht', 'hp'):
        orders, obs = cases[label]['orders'], cases[label]['observations']
        if obs is None:
            obs = hh.observations(d, orders)
        capped = cap_core(orders)
        for hit, scenario in ((True, 'hit'), (False, 'nohit')):
            original_book, _, _ = hc.make_books(d, orders, obs, hit)
            capped_book, _, _ = hc.make_books(d, capped, obs, hit)
            for mode, rules in (('partial', lever), ('hold', hold)):
                key = f'{label}:{mode}:{scenario}'
                print(key, 'reference', flush=True)
                base = hn.account(d, original_book, rules, fixed, hit)
                if hd.compact_reference(base) != refs[key]:
                    raise AssertionError('reference differs: ' + key)
                print(key, 'core cap', flush=True)
                res = hn.account(d, capped_book, rules, fixed, hit)
                submitted[key] = assert_caps(res['plans'])
                res['duration_stats'] = hv.duration_stats(res['trades'])
                res['entries_by_kind_year'] = {year: dict(Counter(t['kind'] for t in res['trades']
                                                                  if t['entry'].startswith(year)))
                                                for year in ('2024', '2025', '2026')}
                results[key] = res
    out = {'dataset_digest': ds.digest(), 'inputs_sha256': sha(ip),
           'source_sha256': {k: sha(v) for k, v in p.items()}, 'submitted_core': submitted, 'results': results}
    target = du.REPORTS / 'strong_continue_hw.json'
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
