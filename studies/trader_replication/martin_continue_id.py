"""ID: same-rule same-pool random accounts for the leveraged H4 hold line."""
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
from studies.trader_replication import martin_continue_hv as hv
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import f1_rules

FIXED = {'n1': .025, 'list': .025}


def paths():
    return {'HJ': du.REPORTS / 'strong_continue_hj.json', 'IA': du.REPORTS / 'strong_continue_ia.json',
            'system': Path(system.__file__), 'planner': Path(preopen.__file__), 'script': Path(__file__)}


def prepare():
    p = paths()
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    ia = json.loads(p['IA'].read_text())
    if ia['dataset_digest'] != ds.digest() or ia['source_sha256']['system'] != sha(p['system']):
        raise ValueError('IA input differs')
    reference = hd.compact_reference({k: v for k, v in ia['results']['base:lever_hold:hit'].items()
                                      if k != 'duration_stats'})
    del ia
    gc.collect()
    source = json.loads(p['HJ'].read_text())
    orders = source['orders']['H4']
    del source
    gc.collect()
    out = {'dataset_digest': ds.digest(), 'source_sha256': {k: sha(v) for k, v in p.items()},
           'orders': orders, 'reference': reference}
    target = du.REPORTS / 'strong_continue_id_inputs.json'
    with target.open('w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(',', ':'), allow_nan=False, default=json_default)
        fh.write('\n')
    print('prepared', target, flush=True)


def run():
    ip = du.REPORTS / 'strong_continue_id_inputs.json'
    data = json.loads(ip.read_text())
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    p = paths()
    if data['dataset_digest'] != ds.digest() or any(data['source_sha256'][k] != sha(v) for k, v in p.items()):
        raise ValueError('prepared sources differ')
    expected_orders, reference = data['orders'], data['reference']
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
    lever = f1_rules(d, 6, (1, 3))
    lever = replace(lever, intraday_kinds=tuple(lever.intraday_kinds) + ('n1', 'list'),
                    trail_next_open=True, add_next_open=True, no_rebuy_day=True, feedback_prior_close=True)
    rules = hv.without_partial(lever)
    source, _, _ = hc.make_books(d, original_orders, hh.observations(d, original_orders), True)
    original = hn.account(d, source, rules, FIXED, True)
    if hd.compact_reference(original) != reference:
        raise AssertionError('IA original account differs')
    print('reference ok', flush=True)
    keep = ('metrics', 'fidelity', 'winner_loss_stats', 'trades_digest')
    base = {k: original[k] for k in keep}
    del source, original
    gc.collect()
    core = [x for x in original_orders if x['kind'] == 'n1']
    widths = {}
    for order in original_orders:
        widths[order['day']] = widths.get(order['day'], 0) + (order['kind'] == 'list')
    draws = []
    progress = du.REPORTS / 'strong_continue_id_progress.jsonl'
    with progress.open('w', encoding='utf-8') as output:
        for seed in range(1, 31):
            orders = hb.freeze_orders(d.days, d.A['codes'], hk.randomize(book, seed), d.A['close'])
            if [x for x in orders if x['kind'] == 'n1'] != core:
                raise AssertionError('core orders differ')
            actual = {}
            for order in orders:
                actual[order['day']] = actual.get(order['day'], 0) + (order['kind'] == 'list')
            if actual != widths:
                raise AssertionError('daily list widths differ')
            source, _, _ = hc.make_books(d, orders, hh.observations(d, orders), True)
            result = hn.account(d, source, rules, FIXED, True)
            draw = {'seed': seed, 'orders_digest': hb.sha_bytes(orders), **{k: result[k] for k in keep}}
            draws.append(draw)
            output.write(json.dumps(draw, ensure_ascii=False, separators=(',', ':'), allow_nan=False,
                                    default=json_default) + '\n')
            output.flush()
            print('seed', seed, round(result['metrics']['total'], 3), flush=True)
            del orders, source, result
            gc.collect()
    out = {'dataset_digest': ds.digest(), 'inputs_sha256': sha(ip),
           'source_sha256': {k: sha(v) for k, v in p.items()}, 'base': base, 'draws': draws}
    target = du.REPORTS / 'strong_continue_id.json'
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
