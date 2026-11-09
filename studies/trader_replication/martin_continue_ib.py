"""IB: supplement H4 with causal correlated peers and original P ranking."""
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
from studies.trader_replication import martin_continue_cn as cn
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ep as ep
from studies.trader_replication import martin_continue_hb as hb
from studies.trader_replication import martin_continue_hc as hc
from studies.trader_replication import martin_continue_hd as hd
from studies.trader_replication import martin_continue_hh as hh
from studies.trader_replication import martin_continue_hj as hj
from studies.trader_replication import martin_continue_hm as hm
from studies.trader_replication import martin_continue_hn as hn
from studies.trader_replication import martin_continue_hv as hv
from studies.trader_replication import martin_continue_ia as ia
from studies.trader_replication import martin_continue_n as n
from studies.trader_replication import martin_continue_p as p_rank
from studies.trader_replication.martin_continue_bv import daily_name_score, daily_pool_book
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import HOLD, f1_rules, hold_sim, merge, nl_rules, sized


def paths():
    return {'IA': du.REPORTS / 'strong_continue_ia.json', 'IA_inputs': du.REPORTS / 'strong_continue_ia_inputs.json',
            'system': Path(system.__file__), 'planner': Path(preopen.__file__), 'ia_script': Path(ia.__file__),
            'cn_script': Path(cn.__file__), 'ep_script': Path(ep.__file__), 'hj_script': Path(hj.__file__),
            'hm_script': Path(hm.__file__), 'hn_script': Path(hn.__file__), 'hv_script': Path(hv.__file__),
            'n_script': Path(n.__file__), 'p_script': Path(p_rank.__file__), 'script': Path(__file__)}


def peer_matrix(residuals, active, held, day):
    """Only prior 40 sessions and a candidate-by-held matrix, preserving N1 semantics."""
    pool, leaders = np.flatnonzero(active & ~held), np.flatnonzero(held)
    if day < 40 or not len(pool) or not len(leaders):
        return pool, leaders, np.zeros((len(pool), len(leaders)), dtype=bool)
    a, b = residuals[day - 40:day, pool], residuals[day - 40:day, leaders]
    a, b = a - a.mean(axis=0), b - b.mean(axis=0)
    near = (a.T @ b) / len(a) / np.outer(a.std(axis=0) + 1e-6, b.std(axis=0) + 1e-6) >= .5
    flags, _ = n.peer_flags(residuals[day - 40:day, pool], residuals[day - 40:day, leaders],
                            np.zeros(len(leaders), dtype=bool))
    if not np.array_equal(near.any(axis=1), flags):
        raise AssertionError('N1 boolean differs')
    return pool, leaders, near


def peer_priority(book, meta, gain, high, low, adr, turnover, codes):
    """Prior P ordering only within signal-qualified peers; preserve the core."""
    out = list(book)
    for day, (pool, leaders, near) in meta.items():
        row = book[day]
        trial = [e for e in row if e[2] > 0 and e[5] == 'list']
        if not trial:
            continue
        names = np.asarray([e[1] for e in trial], dtype=int)
        if len(set(names)) != len(names):
            raise ValueError('duplicate peer')
        position = {int(j): i for i, j in enumerate(pool)}
        correlated = near[[position[int(j)] for j in names]]
        if not np.all(correlated.any(axis=1)):
            raise AssertionError('unrelated name in peer book')
        with np.errstate(all='ignore'):
            tight = (np.max(high[day - 3:day, names], axis=0) /
                     np.min(low[day - 3:day, names], axis=0) - 1) / adr[day - 1, names]
        order = p_rank.rank_peers(correlated, gain[day - 1, names], gain[day - 1, leaders],
                                  tight, turnover[day - 1, names], codes[names])
        rank = {int(names[pos]): i for i, pos in enumerate(order)}
        out[day] = [(e[0][:-1] + (float(rank[e[1]]),),) + e[1:]
                    if e[2] > 0 and e[5] == 'list' else e for e in row]
    return out


