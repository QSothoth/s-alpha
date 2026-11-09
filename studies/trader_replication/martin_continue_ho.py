"""HO: same-pool random accounts for the fill-relative protection strategy."""
from dataclasses import replace
import gc
import json
from pathlib import Path
import sys

import numpy as np

from studies import trader_data
from studies.trader_replication import preopen, system
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ep as ep
from studies.trader_replication import martin_continue_hb as hb
from studies.trader_replication import martin_continue_hc as hc
from studies.trader_replication import martin_continue_hd as hd
from studies.trader_replication import martin_continue_hh as hh
from studies.trader_replication import martin_continue_hj as hj
from studies.trader_replication import martin_continue_hk as hk
from studies.trader_replication import martin_continue_hn as hn
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import f1_rules, nl_rules


def paths():
    return {'HJ': du.REPORTS / 'strong_continue_hj.json', 'HN': du.REPORTS / 'strong_continue_hn.json',
            'system': Path(system.__file__), 'planner': Path(preopen.__file__),
            'hj_script': Path(hj.__file__), 'hk_script': Path(hk.__file__),
            'hn_script': Path(hn.__file__), 'script': Path(__file__)}


def prepare():
    p = paths()
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    hn_report = json.loads(p['HN'].read_text())
    if (hn_report['dataset_digest'] != ds.digest() or hn_report['source_sha256']['HJ'] != sha(p['HJ']) or
            hn_report['source_sha256']['system'] != sha(p['system']) or
            hn_report['source_sha256']['planner'] != sha(p['planner']) or
            hn_report['source_sha256']['script'] != sha(p['hn_script'])):
        raise ValueError('HN input differs')
    references = {name: hd.compact_reference(hn_report['results'][f'low:{name}:both:hit'])
                  for name in ('cash6', 'cash11', 'lever')}
    del hn_report
    gc.collect()
    source = json.loads(p['HJ'].read_text())
    if source['dataset_digest'] != ds.digest() or source['source_sha256']['script'] != sha(p['hj_script']):
        raise ValueError('HJ input differs')
    orders = source['orders']['H4']
    del source
    gc.collect()
    result = {'dataset_digest': ds.digest(), 'source_sha256': {name: sha(path) for name, path in p.items()},
              'orders': orders, 'references': references}
    target = du.REPORTS / 'strong_continue_ho_inputs.json'
    with target.open('w', encoding='utf-8') as output:
        json.dump(result, output, ensure_ascii=False, separators=(',', ':'), allow_nan=False, default=json_default)
        output.write('\n')
    print('prepared', target, flush=True)


def run():
    ip = du.REPORTS / 'strong_continue_ho_inputs.json'
    data = json.loads(ip.read_text())
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    p = paths()
    if (data['dataset_digest'] != ds.digest() or
            any(data['source_sha256'][name] != sha(path) for name, path in p.items())):
        raise ValueError('prepared sources differ')
    expected_orders, references = data['orders'], data['references']
    del data
    gc.collect()
    d = du.make_data(ds)
    fields, mask, unused = du.compute_fields(d)
    del unused
    gc.collect()
    events, eligible, _ = ep.causal_inputs(ds, d, list(map(str, d.A['codes'])))
    fast = np.empty(events.shape, np.float32)
    for start in range(0, events.shape[1], 64):
        sl = slice(start, start + 64)
        fast[:, sl] = du._ROLL_MEAN(events[:, sl].astype(np.float32), 250)
    fields['fast250'] = fast
    del events, fast
    peer, pot = ep.peer_potential(d, eligible)
    fields['peer_pot'] = peer
    del peer, pot, eligible
    gc.collect()
    fields.update(hj.coil_fields_chunked(d))
    original_orders, book = hj.freeze(d, fields, mask, 'H4')
    if original_orders != expected_orders:
        raise AssertionError('H4 original preopen orders differ')
    del fields, mask
    gc.collect()
    cash = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True, no_rebuy_day=True)
    cash = replace(cash, intraday_kinds=tuple(sorted(set(cash.intraday_kinds) | {'n1', 'list'})))
    cash11 = replace(cash, max_open=11, max_position=1 / 11)
    lever = f1_rules(d, 6, (1, 3))
    lever = replace(lever, intraday_kinds=tuple(lever.intraday_kinds) + ('n1', 'list'),
                    trail_next_open=True, add_next_open=True, no_rebuy_day=True, feedback_prior_close=True)
    accounts = (('cash6', cash), ('cash11', cash11), ('lever', lever))
    source, _, _ = hc.make_books(d, original_orders, hh.observations(d, original_orders), True)
    fixed = {'n1': .025, 'list': .025}
    for name, rules in accounts:
        print('reference', name, flush=True)
        if hd.compact_reference(hn.account(d, source, rules, fixed, True)) != references[name]:
            raise AssertionError('HN original account differs: ' + name)
    del source
    gc.collect()
    expected_core = [x for x in original_orders if x['kind'] == 'n1']
    widths = {}
    for order in original_orders:
        widths[order['day']] = widths.get(order['day'], 0) + (order['kind'] == 'list')
    draws = []
    progress = du.REPORTS / 'strong_continue_ho_progress.jsonl'
    with progress.open('w', encoding='utf-8') as output:
        for seed in range(1, 31):
            print('seed', seed, flush=True)
            shuffled = hk.randomize(book, seed)
            orders = hb.freeze_orders(d.days, d.A['codes'], shuffled, d.A['close'])
            if [x for x in orders if x['kind'] == 'n1'] != expected_core:
                raise AssertionError('core orders differ')
            actual_width = {}
            for order in orders:
                actual_width[order['day']] = actual_width.get(order['day'], 0) + (order['kind'] == 'list')
            if actual_width != widths:
                raise AssertionError('daily list widths differ')
            source, _, _ = hc.make_books(d, orders, hh.observations(d, orders), True)
            draw = {'seed': seed, 'orders_digest': hb.sha_bytes(orders)}
            for name, rules in accounts:
                result = hn.account(d, source, rules, fixed, True)
                draw[name] = {key: result[key] for key in ('metrics', 'fidelity', 'winner_loss_stats', 'trades_digest')}
            draws.append(draw)
            output.write(json.dumps(draw, ensure_ascii=False, separators=(',', ':'), allow_nan=False,
                                    default=json_default) + '\n')
            output.flush()
            del shuffled, orders, source, result
            gc.collect()
    out = {'dataset_digest': ds.digest(), 'inputs_sha256': sha(ip),
           'source_sha256': {name: sha(path) for name, path in p.items()}, 'draws': draws}
    target = du.REPORTS / 'strong_continue_ho.json'
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
