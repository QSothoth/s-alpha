"""HQ: random selection within the same preselected H3/H4 union."""
from collections import defaultdict
from dataclasses import replace
import gc
import json
from pathlib import Path
from random import Random
import sys

from studies import trader_data
from studies.trader_replication import preopen, system
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_hb as hb
from studies.trader_replication import martin_continue_hc as hc
from studies.trader_replication import martin_continue_hd as hd
from studies.trader_replication import martin_continue_hh as hh
from studies.trader_replication import martin_continue_hm as hm
from studies.trader_replication import martin_continue_hn as hn
from studies.trader_replication import martin_continue_hp as hp
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import f1_rules, nl_rules


def random_union(h3, h4, seed):
    groups = defaultdict(lambda: {'core': [], 'list': {}})
    for order in h4:
        day = groups[order['day']]
        if order['kind'] == 'n1':
            day['core'].append(order)
        else:
            day['list'][order['code']] = order
    core3 = [x for x in h3 if x['kind'] == 'n1']
    if core3 != [x for x in h4 if x['kind'] == 'n1']:
        raise AssertionError('core differs')
    for order in h3:
        if order['kind'] != 'list':
            continue
        pool = groups[order['day']]['list']
        if order['code'] in pool:
            if {k: v for k, v in order.items() if k != 'priority'} != {
                    k: v for k, v in pool[order['code']].items() if k != 'priority'}:
                raise AssertionError('duplicate stock differs')
        else:
            pool[order['code']] = order
    rng, result = Random(seed), []
    for day in sorted(groups):
        result.extend(groups[day]['core'])
        pool = [{**order, 'priority': [2.0, 1.0, rng.random()]}
                for _, order in sorted(groups[day]['list'].items())]
        result.extend(sorted(pool, key=lambda x: x['priority'])[:6])
    return result


def paths():
    return {'HJ': du.REPORTS / 'strong_continue_hj.json', 'HP': du.REPORTS / 'strong_continue_hp.json',
            'HP_inputs': du.REPORTS / 'strong_continue_hp_inputs.json', 'system': Path(system.__file__),
            'planner': Path(preopen.__file__), 'hp_script': Path(hp.__file__),
            'hn_script': Path(hn.__file__), 'hm_script': Path(hm.__file__), 'script': Path(__file__)}


def prepare():
    p = paths()
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    h = json.loads(p['HP'].read_text())
    if (h['dataset_digest'] != ds.digest() or h['inputs_sha256'] != sha(p['HP_inputs']) or
            h['source_sha256']['system'] != sha(p['system']) or h['source_sha256']['planner'] != sha(p['planner']) or
            h['source_sha256']['script'] != sha(p['hp_script'])):
        raise ValueError('HP input differs')
    expected = {name: hd.compact_reference(h['results'][name + ':hit']) for name in ('cash6', 'cash11', 'lever')}
    del h
    gc.collect()
    prev = json.loads(p['HP_inputs'].read_text())
    blend = prev['blend_orders']
    del prev
    gc.collect()
    j = json.loads(p['HJ'].read_text())
    if j['dataset_digest'] != ds.digest():
        raise ValueError('HJ dataset differs')
    h3, h4 = j['orders']['H3'], j['orders']['H4']
    del j
    gc.collect()
    if hm.blend(h3, h4) != blend:
        raise AssertionError('HP blend differs from H3 / H4 sources')
    data = {'dataset_digest': ds.digest(), 'source_sha256': {name: sha(path) for name, path in p.items()},
            'h3_orders': h3, 'h4_orders': h4, 'blend_orders': blend, 'references': expected}
    target = du.REPORTS / 'strong_continue_hq_inputs.json'
    with target.open('w', encoding='utf-8') as output:
        json.dump(data, output, ensure_ascii=False, separators=(',', ':'), allow_nan=False, default=json_default)
        output.write('\n')
    print('prepared', target, flush=True)


def run():
    ip = du.REPORTS / 'strong_continue_hq_inputs.json'
    data = json.loads(ip.read_text())
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    p = paths()
    if (data['dataset_digest'] != ds.digest() or
            any(data['source_sha256'][name] != sha(path) for name, path in p.items())):
        raise ValueError('prepared sources differ')
    h3, h4, blend, references = (data[k] for k in ('h3_orders', 'h4_orders', 'blend_orders', 'references'))
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
    accounts = (('cash6', cash), ('cash11', cash11), ('lever', lever))
    fixed = {'n1': .025, 'list': .025}
    original, _, _ = hc.make_books(d, blend, hh.observations(d, blend), True)
    for name, rules in accounts:
        print('reference', name, flush=True)
        if hd.compact_reference(hn.account(d, original, rules, fixed, True)) != references[name]:
            raise AssertionError('HP original account differs: ' + name)
    del original
    gc.collect()
    core = [x for x in blend if x['kind'] == 'n1']
    widths = {}
    for order in blend:
        widths[order['day']] = widths.get(order['day'], 0) + (order['kind'] == 'list')
    draws = []
    progress = du.REPORTS / 'strong_continue_hq_progress.jsonl'
    with progress.open('w', encoding='utf-8') as output:
        for seed in range(1, 31):
            print('seed', seed, flush=True)
            orders = random_union(h3, h4, seed)
            if [x for x in orders if x['kind'] == 'n1'] != core:
                raise AssertionError('core orders changed')
            actual_width = {}
            for order in orders:
                actual_width[order['day']] = actual_width.get(order['day'], 0) + (order['kind'] == 'list')
            if actual_width != widths:
                raise AssertionError('candidate width changed')
            source, _, _ = hc.make_books(d, orders, hh.observations(d, orders), True)
            draw = {'seed': seed, 'orders_digest': hb.sha_bytes(orders)}
            for name, rules in accounts:
                result = hn.account(d, source, rules, fixed, True)
                draw[name] = {k: result[k] for k in ('metrics', 'fidelity', 'winner_loss_stats', 'trades_digest')}
            draws.append(draw)
            output.write(json.dumps(draw, ensure_ascii=False, separators=(',', ':'), allow_nan=False,
                                    default=json_default) + '\n')
            output.flush()
            del orders, source, result
            gc.collect()
    out = {'dataset_digest': ds.digest(), 'inputs_sha256': sha(ip),
           'source_sha256': {name: sha(path) for name, path in p.items()}, 'draws': draws}
    target = du.REPORTS / 'strong_continue_hq.json'
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
