"""GP: test prior-month leader priority in frozen cash and leveraged accounts."""
from dataclasses import replace
import gc
import json
from pathlib import Path
import sys

import numpy as np
from studies import trader_data
from studies.trader_replication import panels, system
from studies.trader_replication import martin_continue_ah as ah
from studies.trader_replication import martin_continue_dg as dg
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ep as ep
from studies.trader_replication import martin_continue_er as er
from studies.trader_replication import martin_continue_fc as fc
from studies.trader_replication import martin_continue_fe as fe
from studies.trader_replication import martin_continue_fg as fg
from studies.trader_replication import martin_continue_fn as fn
from studies.trader_replication import martin_continue_fo as fo
from studies.trader_replication import martin_continue_ft as ft
from studies.trader_replication import martin_continue_fx as fx
from studies.trader_replication import martin_continue_gi as gi
from studies.trader_replication import martin_continue_go as go
from studies.trader_replication.martin_continue_b_check import digest
from studies.trader_replication.martin_continue_bv import daily_name_score
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import HOLD, f1_rules, hold_sim, longs, nl_rules, u1_entries


def leader_book(candidate_rows, days, codes, features):
    book, seen = [[] for _ in days], set()
    counts = {'signal_days': 0, 'candidates': 0, 'selected': 0, 'leader_selected': 0, 'unknown_selected': 0}
    for day, candidates, n in candidate_rows:
        def priority(e):
            key = (days[day], str(codes[e[1]]))
            if key not in features:
                raise ValueError('GO candidate missing ' + repr(key))
            group = features[key]
            return (0 if group is True else 1 if group is False else 2, e[0], key[1])
        keys = {(days[day], str(codes[e[1]])) for e in candidates}
        if len(keys) != len(candidates) or seen.intersection(keys):
            raise ValueError('duplicate candidate identity')
        seen.update(keys)
        selected = sorted(candidates, key=priority)[:n]
        book[day] = [((1.0, 0, rank),) + tuple(e[1:6]) for rank, e in enumerate(selected)]
        counts['signal_days'] += 1
        counts['candidates'] += len(candidates)
        counts['selected'] += len(selected)
        counts['leader_selected'] += sum(features[(days[day], str(codes[e[1]]))] is True for e in selected)
        counts['unknown_selected'] += sum(features[(days[day], str(codes[e[1]]))] is None for e in selected)
    if seen != set(features):
        raise ValueError('GO / filtered candidate identities differ')
    return book, counts


def precision_orders(signals, d):
    unknown = []
    for day in range(1, len(signals)):
        if not panels.WINDOW[0] <= d.days[day] <= panels.WINDOW[1]:
            continue
        for e in signals[day - 1]:
            op, low, stop = float(d.A['open'][day, e[1]]), float(d.A['low'][day, e[1]]), float(e[4])
            reason = None
            if np.isfinite(op) and np.float32(op) == np.float32(stop):
                reason = 'open_stop'
            elif np.isfinite(op) and op > stop and np.isfinite(low) and np.float32(low) == np.float32(stop):
                reason = 'low_stop'
            if reason:
                unknown.append({'day': d.days[day], 'code': str(d.A['codes'][e[1]]), 'reason': reason,
                                'open': op, 'low': low if np.isfinite(low) else None, 'stop': stop})
    return unknown


