"""HU: prior turnover ranking inside the fixed H3/H4 union."""
from collections import Counter, defaultdict
from dataclasses import replace
import gc
import json
from pathlib import Path
import sys

import numpy as np

from studies import trader_data
from studies.trader_replication import preopen, system
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_hc as hc
from studies.trader_replication import martin_continue_hd as hd
from studies.trader_replication import martin_continue_hh as hh
from studies.trader_replication import martin_continue_hm as hm
from studies.trader_replication import martin_continue_hn as hn
from studies.trader_replication import martin_continue_hp as hp
from studies.trader_replication import martin_continue_hq as hq
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import f1_rules, nl_rules


def turnover_union(h3, h4, day_index, code_index, turnover):
    groups = defaultdict(lambda: {'core': [], 'list': {}})
    for order in h4:
        group = groups[order['day']]
        if order['kind'] == 'n1':
            group['core'].append(order)
        else:
            group['list'][order['code']] = order
    if [x for x in h3 if x['kind'] == 'n1'] != [x for x in h4 if x['kind'] == 'n1']:
        raise AssertionError('core differs')
    for order in h3:
        if order['kind'] != 'list':
            continue
        pool = groups[order['day']]['list']
        old = pool.get(order['code'])
        if old is not None and {k: v for k, v in order.items() if k != 'priority'} != {
                k: v for k, v in old.items() if k != 'priority'}:
            raise AssertionError('duplicate stock differs')
        if old is None:
            pool[order['code']] = order
    result = []
    for day in sorted(groups):
        group = groups[day]
        result.extend(group['core'])
        def key(order):
            signal = day_index[order['signal_day']]
            if signal <= 0:
                raise ValueError('no prior signal-day turnover')
            value = turnover[signal - 1, code_index[order['code']]]
            return (-float(value) if np.isfinite(value) else float('inf'), order['code'])
        ranked = sorted(group['list'].values(), key=key)
        result.extend({**o, 'priority': [2.0, 1.0, float(rank)]}
                      for rank, o in enumerate(ranked[:6]))
    return result


def paths():
    return {'HQ_inputs': du.REPORTS / 'strong_continue_hq_inputs.json',
            'HQ': du.REPORTS / 'strong_continue_hq.json',
            'HP': du.REPORTS / 'strong_continue_hp.json', 'system': Path(system.__file__),
            'planner': Path(preopen.__file__), 'hq_script': Path(hq.__file__),
            'hp_script': Path(hp.__file__), 'hn_script': Path(hn.__file__), 'script': Path(__file__)}


def prepare():
    p = paths()
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    q = json.loads(p['HQ'].read_text())
    if (q['dataset_digest'] != ds.digest() or q['inputs_sha256'] != sha(p['HQ_inputs']) or
            q['source_sha256']['script'] != sha(p['hq_script']) or
            q['source_sha256']['HP'] != sha(p['HP']) or len(q['draws']) != 30):
        raise ValueError('HQ random reference differs')
    del q
    gc.collect()
    h = json.loads(p['HP'].read_text())
    if (h['dataset_digest'] != ds.digest() or h['source_sha256']['script'] != sha(p['hp_script']) or
            h['source_sha256']['system'] != sha(p['system']) or h['source_sha256']['planner'] != sha(p['planner'])):
        raise ValueError('HP reference differs')
    refs = {f'{a}:{s}': hd.compact_reference(h['results'][f'{a}:{s}'])
            for a in ('cash6', 'cash11', 'lever') for s in ('hit', 'nohit')}
    del h
    gc.collect()
    inp = json.loads(p['HQ_inputs'].read_text())
    if inp['dataset_digest'] != ds.digest() or hm.blend(inp['h3_orders'], inp['h4_orders']) != inp['blend_orders']:
        raise ValueError('HQ orders differ')
    out = {'dataset_digest': ds.digest(), 'source_sha256': {k: sha(v) for k, v in p.items()},
           'h3_orders': inp['h3_orders'], 'h4_orders': inp['h4_orders'],
           'blend_orders': inp['blend_orders'], 'references': refs}
    target = du.REPORTS / 'strong_continue_hu_inputs.json'
    with target.open('w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(',', ':'), allow_nan=False, default=json_default)
        fh.write('\n')
    print('prepared', target, flush=True)


def run():
    ip = du.REPORTS / 'strong_continue_hu_inputs.json'
    data = json.loads(ip.read_text())
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    p = paths()
    if data['dataset_digest'] != ds.digest() or any(data['source_sha256'][k] != sha(v) for k, v in p.items()):
        raise ValueError('prepared inputs differ')
    h3, h4, blend, refs = (data[k] for k in ('h3_orders', 'h4_orders', 'blend_orders', 'references'))
    del data
    gc.collect()
    d = du.make_data(ds)
    del d.fp, d.fwd, d.raw
    gc.collect()
    candidate = turnover_union(h3, h4, {str(x): i for i, x in enumerate(d.days)},
                               {str(x): i for i, x in enumerate(d.A['codes'])}, d.A['to20'])
    counts = lambda orders: Counter((x['day'], x['kind']) for x in orders)
    if counts(candidate) != counts(blend) or [x for x in candidate if x['kind'] == 'n1'] != [x for x in blend if x['kind'] == 'n1']:
        raise AssertionError('candidate widths or core differ')
    obs, candidate_obs = hh.observations(d, blend), hh.observations(d, candidate)
    cash = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True, no_rebuy_day=True)
    cash = replace(cash, intraday_kinds=tuple(sorted(set(cash.intraday_kinds) | {'n1', 'list'})))
    cash11 = replace(cash, max_open=11, max_position=1 / 11)
    lever = f1_rules(d, 6, (1, 3))
    lever = replace(lever, intraday_kinds=tuple(lever.intraday_kinds) + ('n1', 'list'),
                    trail_next_open=True, add_next_open=True, no_rebuy_day=True, feedback_prior_close=True)
    fixed, results = {'n1': .025, 'list': .025}, {}
    for hit, scenario in ((True, 'hit'), (False, 'nohit')):
        baseline, _, _ = hc.make_books(d, blend, obs, hit)
        book, _, _ = hc.make_books(d, candidate, candidate_obs, hit)
        for name, rules in (('cash6', cash), ('cash11', cash11), ('lever', lever)):
            print(scenario, name, 'original blend', flush=True)
            base = hn.account(d, baseline, rules, fixed, hit)
            if hd.compact_reference(base) != refs[name + ':' + scenario]:
                raise AssertionError('HP reference differs')
            print(scenario, name, 'turnover first', flush=True)
            results[name + ':' + scenario] = hn.account(d, book, rules, fixed, hit)
    out = {'dataset_digest': ds.digest(), 'inputs_sha256': sha(ip),
           'source_sha256': {k: sha(v) for k, v in p.items()}, 'orders': candidate,
           'observations': candidate_obs, 'results': results}
    target = du.REPORTS / 'strong_continue_hu.json'
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
