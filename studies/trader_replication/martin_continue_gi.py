"""GI: fixed open-relative stops in full preselected cash and leveraged accounts."""
from collections import Counter
from dataclasses import replace
import gc
import json
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
from studies.trader_replication import martin_continue_fp as fp
from studies.trader_replication import martin_continue_fq as fq
from studies.trader_replication import martin_continue_ft as ft
from studies.trader_replication import martin_continue_fx as fx
from studies.trader_replication import martin_continue_gf as gf
from studies.trader_replication.martin_continue_b_check import digest
from studies.trader_replication.martin_continue_bv import daily_name_score
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import HOLD, f1_rules, hold_sim, nl_rules, u1_entries


def fixed_book(d, core, u1, ambiguous_hit):
    book, counts, records, missing_low = [[] for _ in d.days], Counter(), [], []
    for day in range(1, len(d.days)):
        if not panels.WINDOW[0] <= d.days[day] <= panels.WINDOW[1]:
            continue
        listed = sorted((e for e in u1[day - 1] if e[5] == 'list'), key=lambda e: e[0])[:6]
        for e in [*core[day - 1], *listed]:
            j, kind, old_stop = e[1], e[5], float(e[4])
            opening, low = float(d.A['open'][day, j]), float(d.A['low'][day, j])
            within = panels.WINDOW[0] <= d.days[day] <= panels.WINDOW[1]
            row = {'signal_day': d.days[day - 1], 'day': d.days[day], 'code': str(d.A['codes'][j]), 'kind': kind}
            def mark(label):
                if within:
                    counts[(d.days[day][:4], kind, label)] += 1
            mark('preselected')
            if not np.isfinite(opening) or opening <= 0:
                mark('opening_missing')
                row['status'] = 'opening_missing'
            elif not np.isfinite(low) or low <= 0:
                mark('low_missing')
                row['status'] = 'low_missing'
                missing_low.append((d.days[day], row['code'], kind))
            else:
                stop = opening * (1 - gf.STOP_PCT)
                hit, unknown = gf.same_day_stop(low, stop, ambiguous_hit)
                old_ambiguous = np.float32(opening) == np.float32(old_stop)
                old_cancel = opening < old_stop and not old_ambiguous
                mark('fillable')
                if old_ambiguous:
                    mark('old_open_stop_precision_unknown')
                elif old_cancel:
                    mark('old_cancel_new_fillable')
                if unknown:
                    mark('new_stop_precision_unknown')
                if hit:
                    mark('day0_stop')
                row.update(status='fillable', old_open_stop_precision_unknown=bool(old_ambiguous),
                           old_cancel=bool(old_cancel), stop_precision_unknown=unknown,
                           old_stop=old_stop, new_stop=stop, day0_stop=bool(hit))
                book[day].append((e[0], j, e[2], opening, stop, kind, stop if hit else None) + tuple(e[7:]))
            if within:
                records.append(row)
    if missing_low:
        raise ValueError('missing low prevents full-account simulation: ' + repr(missing_low[:10]))
    return book, {':'.join(k): int(v) for k, v in sorted(counts.items())}, records


def assert_no_same_day_rebuy(trades):
    last_exit = {}
    for trade in sorted(trades, key=lambda t: (t['entry'], t['code'])):
        if trade['code'] in last_exit and last_exit[trade['code']] >= trade['entry']:
            raise AssertionError('same-day or overlapping repurchase')
        last_exit[trade['code']] = trade['exit']


