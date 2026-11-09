"""GK: fixed two-by-two core and list stop policies in full accounts."""
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
from studies.trader_replication import martin_continue_ft as ft
from studies.trader_replication import martin_continue_gi as gi
from studies.trader_replication.martin_continue_b_check import digest
from studies.trader_replication.martin_continue_bv import daily_name_score
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import HOLD, f1_rules, hold_sim, u1_entries


def mix(old_book, fixed_book, fixed_kind):
    if fixed_kind not in ('n1', 'list') or len(old_book) != len(fixed_book):
        raise ValueError('invalid channel or book length')
    result = []
    for old, fixed in zip(old_book, fixed_book):
        source_core = fixed if fixed_kind == 'n1' else old
        source_list = fixed if fixed_kind == 'list' else old
        if any(e[5] not in ('n1', 'list') for e in (*old, *fixed)):
            raise ValueError('unexpected channel')
        result.append([*(e for e in source_core if e[5] == 'n1'),
                       *(e for e in source_list if e[5] == 'list')])
    return result


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
    expected = {n: ref['results'][n] for n in ('L0', 'L1_hit', 'Q0', 'Q1_hit')}
    core_counts, list_counts, old_unknown = ref['old_core_counts'], ref['old_list_counts'], ref['old_core_precision_unknown']
    fixed_counts, fixed_rows = ref['fixed_hit_counts'], ref['fixed_hit_orders']
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
    fixed_hit, hit_counts, hit_rows = gi.fixed_book(d, core, u1, True)
    fixed_nohit, nohit_counts, nohit_rows = gi.fixed_book(d, core, u1, False)
    if hit_counts != fixed_counts or hit_rows != fixed_rows:
        raise AssertionError('GI fixed orders differ')
    if fixed_hit != fixed_nohit or hit_counts != nohit_counts or hit_rows != nohit_rows:
        raise ValueError('fixed-stop precision paths differ; no candidate run')
    a_book, b_book = mix(old_book, fixed_hit, 'list'), mix(old_book, fixed_hit, 'n1')
    del fields, mask, u1, core, list_open, core_open, fixed_nohit, hit_rows, nohit_rows, fixed_rows
    gc.collect()
    lever = f1_rules(d, 6, (1, 3))
    lever = replace(lever, intraday_kinds=tuple(lever.intraday_kinds) + ('list', 'n1'),
                    trail_next_open=True, add_next_open=True, no_rebuy_day=True)
    q = replace(lever, max_open=11)
    cases = [('L0', old_book, lever), ('L1_hit', fixed_hit, lever),
             ('Q0', old_book, q), ('Q1_hit', fixed_hit, q),
             ('LA', a_book, lever), ('LB', b_book, lever),
             ('QA', a_book, q), ('QB', b_book, q)]
    results, audits, traces = {}, {}, {}
    for name, book, rules in cases:
        print('account', name, flush=True)
        result = fo.account(d, book, rules)
        results[name] = result
        if name in expected and result != expected[name]:
            raise AssertionError('GI account differs ' + name)
        px, ema = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules)
        _, _, trades = system.simulate(px, ema, rules, book, *panels.WINDOW, audit=True)
        if digest(trades) != result['trades_digest']:
            raise AssertionError('audit account differs')
        gi.assert_no_same_day_rebuy(trades)
        audits[name] = fc.signal_audit(d, trades)
        traces[name] = ft.trace_orders(d, book, rules, result['trades_digest'])
        if rules.max_open == 11 and any(x['max_positions_after_open'] > 11 for x in traces[name]['years'].values()):
            raise AssertionError('eleven-position limit exceeded')
    out = {'dataset_digest': data_digest, 'gi_sha256': sha(ref_path), 'system_sha256': sha(Path(system.__file__)),
           'script_sha256': sha(Path(__file__)), 'fixed_stop_paths_identical': True,
           'old_core_precision_unknown': unknown, 'results': results, 'trail_audits': audits, 'traces': traces}
    target = root / 'strong_continue_gk.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False,
                                 default=json_default) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
