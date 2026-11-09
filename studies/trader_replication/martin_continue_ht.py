"""HT: rank H4 candidates by prior 20-day mean turnover."""
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
from studies.trader_replication import martin_continue_ho as ho
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import f1_rules, nl_rules


def paths():
    return {'HN': du.REPORTS / 'strong_continue_hn.json', 'HO': du.REPORTS / 'strong_continue_ho.json',
            'HO_inputs': du.REPORTS / 'strong_continue_ho_inputs.json', 'system': Path(system.__file__),
            'planner': Path(preopen.__file__), 'hj_script': Path(hj.__file__),
            'hn_script': Path(hn.__file__), 'ho_script': Path(ho.__file__), 'script': Path(__file__)}


def turnover_books(book, targets, turnover, codes):
    """Use the prior day's registered mean turnover before truncation."""
    result = list(book)
    counts = {}
    for day in targets:
        row = book[day]
        trial = [e for e in row if e[2] > 0 and e[5] == 'list']
        names = np.asarray([e[1] for e in trial], dtype=int)
        if len(set(names)) != len(names):
            raise ValueError('duplicate candidate')
        values = turnover[day - 1, names]
        key = np.where(np.isfinite(values), -values, np.inf)
        ordered = names[np.lexsort((codes[names], key))]
        rank = {int(j): n for n, j in enumerate(ordered)}
        result[day] = [(e[0][:-1] + (float(rank[e[1]]),),) + e[1:]
                       if e[2] > 0 and e[5] == 'list' else e for e in row]
        counts[str(day)] = len(names)
    return result, counts


def prepare():
    p = paths()
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    n = json.loads(p['HN'].read_text())
    if (n['dataset_digest'] != ds.digest() or n['source_sha256']['system'] != sha(p['system']) or
            n['source_sha256']['planner'] != sha(p['planner']) or n['source_sha256']['script'] != sha(p['hn_script'])):
        raise ValueError('HN source differs')
    refs = {f'{a}:{s}': hd.compact_reference(n['results'][f'low:{a}:both:{s}'])
            for a in ('cash6', 'cash11', 'lever') for s in ('hit', 'nohit')}
    del n
    gc.collect()
    o = json.loads(p['HO'].read_text())
    if (o['dataset_digest'] != ds.digest() or o['inputs_sha256'] != sha(p['HO_inputs']) or
            o['source_sha256']['HN'] != sha(p['HN']) or o['source_sha256']['script'] != sha(p['ho_script']) or
            len(o['draws']) != 30):
        raise ValueError('HO random reference differs')
    del o
    info = json.loads(p['HO_inputs'].read_text())
    output = {'dataset_digest': ds.digest(), 'source_sha256': {k: sha(v) for k, v in p.items()},
              'original_orders': info['orders'], 'references': refs}
    target = du.REPORTS / 'strong_continue_ht_inputs.json'
    with target.open('w', encoding='utf-8') as fh:
        json.dump(output, fh, ensure_ascii=False, separators=(',', ':'), allow_nan=False, default=json_default)
        fh.write('\n')
    print('prepared', target, flush=True)


def run():
    ip = du.REPORTS / 'strong_continue_ht_inputs.json'
    source = json.loads(ip.read_text())
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    p = paths()
    if source['dataset_digest'] != ds.digest() or any(source['source_sha256'][k] != sha(v) for k, v in p.items()):
        raise ValueError('prepared inputs differ')
    expected_orders, refs = source['original_orders'], source['references']
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
    h4, book = hj.freeze(d, fields, mask, 'H4')
    if h4 != expected_orders:
        raise AssertionError('original H4 orders differ')
    targets = [day for day, row in enumerate(book[:-1])
               if day > 0 and any(e[5] == 'list' for e in row)
               and panels.WINDOW[0] <= d.days[day + 1] <= panels.WINDOW[1]]
    priority, counts = turnover_books(book, targets, d.A['to20'], np.asarray(d.A['codes']).astype(str))
    candidate = hb.freeze_orders(d.days, d.A['codes'], priority, d.A['close'])
    keycounts = lambda xs: Counter((x['day'], x['kind']) for x in xs)
    if (keycounts(candidate) != keycounts(h4) or
            [x for x in candidate if x['kind'] == 'n1'] != [x for x in h4 if x['kind'] == 'n1']):
        raise AssertionError('daily widths or core orders changed')
    del fields, mask, priority, book
    gc.collect()
    original_obs, candidate_obs = hh.observations(d, h4), hh.observations(d, candidate)
    cash = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True, no_rebuy_day=True)
    cash = replace(cash, intraday_kinds=tuple(sorted(set(cash.intraday_kinds) | {'n1', 'list'})))
    cash11 = replace(cash, max_open=11, max_position=1 / 11)
    lever = f1_rules(d, 6, (1, 3))
    lever = replace(lever, intraday_kinds=tuple(lever.intraday_kinds) + ('n1', 'list'),
                    trail_next_open=True, add_next_open=True, no_rebuy_day=True, feedback_prior_close=True)
    fixed, results = {'n1': .025, 'list': .025}, {}
    for hit, scenario in ((True, 'hit'), (False, 'nohit')):
        baseline, _, _ = hc.make_books(d, h4, original_obs, hit)
        book, _, _ = hc.make_books(d, candidate, candidate_obs, hit)
        for name, rules in (('cash6', cash), ('cash11', cash11), ('lever', lever)):
            print(scenario, name, 'original H4', flush=True)
            base = hn.account(d, baseline, rules, fixed, hit)
            if hd.compact_reference(base) != refs[name + ':' + scenario]:
                raise AssertionError('HN reference differs')
            print(scenario, name, 'turnover first', flush=True)
            results[name + ':' + scenario] = hn.account(d, book, rules, fixed, hit)
    out = {'dataset_digest': ds.digest(), 'inputs_sha256': sha(ip),
           'source_sha256': {k: sha(v) for k, v in p.items()}, 'candidate_counts': counts,
           'orders': candidate, 'observations': candidate_obs, 'results': results}
    target = du.REPORTS / 'strong_continue_ht.json'
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
