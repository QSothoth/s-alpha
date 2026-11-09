"""IA: H4 candidate funnel and registered 20-in/60-out watchlist."""
from collections import Counter
from dataclasses import replace
import gc
import json
from pathlib import Path
from statistics import mean, median
import sys

import numpy as np

from studies import trader_data
from studies.trader_replication import panels, preopen, system
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ep as ep
from studies.trader_replication import martin_continue_hb as hb
from studies.trader_replication import martin_continue_hc as hc
from studies.trader_replication import martin_continue_hd as hd
from studies.trader_replication import martin_continue_hf as hf
from studies.trader_replication import martin_continue_hg as hg
from studies.trader_replication import martin_continue_hh as hh
from studies.trader_replication import martin_continue_hj as hj
from studies.trader_replication import martin_continue_hn as hn
from studies.trader_replication import martin_continue_hv as hv
from studies.trader_replication import martin_continue_hx as hx
from studies.trader_replication.martin_continue_bv import daily_name_score, daily_pool_book
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import HOLD, f1_rules, hold_sim, merge, nl_rules, sized


def paths():
    return {'HX': du.REPORTS / 'strong_continue_hx.json', 'HX_inputs': du.REPORTS / 'strong_continue_hx_inputs.json',
            'HN': du.REPORTS / 'strong_continue_hn.json', 'HF': du.REPORTS / 'strong_continue_hf.json',
            'ledger': hf.LEDGER, 'system': Path(system.__file__), 'planner': Path(preopen.__file__),
            'ep_script': Path(ep.__file__), 'hj_script': Path(hj.__file__), 'hn_script': Path(hn.__file__),
            'hv_script': Path(hv.__file__), 'hx_script': Path(hx.__file__), 'hg_script': Path(hg.__file__),
            'script': Path(__file__)}


