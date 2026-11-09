"""GW: test a single concurrent H3 trial in cash and leveraged accounts."""
from dataclasses import replace
import gc
import json
import sys
from pathlib import Path

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
from studies.trader_replication import martin_continue_fn as fn
from studies.trader_replication import martin_continue_fo as fo
from studies.trader_replication import martin_continue_ft as ft
from studies.trader_replication import martin_continue_fx as fx
from studies.trader_replication import martin_continue_gi as gi
from studies.trader_replication import martin_continue_gu as gu
from studies.trader_replication import martin_continue_gv as gv
from studies.trader_replication.martin_continue_b_check import digest
from studies.trader_replication.martin_continue_bv import daily_name_score
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import HOLD, f1_rules, hold_sim, nl_rules, u1_entries



def sensitive_book(book, days, codes, keys, hit):
    out, changed = [], []
    for i, row in enumerate(book):
        day_out = []
        for entry in row:
            key = (days[i], str(codes[entry[1]]), entry[5])
            if key in keys:
                if len(entry) < 7:
                    raise ValueError('day-zero execution field missing')
                entry = tuple(entry[:6]) + (float(entry[4]) if hit else None,) + tuple(entry[7:])
                changed.append(key)
            day_out.append(entry)
        out.append(day_out)
    if len(changed) != len(set(changed)):
        raise ValueError('duplicate ambiguous order key')
    return out, changed


def trace_open_kinds(d, book, rules, expected_digest):
    records = []
    source = Path(system.__file__).resolve()

    def trace(frame, event, arg):
        if event == 'return' and arg:
            local = frame.f_locals
            positions = local['pos']
            records.append({'day': d.days[local['d']], 'code': str(d.A['codes'][local['j']]),
                            'kind': local['kind'], 'total': len(positions),
                            'list': sum(q.kind == 'list' for q in positions.values())})
        return trace

    def dispatch(frame, event, arg):
        if event == 'call' and frame.f_code.co_name == 'open_pos' and Path(frame.f_code.co_filename).resolve() == source:
            return trace
        return None

    px, ema = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules)
    try:
        sys.settrace(dispatch)
        _, _, trades = system.simulate(px, ema, rules, book, *panels.WINDOW, audit=True)
    finally:
        sys.settrace(None)
    if digest(trades) != expected_digest:
        raise AssertionError('position trace differs')
    if sorted((r['day'], r['code'], r['kind']) for r in records) != sorted(
            (t['entry'], t['code'], t['kind']) for t in trades):
        raise AssertionError('position trace openings differ')
    return {'max_list': max((r['list'] for r in records), default=0),
            'max_total': max((r['total'] for r in records), default=0), 'records': records}

