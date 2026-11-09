"""IC: append one prior-selected peer after all original H4 candidates."""
from collections import Counter, defaultdict
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
from studies.trader_replication import martin_continue_hv as hv
from studies.trader_replication import martin_continue_ib as ib
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import f1_rules, nl_rules


def paths():
    return {'IB': du.REPORTS / 'strong_continue_ib.json', 'IB_inputs': du.REPORTS / 'strong_continue_ib_inputs.json',
            'system': Path(system.__file__), 'planner': Path(preopen.__file__),
            'ib_script': Path(ib.__file__), 'hn_script': Path(hn.__file__), 'hv_script': Path(hv.__file__),
            'script': Path(__file__)}


def append_one_peer(original, peer):
    """Keep every original order; append first preselected peer unless duplicate."""
    by_day, peer_by_day = defaultdict(list), defaultdict(list)
    for order in original:
        by_day[order['day']].append(order)
    for order in peer:
        if order['kind'] == 'list':
            peer_by_day[order['day']].append(order)
    result, selected, skipped = [], set(), Counter()
    for day in sorted(set(by_day) | set(peer_by_day)):
        core = by_day[day]
        if any(hc.tuple_priority(o['priority']) >= (2., 2., 0.) for o in core):
            raise AssertionError('supplement priority is not last')
        result.extend(core)
        ranked = sorted(peer_by_day[day], key=lambda o: hc.tuple_priority(o['priority']))
        if not ranked:
            continue
        first = ranked[0]
        if any(o['code'] == first['code'] for o in core):
            skipped[day[:4]] += 1
            continue
        result.append({**first, 'priority': [2., 2., 0.]})
        selected.add((day, first['code']))
    return result, selected, dict(skipped)


def audit_plans(plans, peer_keys, cash_limit=None):
    by_year = defaultdict(Counter)
    for day in plans:
        peer_seen = False
        new_count = 0
        list_count = 0
        for order in day['orders']:
            if order['type'] != 'entry':
                continue
            is_peer = (day['day'], order['code']) in peer_keys and order['kind'] == 'list'
            if is_peer:
                peer_seen = True
                by_year[day['day'][:4]]['attempts'] += 1
                by_year[day['day'][:4]]['reservation:' + order['status']] += 1
                if order['status'] == 'submitted':
                    by_year[day['day'][:4]]['execution:' + order.get('execution', 'unknown')] += 1
                else:
                    by_year[day['day'][:4]]['reason:' + order.get('reason', 'unknown')] += 1
            elif peer_seen:
                raise AssertionError('original entry processed after peer')
            if order['status'] == 'submitted':
                new_count += 1
                list_count += order['kind'] == 'list'
        if cash_limit is not None and new_count > cash_limit:
            raise AssertionError('cash new-entry limit exceeded')
        if cash_limit is None and list_count > 6:
            raise AssertionError('lever trial limit exceeded')
    return {year: dict(counts) for year, counts in by_year.items()}


def peer_trade_stats(result, peer_keys):
    summary = {}
    for year in ('2024', '2025', '2026'):
        trades = [t for t in result['trades'] if t['entry'].startswith(year) and t['kind'] == 'list'
                  and (t['entry'], t['code']) in peer_keys]
        closed = [t for t in trades if t['why'] != 'end']
        summary[year] = {'entries': len(trades), 'closed': len(closed),
                         'return_30': sum(t['ret_invested'] >= .3 for t in closed),
                         'return_50': sum(t['ret_invested'] >= .5 for t in closed),
                         'r10': sum(t['r'] >= 10 for t in closed)}
    return summary


def window_summary(rows, original, combined, peer_keys):
    orig = {(o['day'], o['code'], o['kind']) for o in original}
    new = {(o['day'], o['code'], o['kind']) for o in combined}
    result = []
    for row in rows:
        code = row['code']
        days = [e['day'] for e in row['events']]
        old = any((day, code, kind) in orig for day in days for kind in ('n1', 'list'))
        current = any((day, code, kind) in new for day in days for kind in ('n1', 'list'))
        supplement = any((day, code) in peer_keys for day in days)
        result.append({'id': row['id'], 'code': code, 'entry_date': row['entry_date'], 'window': row['window'],
                       'original': old, 'candidate': current, 'peer': supplement})
    summary = {}
    for label, sample in (('2024_2025', [x for x in result if x['entry_date'] <= '2025-12-31']),
                          ('2026', [x for x in result if x['entry_date'] > '2025-12-31'])):
        summary[label] = {'n': len(sample), 'original': sum(x['original'] for x in sample),
                          'candidate': sum(x['candidate'] for x in sample), 'peer': sum(x['peer'] for x in sample),
                          'gained': sum(not x['original'] and x['candidate'] for x in sample)}
        if any(x['original'] and not x['candidate'] for x in sample):
            raise AssertionError('original candidate was removed')
    return {'summary': summary, 'rows': result}