def main():
    root = du.REPORTS
    fp_path, fn_path, fq_path, fc_path = (root / 'strong_continue_fp.json', root / 'strong_continue_fn.json',
                                           root / 'strong_continue_fq.json', root / 'strong_continue_fc.json')
    fp_ref, fn_ref, fq_ref, fc_ref = (json.loads(p.read_text()) for p in (fp_path, fn_path, fq_path, fc_path))
    if (fp_ref['script_sha256'] != sha(Path(fp.__file__)) or fn_ref['script_sha256'] != sha(Path(fn.__file__))
            or fq_ref['script_sha256'] != sha(Path(fq.__file__)) or fp_ref['system_sha256'] != sha(Path(system.__file__))
            or fq_ref['system_sha256'] != sha(Path(system.__file__))):
        raise ValueError('baseline source differs')
    dataset = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    data_digest = dataset.digest()
    if any(r['dataset_digest'] != data_digest for r in (fp_ref, fn_ref, fq_ref, fc_ref)):
        raise ValueError('dataset differs')
    expected_fo, expected_fq, expected_fc = fp_ref['results']['FO1'], fq_ref['results']['FQ1'], fc_ref['results']['FC1']
    list_counts, core_counts, precision = fn_ref['list_counts'], fn_ref['core_counts'], fn_ref['core_precision_unknown']
    del fp_ref, fn_ref, fq_ref, fc_ref
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
    if {e[5] for row in core for e in row} != {'n1'}:
        raise ValueError('unexpected core kind')
    core_open, got_core = dg.next_open(core, d.A['open'], d.A['low'], d.days)
    core_open, unknown = fe.remove_precision_unknown(core_open, d.days, d.A['codes'])
    unknown = [x for x in unknown if panels.WINDOW[0] <= x[0] <= panels.WINDOW[1]]
    if got_core != core_counts or unknown != precision:
        raise AssertionError('original core candidates differ')
    _, old_full = fn.build_books(list_open, core_open)
    hit, hit_counts, hit_rows = fixed_book(d, core, u1, True)
    nohit, nohit_counts, nohit_rows = fixed_book(d, core, u1, False)
    for a, b in zip(hit_rows, nohit_rows):
        if {k: v for k, v in a.items() if k != 'day0_stop'} != {k: v for k, v in b.items() if k != 'day0_stop'}:
            raise AssertionError('fixed-stop candidate identity differs')
    new_core_hit = [[e for e in row if e[5] == 'n1'] for row in hit]
    new_core_nohit = [[e for e in row if e[5] == 'n1'] for row in nohit]
    del fields, mask, u1, core, list_open
    gc.collect()
    lever = f1_rules(d, 6, (1, 3))
    lever = replace(lever, intraday_kinds=tuple(lever.intraday_kinds) + ('list', 'n1'),
                    trail_next_open=True, add_next_open=True)
    cash = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True)
    cash = replace(cash, intraday_kinds=tuple(sorted(set(cash.intraday_kinds) | {'n1'})))
    cases = [('FC1', core_open, cash), ('C0', core_open, replace(cash, no_rebuy_day=True)),
             ('C1_hit', new_core_hit, replace(cash, no_rebuy_day=True)),
             ('C1_nohit', new_core_nohit, replace(cash, no_rebuy_day=True)),
             ('FO1', old_full, lever), ('L0', old_full, replace(lever, no_rebuy_day=True)),
             ('L1_hit', hit, replace(lever, no_rebuy_day=True)),
             ('L1_nohit', nohit, replace(lever, no_rebuy_day=True)),
             ('FQ1', old_full, replace(lever, max_open=11)),
             ('Q0', old_full, replace(lever, max_open=11, no_rebuy_day=True)),
             ('Q1_hit', hit, replace(lever, max_open=11, no_rebuy_day=True)),
             ('Q1_nohit', nohit, replace(lever, max_open=11, no_rebuy_day=True))]
    results, audits, traces, cash_audits = {}, {}, {}, {}
    for name, active, rules in cases:
        print('account', name, flush=True)
        result = fo.account(d, active, rules)
        results[name] = result
        if name == 'FO1' and result != expected_fo:
            raise AssertionError('FO1 differs')
        if name == 'FQ1' and result != expected_fq:
            raise AssertionError('FQ1 differs')
        if name == 'FC1':
            if result['trades_digest'] != expected_fc['trades_digest'] or result['fidelity'] != expected_fc['fidelity']:
                raise AssertionError('FC1 trade / fidelity differs')
            for key in ('by_year', 'maxdd', 'win', 'payoff', 'entries_by_year', 'invested_basis',
                        'max_close_positions', 'max_close_gross'):
                if result['metrics'][key] != expected_fc['metrics'][key]:
                    raise AssertionError('FC1 metric differs: ' + key)
        px, em = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules)
        _, _, trades = system.simulate(px, em, rules, active, *panels.WINDOW, audit=True)
        if digest(trades) != result['trades_digest']:
            raise AssertionError('audit account differs')
        if rules.no_rebuy_day:
            assert_no_same_day_rebuy(trades)
        audits[name] = fc.signal_audit(d, trades)
        traces[name] = ft.trace_orders(d, active, rules, result['trades_digest'])
        limit = 6 if name.startswith('C') or name == 'FC1' else (11 if name.startswith('Q') or name == 'FQ1' else None)
        if limit and any(y['max_positions_after_open'] > limit for y in traces[name]['years'].values()):
            raise AssertionError('position limit exceeded')
        if limit == 6:
            if result['metrics']['max_close_gross'] > 1 + 1e-7:
                raise AssertionError('cash gross exceeds one')
            cash_audits[name] = fx.audit_open_cash(d, active, rules, result)
            if cash_audits[name]['negative_cash']:
                raise AssertionError('negative cash after opening')
    out = {'dataset_digest': data_digest, 'fp_sha256': sha(fp_path), 'fn_sha256': sha(fn_path),
           'fq_sha256': sha(fq_path), 'fc_sha256': sha(fc_path), 'system_sha256': sha(Path(system.__file__)),
           'script_sha256': sha(Path(__file__)), 'old_core_counts': got_core, 'old_list_counts': got_list,
           'old_core_precision_unknown': unknown, 'fixed_hit_counts': hit_counts, 'fixed_nohit_counts': nohit_counts,
           'fixed_hit_orders': hit_rows, 'fixed_nohit_orders': nohit_rows,
           'results': results, 'trail_audits': audits, 'traces': traces, 'cash_audits': cash_audits}
    target = root / 'strong_continue_gi.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False,
                                 default=json_default) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