def main():
    root = du.REPORTS
    ref_path = root / 'strong_continue_gi.json'
    ref = json.loads(ref_path.read_text())
    if ref['script_sha256'] != sha(Path(gi.__file__)) or ref['system_sha256'] != sha(Path(system.__file__)):
        raise ValueError('GI source or engine differs')
    dataset = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    data_digest = dataset.digest()
    if data_digest != ref['dataset_digest']:
        raise ValueError('dataset differs')
    gu_path = root / 'strong_continue_gu.json'
    base = json.loads(gu_path.read_text())
    if (base['script_sha256'] != sha(Path(gu.__file__)) or base['gi_sha256'] != sha(ref_path) or
            base['dataset_digest'] != data_digest or base['system_sha256'] != sha(Path(system.__file__))):
        raise ValueError('GU source or dataset differs')
    expected = base['results']
    expected_low, expected_open = base['low_precision_unknown'], base['old_open_precision_unknown']
    del base
    gv_path = root / 'strong_continue_gv.json'
    sensitivity = json.loads(gv_path.read_text())
    if (sensitivity['script_sha256'] != sha(Path(gv.__file__)) or sensitivity['gu_sha256'] != sha(gu_path) or
            sensitivity['dataset_digest'] != data_digest or sensitivity['system_sha256'] != sha(Path(system.__file__)) or
            sensitivity['low_precision_unknown'] != expected_low or sensitivity['old_open_precision_unknown'] != expected_open):
        raise ValueError('GV reference differs')
    expected_paths = {k: v for k, v in sensitivity['results'].items()
                      if k.split(':')[0] in ('C0', 'GU-M', 'L0')}
    del sensitivity
    core_counts, list_counts, old_unknown = ref['old_core_counts'], ref['old_list_counts'], ref['old_core_precision_unknown']
    precision_open = [r for r in ref['fixed_hit_orders'] if r.get('old_open_stop_precision_unknown')]
    del ref
    gc.collect()
    d = du.make_data(dataset)
    fields, mask, unused_holding = du.compute_fields(d)
    del unused_holding
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
    del score, holding
    list_open, got_list = ah.delayed_list(d, u1)
    if got_list != list_counts or er.ambiguous_orders(d, u1):
        raise AssertionError('original list candidates differ')
    core = [[e for e in row if e[2] > 0 and e[5] != 'list'] for row in u1]
    core_open, got_core = dg.next_open(core, d.A['open'], d.A['low'], d.days)
    core_open, unknown = fe.remove_precision_unknown(core_open, d.days, d.A['codes'])
    unknown = [x for x in unknown if panels.WINDOW[0] <= x[0] <= panels.WINDOW[1]]
    if got_core != core_counts or unknown != old_unknown:
        raise AssertionError('original core differs')
    _, old_book = fn.build_books(list_open, core_open)
    only_list = [[e for e in row if e[5] == 'list'] for row in list_open]
    low_unknown = []
    for i, day in enumerate(d.days):
        if not panels.WINDOW[0] <= day <= panels.WINDOW[1]:
            continue
        for e in old_book[i]:
            low = float(d.A['low'][i, e[1]])
            if np.isfinite(low) and np.float32(low) == np.float32(e[4]):
                low_unknown.append({'day': day, 'code': str(d.A['codes'][e[1]]), 'kind': e[5],
                                    'opening': float(e[3]), 'low': low, 'stop': float(e[4])})
    if low_unknown != expected_low or precision_open != expected_open or len(low_unknown) != 7:
        raise AssertionError('GU precision candidate list differs')
    keys = {(r['day'], r['code'], r['kind']) for r in low_unknown}
    if len(keys) != len(low_unknown):
        raise AssertionError('duplicate precision key')
    del fields, mask, u1, core, list_open
    gc.collect()
    cash = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True, no_rebuy_day=True)
    cash = replace(cash, intraday_kinds=tuple(sorted(set(cash.intraday_kinds) | {'list', 'n1'})))
    lever = f1_rules(d, 6, (1, 3))
    lever = replace(lever, intraday_kinds=tuple(lever.intraday_kinds) + ('list', 'n1'),
                    trail_next_open=True, add_next_open=True, no_rebuy_day=True)
    candidate_cash = replace(cash, max_open_by_kind={**cash.max_open_by_kind, 'list': 1})
    candidate_lever = replace(lever, max_open_by_kind={**lever.max_open_by_kind, 'list': 1})
    bases = [('C0', core_open, cash), ('GU-M', old_book, cash), ('GW-C', old_book, candidate_cash),
             ('L0', old_book, lever), ('GW-L', old_book, candidate_lever)]
    cases, changed_keys = [], {}
    for name, book, rules in bases:
        cases.append((name, name + ':original', book, rules))
        for hit in (True, False):
            changed, found = sensitive_book(book, d.days, d.A['codes'], keys, hit)
            case = name + (':hit' if hit else ':nohit')
            cases.append((name, case, changed, rules))
            changed_keys[case] = found
    results, audits, traces, cash_audits, kind_audits = {}, {}, {}, {}, {}
    for base_name, name, book, rules in cases:
        print('account', name, flush=True)
        result = fo.account(d, book, rules)
        results[name] = result
        if name in expected_paths and result != expected_paths[name]:
            raise AssertionError('GV account differs ' + name)
        px, ema = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules)
        _, _, trades = system.simulate(px, ema, rules, book, *panels.WINDOW, audit=True)
        if digest(trades) != result['trades_digest']:
            raise AssertionError('audit account differs')
        gi.assert_no_same_day_rebuy(trades)
        audits[name] = fc.signal_audit(d, trades)
        traces[name] = ft.trace_orders(d, book, rules, result['trades_digest'])
        if base_name in ('GW-C', 'GW-L'):
            kind_audits[name] = trace_open_kinds(d, book, rules, result['trades_digest'])
            if kind_audits[name]['max_list'] > 1:
                raise AssertionError('H3 concurrent limit exceeded')
        if base_name in ('C0', 'GU-M', 'GW-C'):
            cash_audits[name] = fx.audit_open_cash(d, book, rules, result)
            if cash_audits[name]['negative_cash'] or result['metrics']['max_close_positions'] > 6 or any(
                    x['max_positions_after_open'] > 6 for x in traces[name]['years'].values()):
                raise AssertionError('cash or position limit exceeded')
    ledger = []
    for r in low_unknown:
        key = (r['day'], r['code'], r['kind'])
        record = dict(r, accounts={})
        for base_name, name, book, rules in cases:
            trace = next((o for o in traces[name]['orders']
                          if (o['day'], o['code'], o['kind']) == key), None)
            trade = next((t for t in results[name]['trade_keys']
                          if (t[3], t[0], t[2]) == key), None)
            present = any((d.days[i], str(d.A['codes'][e[1]]), e[5]) == key
                          for i, row in enumerate(book) if d.days[i] == r['day'] for e in row)
            if present != (trace is not None):
                raise AssertionError('ambiguous order trace missing')
            if trace is not None and (trace['reason'] == 'opened') != (trade is not None):
                raise AssertionError('ambiguous order trade mismatch')
            record['accounts'][name] = {'reason': trace['reason'] if trace else 'not_in_book',
                                        'exit': trade[4] if trade else None,
                                        'exit_reason': trade[5] if trade else None}
        ledger.append(record)
    out = {'dataset_digest': data_digest, 'gi_sha256': sha(ref_path), 'gu_sha256': sha(gu_path),
           'gv_sha256': sha(gv_path),
           'system_sha256': sha(Path(system.__file__)), 'script_sha256': sha(Path(__file__)),
           'old_open_precision_unknown': precision_open, 'low_precision_unknown': low_unknown,
           'changed_keys': changed_keys, 'results': results, 'trail_audits': audits, 'traces': traces,
           'cash_audits': cash_audits, 'kind_audits': kind_audits, 'ambiguous_ledger': ledger}
    target = root / 'strong_continue_gw.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False,
                                 default=json_default) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
