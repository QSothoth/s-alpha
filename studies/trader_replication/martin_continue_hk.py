"""HK: H4 ranking against seeded same-candidate random orders."""
from dataclasses import replace
import gc
import json
from pathlib import Path
from random import Random

import numpy as np

from studies import trader_data
from studies.trader_replication import preopen, system
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ep as ep
from studies.trader_replication import martin_continue_hb as hb
from studies.trader_replication import martin_continue_hc as hc
from studies.trader_replication import martin_continue_hd as hd
from studies.trader_replication import martin_continue_he as he
from studies.trader_replication import martin_continue_hh as hh
from studies.trader_replication import martin_continue_hj as hj
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import f1_rules, nl_rules


def randomize(book, seed):
    rng = Random(seed)
    return [[(e[0][:-1] + (rng.random(),),) + tuple(e[1:]) if e[5] == 'list' else e
             for e in row] for row in book]


def main():
    report = du.REPORTS / 'strong_continue_hj.json'
    source = json.loads(report.read_text())
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if (ds.digest() != source['dataset_digest'] or source['source_sha256']['script'] != sha(Path(hj.__file__)) or
            source['source_sha256']['system'] != sha(Path(system.__file__)) or
            source['source_sha256']['planner'] != sha(Path(preopen.__file__))):
        raise ValueError('HJ data, source or engine differs')
    expected_orders = source['orders']['H4']
    expected = {name: hd.compact_reference(source['results'][name + ':H4:hit']) for name in ('cash', 'lever')}
    del source
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
    actual_orders, book = hj.freeze(d, fields, mask, 'H4')
    if actual_orders != expected_orders:
        raise AssertionError('HJ H4 orders differ')
    del fields, mask
    gc.collect()
    cash = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True, no_rebuy_day=True)
    cash = replace(cash, intraday_kinds=tuple(sorted(set(cash.intraday_kinds) | {'n1', 'list'})))
    lever = f1_rules(d, 6, (1, 3))
    lever = replace(lever, intraday_kinds=tuple(lever.intraday_kinds) + ('n1', 'list'),
                    trail_next_open=True, add_next_open=True, no_rebuy_day=True, feedback_prior_close=True)
    reference_obs = hh.observations(d, actual_orders)
    base_book, _, _ = hc.make_books(d, actual_orders, reference_obs, True)
    base_book, _ = he.at_close_proxy(d, base_book)
    for name, rules in (('cash', cash), ('lever', lever)):
        print('reference', name, flush=True)
        result = he.account(d, base_book, rules)
        if hd.compact_reference(result) != expected[name]:
            raise AssertionError('HJ H4 account differs: ' + name)
    expected_core = [r for r in expected_orders if r['kind'] == 'n1']
    expected_width = {}
    for order in expected_orders:
        expected_width[order['day']] = expected_width.get(order['day'], 0) + (order['kind'] == 'list')
    draws = []
    for seed in range(1, 31):
        print('seed', seed, flush=True)
        shuffled = randomize(book, seed)
        orders = hb.freeze_orders(d.days, d.A['codes'], shuffled, d.A['close'])
        if [r for r in orders if r['kind'] == 'n1'] != expected_core:
            raise AssertionError('core differs')
        width = {}
        for order in orders:
            width[order['day']] = width.get(order['day'], 0) + (order['kind'] == 'list')
        if width != expected_width:
            raise AssertionError('daily candidate count differs')
        obs = hh.observations(d, orders)
        entries, _, unknown = hc.make_books(d, orders, obs, True)
        entries, _ = he.at_close_proxy(d, entries)
        draw = {'seed': seed, 'orders_digest': hb.sha_bytes(orders), 'unknown_low_count': len(unknown)}
        for name, rules in (('cash', cash), ('lever', lever)):
            result = he.account(d, entries, rules)
            draw[name] = {k: result[k] for k in ('metrics', 'fidelity', 'trades_digest')}
        draws.append(draw)
        del shuffled, orders, obs, entries, result
        gc.collect()
    out = {'dataset_digest': ds.digest(), 'hj_sha256': sha(report), 'system_sha256': sha(Path(system.__file__)),
           'planner_sha256': sha(Path(preopen.__file__)), 'script_sha256': sha(Path(__file__)), 'draws': draws}
    target = du.REPORTS / 'strong_continue_hk.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False,
                                 default=json_default) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
