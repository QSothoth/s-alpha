"""HZ: rank H4 trial candidates by causal long-term fast-stock frequency."""
from collections import Counter
from dataclasses import replace
import gc
import json
from pathlib import Path
import sys

import numpy as np

from studies import trader_data
from studies.trader_replication import panels, preopen, system
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ep as ep
from studies.trader_replication import martin_continue_hb as hb
from studies.trader_replication import martin_continue_hc as hc
from studies.trader_replication import martin_continue_hd as hd
from studies.trader_replication import martin_continue_hh as hh
from studies.trader_replication import martin_continue_hj as hj
from studies.trader_replication import martin_continue_hn as hn
from studies.trader_replication import martin_continue_ht as ht
from studies.trader_replication import martin_continue_hv as hv
from studies.trader_replication import martin_continue_hx as hx
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import nl_rules


def paths():
    return {'HX': du.REPORTS / 'strong_continue_hx.json', 'HX_inputs': du.REPORTS / 'strong_continue_hx_inputs.json',
            'system': Path(system.__file__), 'planner': Path(preopen.__file__),
            'ep_script': Path(ep.__file__), 'hj_script': Path(hj.__file__), 'ht_script': Path(ht.__file__),
            'hn_script': Path(hn.__file__), 'hv_script': Path(hv.__file__),
            'hx_script': Path(hx.__file__), 'script': Path(__file__)}


def prepare():
    p = paths()
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    report = json.loads(p['HX'].read_text())
    if (report['dataset_digest'] != ds.digest() or report['inputs_sha256'] != sha(p['HX_inputs']) or
            report['source_sha256']['script'] != sha(p['hx_script']) or
            report['source_sha256']['system'] != sha(p['system']) or report['source_sha256']['planner'] != sha(p['planner'])):
        raise ValueError('HX reference differs')
    refs = {f'cash11:{s}': hd.compact_reference({k: v for k, v in report['results'][f'hold:{s}'].items()
                                               if k != 'duration_stats'}) for s in ('hit', 'nohit')}
    del report
    gc.collect()
    inp = json.loads(p['HX_inputs'].read_text())
    for s in ('hit', 'nohit'):
        refs[f'cash6:{s}'] = inp['references'][f'cash6:hold:{s}']
    out = {'dataset_digest': ds.digest(), 'source_sha256': {k: sha(v) for k, v in p.items()},
           'orders': inp['orders'], 'references': refs}
    target = du.REPORTS / 'strong_continue_hz_inputs.json'
    with target.open('w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(',', ':'), allow_nan=False, default=json_default)
        fh.write('\n')
    print('prepared', target, flush=True)


def run():
    ip = du.REPORTS / 'strong_continue_hz_inputs.json'
    inp = json.loads(ip.read_text())
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    p = paths()
    if inp['dataset_digest'] != ds.digest() or any(inp['source_sha256'][k] != sha(v) for k, v in p.items()):
        raise ValueError('prepared inputs differ')
    expected, refs = inp['orders'], inp['references']
    del inp
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
    original, book = hj.freeze(d, fields, mask, 'H4')
    if original != expected:
        raise AssertionError('original H4 orders differ')
    targets = [day for day, row in enumerate(book[:-1]) if day > 0 and any(e[5] == 'list' for e in row)
               and panels.WINDOW[0] <= d.days[day + 1] <= panels.WINDOW[1]]
    priority, counts = ht.turnover_books(book, targets, fields['fast250'], np.asarray(d.A['codes']).astype(str))
    candidate = hb.freeze_orders(d.days, d.A['codes'], priority, d.A['close'])
    widths = lambda xs: Counter((x['day'], x['kind']) for x in xs)
    if (widths(candidate) != widths(original) or
            [x for x in candidate if x['kind'] == 'n1'] != [x for x in original if x['kind'] == 'n1']):
        raise AssertionError('daily widths or core changed')
    del fields, mask, priority, book
    gc.collect()
    original_obs, candidate_obs = hh.observations(d, original), hh.observations(d, candidate)
    cash = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True, no_rebuy_day=True)
    cash = replace(cash, intraday_kinds=tuple(sorted(set(cash.intraday_kinds) | {'n1', 'list'})))
    cash11 = replace(cash, max_open=11, max_position=1 / 11)
    accounts = (('cash6', hv.without_partial(cash)), ('cash11', hv.without_partial(cash11)))
    fixed, results = {'n1': .025, 'list': .025}, {}
    for hit, scenario in ((True, 'hit'), (False, 'nohit')):
        baseline, _, _ = hc.make_books(d, original, original_obs, hit)
        source, _, _ = hc.make_books(d, candidate, candidate_obs, hit)
        for name, rules in accounts:
            print(scenario, name, 'reference', flush=True)
            ref = hn.account(d, baseline, rules, fixed, hit)
            if hd.compact_reference(ref) != refs[name + ':' + scenario]:
                raise AssertionError('reference differs: ' + name + ':' + scenario)
            print(scenario, name, 'prior fast-stock frequency', flush=True)
            result = hn.account(d, source, rules, fixed, hit)
            result['duration_stats'] = hv.duration_stats(result['trades'])
            results[name + ':' + scenario] = result
    out = {'dataset_digest': ds.digest(), 'inputs_sha256': sha(ip),
           'source_sha256': {k: sha(v) for k, v in p.items()}, 'candidate_counts': counts,
           'orders': candidate, 'observations': candidate_obs, 'results': results}
    target = du.REPORTS / 'strong_continue_hz.json'
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