def prepare():
    p = paths()
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    prev = json.loads(p['IB'].read_text())
    if (prev['dataset_digest'] != ds.digest() or prev['inputs_sha256'] != sha(p['IB_inputs']) or
            prev['source_sha256']['script'] != sha(p['ib_script']) or
            prev['source_sha256']['system'] != sha(p['system']) or prev['source_sha256']['planner'] != sha(p['planner'])):
        raise ValueError('IB reference differs')
    refs = {f'interleave:{a}:{s}': hd.compact_reference({k: v for k, v in prev['results'][f'{a}:{s}'].items()
                                if k not in ('duration_stats', 'peer_trade_stats')})
            for a in ('cash6', 'cash11', 'lever') for s in ('hit', 'nohit')}
    peer, interleave, interleave_obs, rows = (prev[k] for k in ('peer_orders', 'combined_orders', 'observations', 'funnel'))
    rows = rows['rows']
    del prev
    gc.collect()
    inp = json.loads(p['IB_inputs'].read_text())
    for account in ('cash6', 'cash11', 'lever'):
        for s in ('hit', 'nohit'):
            refs[f'original:{account}:{s}'] = inp['references'][f'{account}:{s}']
    out = {'dataset_digest': ds.digest(), 'source_sha256': {k: sha(v) for k, v in p.items()},
           'original': inp['orders'], 'peer': peer, 'interleave': interleave,
           'interleave_obs': interleave_obs, 'references': refs, 'rows': rows}
    target = du.REPORTS / 'strong_continue_ic_inputs.json'
    with target.open('w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(',', ':'), allow_nan=False, default=json_default)
        fh.write('\n')
    print('prepared', target, flush=True)


def run():
    ip = du.REPORTS / 'strong_continue_ic_inputs.json'
    data = json.loads(ip.read_text())
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    p = paths()
    if data['dataset_digest'] != ds.digest() or any(data['source_sha256'][k] != sha(v) for k, v in p.items()):
        raise ValueError('prepared inputs differ')
    original, peer, interleave, interleave_obs, refs, rows = (data[k] for k in
        ('original', 'peer', 'interleave', 'interleave_obs', 'references', 'rows'))
    del data
    gc.collect()
    candidate, peer_keys, skipped = append_one_peer(original, peer)
    if [o for o in candidate if (o['day'], o['code']) not in peer_keys] != original:
        raise AssertionError('original orders changed')
    coverage = window_summary(rows, original, candidate, peer_keys)
    d = du.make_data(ds)
    del d.fp, d.fwd, d.raw
    gc.collect()
    original_obs, candidate_obs = hh.observations(d, original), hh.observations(d, candidate)
    cash = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True, no_rebuy_day=True)
    cash = replace(cash, intraday_kinds=tuple(sorted(set(cash.intraday_kinds) | {'n1', 'list'})))
    cash11 = replace(cash, max_open=11, max_position=1 / 11)
    lever = f1_rules(d, 6, (1, 3))
    lever = replace(lever, intraday_kinds=tuple(lever.intraday_kinds) + ('n1', 'list'),
                    trail_next_open=True, add_next_open=True, no_rebuy_day=True, feedback_prior_close=True)
    accounts = (('cash6', hv.without_partial(cash), 6), ('cash11', hv.without_partial(cash11), 11),
                ('lever', hv.without_partial(lever), None))
    fixed, results = {'n1': .025, 'list': .025}, {}
    for hit, scenario in ((True, 'hit'), (False, 'nohit')):
        original_book, _, _ = hc.make_books(d, original, original_obs, hit)
        old_book, _, _ = hc.make_books(d, interleave, interleave_obs, hit)
        candidate_book, _, _ = hc.make_books(d, candidate, candidate_obs, hit)
        for name, rules, cap in accounts:
            for label, book in (('original', original_book), ('interleave', old_book)):
                print(scenario, name, label, 'reference', flush=True)
                reference = hn.account(d, book, rules, fixed, hit)
                if hd.compact_reference(reference) != refs[f'{label}:{name}:{scenario}']:
                    raise AssertionError('reference differs')
            print(scenario, name, 'one peer', flush=True)
            result = hn.account(d, candidate_book, rules, fixed, hit)
            result['peer_plan_audit'] = audit_plans(result['plans'], peer_keys, cap)
            result['peer_trade_stats'] = peer_trade_stats(result, peer_keys)
            result['duration_stats'] = hv.duration_stats(result['trades'])
            results[name + ':' + scenario] = result
    out = {'dataset_digest': ds.digest(), 'inputs_sha256': sha(ip),
           'source_sha256': {k: sha(v) for k, v in p.items()}, 'orders': candidate,
           'observations': candidate_obs, 'peer_order_count': len(peer_keys), 'duplicate_skipped': skipped,
           'coverage': coverage, 'results': results}
    target = du.REPORTS / 'strong_continue_ic.json'
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