def peer_funnel(d, peer_mask, peer_book, original, combined, old_rows):
    cols = {str(code): j for j, code in enumerate(d.A['codes'])}
    day_index = {str(day): i for i, day in enumerate(d.days)}
    peer_qualified = {str(d.days[day + 1]): {int(e[1]) for e in row if e[2] > 0 and e[5] == 'list'}
                      for day, row in enumerate(peer_book[:-1])}
    original_keys = {(r['day'], r['code'], r['kind']) for r in original}
    combined_keys = {(r['day'], r['code'], r['kind']) for r in combined}
    rows = []
    for old in old_rows:
        j = cols[old['code']]
        events = []
        for previous in old['upstream_days']:
            day, signal = previous['day'], previous['signal_day']
            raw = bool(peer_mask[day_index[signal], j])
            qual = j in peer_qualified.get(day, set())
            chosen = qual and (day, old['code'], 'list') in combined_keys
            orig = (day, old['code'], 'list') in original_keys
            core = (day, old['code'], 'n1') in combined_keys
            any_list = (day, old['code'], 'list') in combined_keys
            if not (chosen <= qual <= raw):
                raise AssertionError('peer stages do not accumulate')
            events.append({'day': day, 'signal_day': signal, 'peer': raw, 'qualified': qual,
                           'peer_selected': chosen, 'old_list': orig, 'combined_list': any_list, 'core': core})
        reached = {k: any(e[k] for e in events) for k in ('peer', 'qualified', 'peer_selected',
                                                          'old_list', 'combined_list', 'core')}
        if reached['old_list'] != old['reached']['selected'] or reached['core'] != old['reached']['core']:
            raise AssertionError('IA original window differs')
        rows.append({'id': old['id'], 'code': old['code'], 'entry_date': old['entry_date'],
                     'precision': old['precision'], 'window': old['window'], 'events': events, 'reached': reached})
    summary = {}
    for label, sample in (('2024_2025', [r for r in rows if r['entry_date'] <= '2025-12-31']),
                          ('2026', [r for r in rows if r['entry_date'] > '2025-12-31'])):
        old_union = lambda r: r['reached']['old_list'] or r['reached']['core']
        new_union = lambda r: r['reached']['combined_list'] or r['reached']['core']
        summary[label] = {'n': len(sample), **{k: sum(r['reached'][k] for r in sample)
                          for k in ('peer', 'qualified', 'peer_selected', 'old_list', 'combined_list', 'core')},
                          'old_union': sum(old_union(r) for r in sample), 'new_union': sum(new_union(r) for r in sample),
                          'gained': sum(not old_union(r) and new_union(r) for r in sample),
                          'lost': sum(old_union(r) and not new_union(r) for r in sample)}
    return {'summary': summary, 'rows': rows}


def peer_trade_stats(result, selected_keys):
    out = {}
    for year in ('2024', '2025', '2026'):
        trades = [t for t in result['trades'] if t['entry'].startswith(year) and t['kind'] == 'list'
                  and (t['entry'], t['code']) in selected_keys]
        closed = [t for t in trades if t['why'] != 'end']
        out[year] = {'entries': len(trades), 'closed': len(closed),
                     'return_30': sum(t['ret_invested'] >= .3 for t in closed),
                     'return_50': sum(t['ret_invested'] >= .5 for t in closed),
                     'r10': sum(t['r'] >= 10 for t in closed)}
    return out