def prepare():
    p = paths()
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    x = json.loads(p['HX'].read_text())
    if (x['dataset_digest'] != ds.digest() or x['inputs_sha256'] != sha(p['HX_inputs']) or
            x['source_sha256']['script'] != sha(p['hx_script']) or x['source_sha256']['system'] != sha(p['system']) or
            x['source_sha256']['planner'] != sha(p['planner'])):
        raise ValueError('HX reference differs')
    refs = {f'cash11:{s}': hd.compact_reference({k: v for k, v in x['results'][f'hold:{s}'].items()
                                               if k != 'duration_stats'}) for s in ('hit', 'nohit')}
    del x
    gc.collect()
    inp = json.loads(p['HX_inputs'].read_text())
    original = inp['orders']
    for s in ('hit', 'nohit'):
        refs[f'cash6:{s}'] = inp['references'][f'cash6:hold:{s}']
    del inp
    gc.collect()
    n = json.loads(p['HN'].read_text())
    if (n['dataset_digest'] != ds.digest() or n['source_sha256']['script'] != sha(p['hn_script']) or
            n['source_sha256']['system'] != sha(p['system']) or n['source_sha256']['planner'] != sha(p['planner'])):
        raise ValueError('HN reference differs')
    for s in ('hit', 'nohit'):
        refs[f'lever_partial:{s}'] = hd.compact_reference(n['results'][f'low:lever:both:{s}'])
    del n
    gc.collect()
    f = json.loads(p['HF'].read_text())
    if f['dataset_digest'] != ds.digest() or f['ledger_sha256'] != sha(p['ledger']):
        raise ValueError('HF or ledger differs')
    targets = f['results']['lever:hit']['rows']
    del f
    out = {'dataset_digest': ds.digest(), 'source_sha256': {k: sha(v) for k, v in p.items()},
           'orders': original, 'references': refs, 'targets': targets}
    target = du.REPORTS / 'strong_continue_ia_inputs.json'
    with target.open('w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(',', ':'), allow_nan=False, default=json_default)
        fh.write('\n')
    print('prepared', target, flush=True)


def collect_funnel(d, mask, holding, book, targets):
    cols = {str(code): j for j, code in enumerate(d.A['codes'])}
    wanted = {}
    for target in targets:
        for day in d.days:
            if target['window'][0] <= day <= target['window'][1] and day in d.di:
                wanted.setdefault(day, []).append(target)
    per_id = {target['id']: [] for target in targets}
    widths = {}
    for day in range(1, len(d.days) - 1):
        next_day = d.days[day + 1]
        if not panels.WINDOW[0] <= next_day <= panels.WINDOW[1]:
            continue
        trial = [e for e in book[day] if e[2] > 0 and e[5] == 'list']
        qualified = {e[1] for e in trial}
        selected = {e[1] for e in sorted(trial, key=lambda e: e[0])[:6]}
        core = {e[1] for e in book[day] if e[2] > 0 and e[5] != 'list'}
        if any(e[5] != 'n1' for e in book[day] if e[2] > 0 and e[5] != 'list'):
            raise AssertionError('unexpected core kind')
        if np.any(holding[day] & ~mask[day]):
            raise AssertionError('held name outside active')
        widths.setdefault(next_day[:4], []).append([int(mask[day].sum()), int(holding[day].sum()),
                                                   len(qualified), len(selected), len(core)])
        for target in wanted.get(next_day, []):
            j = cols[target['code']]
            item = hg.event(mask[day, j], holding[day, j], j in qualified, j in selected, j in core)
            item.update(day=str(next_day), signal_day=str(d.days[day]))
            per_id[target['id']].append(item)
    rows = []
    for target in targets:
        items = per_id[target['id']]
        reached = {k: any(e[k] for e in items) for k in ('active', 'held', 'qualified', 'selected', 'core')}
        rows.append({**target, 'upstream_days': items, 'reached': reached})
    summary = {}
    keys = ('active', 'held', 'qualified', 'selected')
    for label, sample in (('2024_2025', [r for r in rows if r['entry_date'] <= '2025-12-31']),
                          ('2026', [r for r in rows if r['entry_date'] > '2025-12-31'])):
        summary[label] = {'n': len(sample), **{k: sum(r['reached'][k] for r in sample)
                          for k in ('active', 'held', 'qualified', 'selected', 'core')},
                          'union': sum(r['reached']['selected'] or r['reached']['core'] for r in sample),
                          'first_gap': {name: sum(not r['reached'][name] and (i == 0 or r['reached'][keys[i - 1]])
                                                  for r in sample)
                                        for i, name in enumerate(keys)}}
    width_summary = {year: {key: {'mean': mean(row[i] for row in values),
                                      'median': median(row[i] for row in values)}
                            for i, key in enumerate(('active', 'held', 'qualified', 'selected', 'core'))}
                     for year, values in widths.items()}
    return {'summary': summary, 'daily_width': width_summary, 'rows': rows}


def run():
    ip = du.REPORTS / 'strong_continue_ia_inputs.json'
    source = json.loads(ip.read_text())
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    p = paths()
    if source['dataset_digest'] != ds.digest() or any(source['source_sha256'][k] != sha(v) for k, v in p.items()):
        raise ValueError('prepared inputs differ')
    expected, refs, targets = source['orders'], source['references'], source['targets']
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
    score = daily_name_score(fields, mask, HOLD['H4'])
    h12, h20 = hold_sim(score, 12, 36), hold_sim(score, 20, 60)
    if np.any(h12 & ~h20):
        raise AssertionError('wide holding does not contain original')
    books = {label: merge(d.reg, sized(daily_pool_book(d, fields, hold, score), .5))
             for label, hold in (('base', h12), ('wide', h20))}
    orders = {label: hb.freeze_orders(d.days, d.A['codes'], book, d.A['close'])
              for label, book in books.items()}
    if orders['base'] != expected:
        raise AssertionError('original H4 orders differ')
    if [o for o in orders['base'] if o['kind'] == 'n1'] != [o for o in orders['wide'] if o['kind'] == 'n1']:
        raise AssertionError('core orders differ')
    for base, wide in zip(books['base'], books['wide']):
        if not {e[1] for e in base if e[5] == 'list'} <= {e[1] for e in wide if e[5] == 'list'}:
            raise AssertionError('wide qualified list does not contain original')
    funnel = {'base': collect_funnel(d, mask, h12, books['base'], targets),
              'wide': collect_funnel(d, mask, h20, books['wide'], targets)}
    del fields, mask, score, h12, h20, books
    gc.collect()
    observations = {label: hh.observations(d, value) for label, value in orders.items()}
    cash = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True, no_rebuy_day=True)
    cash = replace(cash, intraday_kinds=tuple(sorted(set(cash.intraday_kinds) | {'n1', 'list'})))
    cash11 = replace(cash, max_open=11, max_position=1 / 11)
    lever = f1_rules(d, 6, (1, 3))
    lever = replace(lever, intraday_kinds=tuple(lever.intraday_kinds) + ('n1', 'list'),
                    trail_next_open=True, add_next_open=True, no_rebuy_day=True, feedback_prior_close=True)
    accounts = (('cash6', hv.without_partial(cash)), ('cash11', hv.without_partial(cash11)),
                ('lever_partial', lever), ('lever_hold', hv.without_partial(lever)))
    fixed, results = {'n1': .025, 'list': .025}, {}
    for hit, scenario in ((True, 'hit'), (False, 'nohit')):
        baseline, _, _ = hc.make_books(d, orders['base'], observations['base'], hit)
        candidate, _, _ = hc.make_books(d, orders['wide'], observations['wide'], hit)
        for name, rules in accounts:
            print(scenario, name, 'reference', flush=True)
            base = hn.account(d, baseline, rules, fixed, hit)
            if name != 'lever_hold' and hd.compact_reference(base) != refs[name + ':' + scenario]:
                raise AssertionError('reference differs: ' + name + ':' + scenario)
            if name == 'lever_hold':
                base['duration_stats'] = hv.duration_stats(base['trades'])
                results['base:' + name + ':' + scenario] = base
            print(scenario, name, 'wide list', flush=True)
            result = hn.account(d, candidate, rules, fixed, hit)
            result['duration_stats'] = hv.duration_stats(result['trades'])
            results['wide:' + name + ':' + scenario] = result
    out = {'dataset_digest': ds.digest(), 'inputs_sha256': sha(ip),
           'source_sha256': {k: sha(v) for k, v in p.items()}, 'funnel': funnel,
           'orders': orders['wide'], 'observations': observations['wide'], 'results': results}
    target = du.REPORTS / 'strong_continue_ia.json'
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