def main():
    root = du.REPORTS
    gp, ip = root / 'strong_continue_go.json', root / 'strong_continue_gi.json'
    factor, ref = json.loads(gp.read_text()), json.loads(ip.read_text())
    if (factor['script_sha256'] != sha(Path(go.__file__)) or ref['script_sha256'] != sha(Path(gi.__file__)) or
            ref['system_sha256'] != sha(Path(system.__file__)) or factor['dataset_digest'] != ref['dataset_digest']):
        raise ValueError('GO / GI source differs')
    features = {(r['signal_day'], r['code']): r['leader'] for r in factor['rows']}
    if len(features) != len(factor['rows']) or not all(c['passed'] for c in factor['cuts'].values()):
        raise ValueError('GO feature or truncation mismatch')
    reference = {'dataset_digest': ref['dataset_digest'], 'old_core_counts': ref['old_core_counts'],
                 'old_list_counts': ref['old_list_counts'], 'old_core_precision_unknown': ref['old_core_precision_unknown'],
                 'results': {n: ref['results'][n] for n in ('C0', 'L0')}}
    del factor, ref
    gc.collect()
    dataset = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if dataset.digest() != reference['dataset_digest']:
        raise ValueError('dataset differs')
    stage_path = root / 'strong_continue_gp_selection.json'
    if sys.argv[1:] == ['select']:
        d = du.make_data(dataset)
        reg = [[((1.0,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:6])
                for e in row] for row in longs(d.reg)]
        for name in ('fp', 'fwd', 'raw', 'o', 'h', 'l', 'c', 't', 'adr', 'to20', 'U', 'rk'):
            if hasattr(d, name):
                delattr(d, name)
        gc.collect()
        trace = {}
        cfg = {k: v for k, v in d.cfg.items() if k != 'short'}
        long_entries, _, long_mask, long_pool = d.base.build(d.A, cfg, trace)
        if np.count_nonzero(d.pool != long_pool):
            raise AssertionError('candidate pool differs')
        candidate_rows = fg.candidate_rows(reg, trace['filtered'], trace['capped'], d.days)
        signals, selection = leader_book(candidate_rows, d.days, d.A['codes'], features)
        uncertain = precision_orders(signals, d)
        records = [{'day': d.days[i], 'code': str(d.A['codes'][e[1]]), 'rank': rank,
                    'side': e[2], 'fill': e[3], 'stop': e[4], 'kind': e[5]}
                   for i, row in enumerate(signals) for rank, e in enumerate(row)]
        out = {'dataset_digest': reference['dataset_digest'], 'go_sha256': sha(gp),
               'script_sha256': sha(Path(__file__)), 'selection': selection,
               'precision_orders': uncertain, 'signals': records}
        stage_path.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False,
                                          default=json_default) + '\n')
        print('wrote selection', stage_path, flush=True)
        return
    if sys.argv[1:] != ['accounts']:
        raise ValueError('choose select or accounts')
    stage = json.loads(stage_path.read_text())
    if (stage['dataset_digest'] != reference['dataset_digest'] or stage['go_sha256'] != sha(gp) or
            stage['script_sha256'] != sha(Path(__file__))):
        raise ValueError('selection source differs')
    del features
    gc.collect()
    d = du.make_data(dataset)
    code_index = {str(c): i for i, c in enumerate(d.A['codes'])}
    signals = [[] for _ in d.days]
    for record in stage['signals']:
        day, code, rank = record['day'], record['code'], record['rank']
        row = signals[d.di[day]]
        if rank != len(row):
            raise AssertionError('selection priority differs')
        row.append(((1.0, 0, rank), code_index[code], record['side'], record['fill'],
                    record['stop'], record['kind']))
    selection, uncertain = stage['selection'], stage['precision_orders']
    if uncertain != precision_orders(signals, d):
        raise AssertionError('precision audit differs')
    del stage
    selected_open, selected_counts = dg.next_open(signals, d.A['open'], d.A['low'], d.days)
    selected_open, accepted_unknown = fe.remove_precision_unknown(selected_open, d.days, d.A['codes'])
    accepted_unknown = [x for x in accepted_unknown if panels.WINDOW[0] <= x[0] <= panels.WINDOW[1]]
    del signals
    gc.collect()
    fields, mask, unused = du.compute_fields(d)
    del unused
    gc.collect()
    old = ep.original_eligibility(d)
    replay, old_pot = ep.peer_potential(d, old)
    for i, day in enumerate(d.days):
        if not np.array_equal(replay[i], fields['peer_pot'][i], equal_nan=True):
            raise AssertionError('original peer potential differs ' + day)
    del old, replay, old_pot
    gc.collect()
    events, eligible, _ = ep.causal_inputs(dataset, d, list(map(str, d.A['codes'])))
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
    score = daily_name_score(fields, mask, HOLD['H3'])
    holding = hold_sim(score, 12, 36)
    u1 = u1_entries(d, fields, holding, score)
    list_open, list_counts = ah.delayed_list(d, u1)
    if list_counts != reference['old_list_counts'] or er.ambiguous_orders(d, u1):
        raise AssertionError('original list differs')
    core_signals = [[e for e in row if e[2] > 0 and e[5] != 'list'] for row in u1]
    core_open, core_counts = dg.next_open(core_signals, d.A['open'], d.A['low'], d.days)
    core_open, old_unknown = fe.remove_precision_unknown(core_open, d.days, d.A['codes'])
    old_unknown = [x for x in old_unknown if panels.WINDOW[0] <= x[0] <= panels.WINDOW[1]]
    if core_counts != reference['old_core_counts'] or old_unknown != reference['old_core_precision_unknown']:
        raise AssertionError('original core differs')
    _, lever_original = fn.build_books(list_open, core_open)
    del fields, mask, score, holding, u1
    gc.collect()
    _, lever_candidate = fn.build_books(list_open, selected_open)
    del core_signals
    gc.collect()
    cash = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True, no_rebuy_day=True)
    cash = replace(cash, intraday_kinds=tuple(sorted(set(cash.intraday_kinds) | {'n1'})))
    lever = f1_rules(d, 6, (1, 3))
    lever = replace(lever, intraday_kinds=tuple(lever.intraday_kinds) + ('list', 'n1'),
                    trail_next_open=True, add_next_open=True, no_rebuy_day=True)
    cases = (('C0', core_open, cash), ('GP-C', selected_open, cash),
             ('L0', lever_original, lever), ('GP-L', lever_candidate, lever))
    results, traces, audits, cash_audits = {}, {}, {}, {}
    for name, book, rules in cases:
        print('account', name, flush=True)
        result = fo.account(d, book, rules)
        if name in reference['results'] and result != reference['results'][name]:
            raise AssertionError('baseline account differs: ' + name)
        px, ema = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules)
        _, _, trades = system.simulate(px, ema, rules, book, *panels.WINDOW, audit=True)
        if digest(trades) != result['trades_digest']:
            raise AssertionError('trade audit differs')
        gi.assert_no_same_day_rebuy(trades)
        results[name] = result
        audits[name] = fc.signal_audit(d, trades)
        traces[name] = ft.trace_orders(d, book, rules, result['trades_digest'])
        if name in ('C0', 'GP-C'):
            cash_audits[name] = fx.audit_open_cash(d, book, rules, result)
            if cash_audits[name]['negative_cash'] or any(v['max_positions_after_open'] > 6
                                                          for v in traces[name]['years'].values()):
                raise AssertionError('cash or position constraint breached')
    out = {'dataset_digest': reference['dataset_digest'], 'go_sha256': sha(gp), 'gi_sha256': sha(ip),
           'system_sha256': sha(Path(system.__file__)), 'script_sha256': sha(Path(__file__)),
           'selection_sha256': sha(stage_path), 'selection': selection, 'selected_counts': selected_counts, 'precision_orders': uncertain,
           'accepted_precision_unknown': accepted_unknown, 'results': results, 'traces': traces,
           'trail_audits': audits, 'cash_audits': cash_audits}
    target = root / 'strong_continue_gp.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False,
                                 default=json_default) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