def prepare():
    p = paths()
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    report = json.loads(p['IA'].read_text())
    if (report['dataset_digest'] != ds.digest() or report['inputs_sha256'] != sha(p['IA_inputs']) or
            report['source_sha256']['script'] != sha(p['ia_script']) or
            report['source_sha256']['system'] != sha(p['system']) or report['source_sha256']['planner'] != sha(p['planner'])):
        raise ValueError('IA reference differs')
    refs = {f'lever:{s}': hd.compact_reference({k: v for k, v in report['results'][f'base:lever_hold:{s}'].items()
                                                if k != 'duration_stats'}) for s in ('hit', 'nohit')}
    rows = report['funnel']['base']['rows']
    del report
    gc.collect()
    inp = json.loads(p['IA_inputs'].read_text())
    for account in ('cash6', 'cash11'):
        for s in ('hit', 'nohit'):
            refs[f'{account}:{s}'] = inp['references'][f'{account}:{s}']
    out = {'dataset_digest': ds.digest(), 'source_sha256': {k: sha(v) for k, v in p.items()},
           'orders': inp['orders'], 'references': refs, 'rows': rows}
    target = du.REPORTS / 'strong_continue_ib_inputs.json'
    with target.open('w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(',', ':'), allow_nan=False, default=json_default)
        fh.write('\n')
    print('prepared', target, flush=True)


def run():
    ip = du.REPORTS / 'strong_continue_ib_inputs.json'
    source = json.loads(ip.read_text())
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    p = paths()
    if source['dataset_digest'] != ds.digest() or any(source['source_sha256'][k] != sha(v) for k, v in p.items()):
        raise ValueError('prepared inputs differ')
    expected, refs, rows = source['orders'], source['references'], source['rows']
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
    holding = hold_sim(score, 12, 36)
    original_book = merge(d.reg, sized(daily_pool_book(d, fields, holding, score), .5))
    original = hb.freeze_orders(d.days, d.A['codes'], original_book, d.A['close'])
    if original != expected:
        raise AssertionError('original H4 differs')
    for key in list(fields):
        if key not in ('lowe9', 'cpos', 'ext21', 'g21'):
            del fields[key]
    gc.collect()
    residuals = cn.residuals(d)
    peer_mask = np.zeros(mask.shape, dtype=bool)
    meta = {}
    for day in range(40, len(d.days) - 1):
        if not panels.WINDOW[0] <= d.days[day + 1] <= panels.WINDOW[1]:
            continue
        pool, leaders, near = peer_matrix(residuals, mask[day], holding[day], day)
        peer_mask[day, pool[near.any(axis=1)]] = True
        meta[day] = (pool, leaders, near)
    del residuals
    gc.collect()
    peer_book = merge(d.reg, sized(daily_pool_book(d, fields, peer_mask, score), .5))
    ranked_peer = peer_priority(peer_book, meta, fields['g21'], d.h, d.l, d.adr, d.to20,
                                np.asarray(d.A['codes']).astype(str))
    peer_orders = hb.freeze_orders(d.days, d.A['codes'], ranked_peer, d.A['close'])
    combined = hm.blend(peer_orders, original)
    if [o for o in combined if o['kind'] == 'n1'] != [o for o in original if o['kind'] == 'n1']:
        raise AssertionError('core changed')
    widths = Counter(o['day'] for o in combined if o['kind'] == 'list')
    if any(v > 6 for v in widths.values()):
        raise AssertionError('daily trial limit exceeded')
    peer_keys = {(o['day'], o['code']) for o in peer_orders if o['kind'] == 'list'}
    combined_keys = {(o['day'], o['code']) for o in combined if o['kind'] == 'list'}
    chosen_peer = peer_keys & combined_keys
    funnel = peer_funnel(d, peer_mask, ranked_peer, original, combined, rows)
    width_rows = {}
    for day in range(40, len(d.days) - 1):
        target = str(d.days[day + 1])
        if not panels.WINDOW[0] <= target <= panels.WINDOW[1]:
            continue
        raw = int(peer_mask[day].sum())
        qual = sum(e[2] > 0 and e[5] == 'list' for e in ranked_peer[day])
        selected = sum(k[0] == target for k in chosen_peer)
        width_rows.setdefault(target[:4], []).append((raw, qual, selected))
    width_summary = {y: {key: {'mean': mean(r[i] for r in values), 'median': median(r[i] for r in values)}
                         for i, key in enumerate(('peer', 'qualified', 'selected'))} for y, values in width_rows.items()}
    del fields, mask, score, holding, original_book, peer_book, ranked_peer, meta, peer_mask
    gc.collect()
    original_obs, combined_obs = hh.observations(d, original), hh.observations(d, combined)
    cash = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True, no_rebuy_day=True)
    cash = replace(cash, intraday_kinds=tuple(sorted(set(cash.intraday_kinds) | {'n1', 'list'})))
    cash11 = replace(cash, max_open=11, max_position=1 / 11)
    lever = f1_rules(d, 6, (1, 3))
    lever = replace(lever, intraday_kinds=tuple(lever.intraday_kinds) + ('n1', 'list'),
                    trail_next_open=True, add_next_open=True, no_rebuy_day=True, feedback_prior_close=True)
    accounts = (('cash6', hv.without_partial(cash)), ('cash11', hv.without_partial(cash11)),
                ('lever', hv.without_partial(lever)))
    fixed, results = {'n1': .025, 'list': .025}, {}
    for hit, scenario in ((True, 'hit'), (False, 'nohit')):
        baseline, _, _ = hc.make_books(d, original, original_obs, hit)
        candidate, _, _ = hc.make_books(d, combined, combined_obs, hit)
        for name, rules in accounts:
            print(scenario, name, 'reference', flush=True)
            ref = hn.account(d, baseline, rules, fixed, hit)
            if hd.compact_reference(ref) != refs[name + ':' + scenario]:
                raise AssertionError('reference differs: ' + name + ':' + scenario)
            print(scenario, name, 'peer supplement', flush=True)
            result = hn.account(d, candidate, rules, fixed, hit)
            result['duration_stats'] = hv.duration_stats(result['trades'])
            result['peer_trade_stats'] = peer_trade_stats(result, chosen_peer)
            results[name + ':' + scenario] = result
    out = {'dataset_digest': ds.digest(), 'inputs_sha256': sha(ip),
           'source_sha256': {k: sha(v) for k, v in p.items()}, 'funnel': funnel, 'daily_width': width_summary,
           'peer_orders': peer_orders, 'combined_orders': combined, 'observations': combined_obs, 'results': results}
    target = du.REPORTS / 'strong_continue_ib.json'
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
