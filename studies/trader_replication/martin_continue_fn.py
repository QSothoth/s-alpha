"""FN: isolate remaining timing assumptions in the precision-corrected leveraged book."""
from collections import Counter
from dataclasses import replace
import gc
import json
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trader_replication import compare, panels, system
from studies.trader_replication import martin_continue_ah as ah
from studies.trader_replication import martin_continue_dg as dg
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ef as ef
from studies.trader_replication import martin_continue_ep as ep
from studies.trader_replication import martin_continue_er as er
from studies.trader_replication import martin_continue_fe as fe
from studies.trader_replication.martin_continue_b_check import digest
from studies.trader_replication.martin_continue_bm import describe
from studies.trader_replication.martin_continue_bt import fidelity
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import f1_rules


def build_books(u1_open, core_open):
    shifted = [[*core, *(e for e in row if e[5] == 'list' or e[2] < 0)]
               for row, core in zip(u1_open, core_open)]
    long_only = [[e for e in row if e[2] > 0] for row in shifted]
    return shifted, long_only


def no_adds(rules):
    management = {k: {**v, 'add_levels': (), 'add_r': 0.0} for k, v in rules.management_by_kind.items()}
    return replace(rules, add_levels=(), add_r=0.0, add_signal='', management_by_kind=management)


def account(d, book, rules):
    px, em = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules)
    track = {}
    curve, dates, trades = system.simulate(px, em, rules, book, *panels.WINDOW, audit=True, track=track)
    lo = int(np.searchsorted(d.A['days'], panels.WINDOW[0]))
    hi = int(np.searchsorted(d.A['days'], panels.WINDOW[1], side='right'))
    m = compare.metrics(curve, dates, trades, book, lo, hi)
    m['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in trades) for y in ('2024', '2025', '2026')}
    m['invested_basis'] = describe([t for t in trades if t['why'] != 'end'], 'ret_invested')
    m['max_close_positions'] = max(track['open'])
    m['average_close_positions'] = float(np.mean(track['open']))
    m['max_close_gross'] = float(max(track['gross']))
    m['margin_paid'] = float(track['margin'])
    m['add_executions_by_year'] = {y: sum(e['action'] == 'add' and e['time'].startswith(y)
                                            for t in trades for e in t['executions'])
                                       for y in ('2024', '2025', '2026')}
    keys = [[t['code'], int(t['side']), t['kind'], t['entry'], t['exit'], t['why']] for t in trades]
    return {'metrics': m, 'fidelity': fidelity(d, trades), 'trade_keys': keys, 'trades_digest': digest(trades),
            'exit_reasons': dict(Counter(t['why'] for t in trades))}


def main():
    root = du.REPORTS
    path, ep_path = root / 'strong_continue_er.json', root / 'strong_continue_ep_full.json'
    ref, ep_ref = json.loads(path.read_text()), json.loads(ep_path.read_text())
    if ref['script_sha256'] != sha(Path(er.__file__)) or ref['ep_sha256'] != sha(ep_path) or not ep_ref['original_peer_replayed']:
        raise ValueError('ER / EP source differs')
    dataset = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if dataset.digest() != ref['dataset_digest']:
        raise ValueError('dataset differs')
    d = du.make_data(dataset)
    fields, mask, _ = du.compute_fields(d)
    original = ep.original_eligibility(d)
    replay, old_pot = ep.peer_potential(d, original)
    for i, day in enumerate(d.days):
        if not np.array_equal(replay[i], fields['peer_pot'][i], equal_nan=True):
            raise AssertionError('original peer_pot mismatch ' + day)
    del original, replay, old_pot
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
    u1, _ = ef.books(d, fields, mask)
    u1_open, list_counts = ah.delayed_list(d, u1)
    if list_counts != ref['candidate_counts']['U1'] or er.ambiguous_orders(d, u1):
        raise AssertionError('ER list counts differ or precision unknown')
    core = [[e for e in row if e[2] > 0 and e[5] != 'list'] for row in u1]
    if {e[5] for row in core for e in row} != {'n1'}:
        raise ValueError('unexpected core kinds')
    core_open, core_counts = dg.next_open(core, d.A['open'], d.A['low'], d.days)
    core_open, unknown = fe.remove_precision_unknown(core_open, d.days, d.A['codes'])
    unknown = [x for x in unknown if panels.WINDOW[0] <= x[0] <= panels.WINDOW[1]]
    shifted, long_only = build_books(u1_open, core_open)
    for a, b in zip(u1_open, shifted):
        if [e for e in a if e[5] == 'list' or e[2] < 0] != [e for e in b if e[5] == 'list' or e[2] < 0]:
            raise AssertionError('non-core orders changed')
    del fields, mask, u1, core
    gc.collect()
    lever = f1_rules(d, 6, (1, 3))
    if 'list' in lever.intraday_kinds or 'n1' in lever.intraday_kinds:
        raise ValueError('baseline entry timing changed')
    base = replace(lever, intraday_kinds=tuple(lever.intraday_kinds) + ('list',))
    delayed = replace(base, intraday_kinds=tuple(base.intraday_kinds) + ('n1',))
    no_pyramid = no_adds(delayed)
    cases = [('U1_open', u1_open, base), ('FN1', shifted, delayed), ('FN2', long_only, delayed),
             ('FN3', long_only, no_pyramid), ('FN4', long_only, replace(no_pyramid, trail_next_open=True))]
    results = {}
    for name, book, rules in cases:
        print('account', name, flush=True)
        results[name] = account(d, book, rules)
        if name in ('FN3', 'FN4') and any(results[name]['metrics']['add_executions_by_year'].values()):
            raise AssertionError('unexpected add execution')
    expected = ref['results']['U1_open']
    actual = results['U1_open']
    if actual['trade_keys'] != expected['trade_keys'] or actual['fidelity'] != expected['fidelity']:
        raise AssertionError('ER trade keys / fidelity differ')
    for y in ('2024', '2025', '2026'):
        if (abs(actual['metrics']['by_year'][y] - expected['metrics']['by_year'][y]) > 1e-10 or
                actual['metrics']['entries_by_year'][y] != expected['metrics']['entries_by_year'][y]):
            raise AssertionError('ER annual baseline differs ' + y)
    out = {'dataset_digest': ref['dataset_digest'], 'er_sha256': sha(path), 'ep_sha256': sha(ep_path),
           'script_sha256': sha(Path(__file__)), 'system_sha256': sha(Path(system.__file__)),
           'list_counts': list_counts, 'core_counts': core_counts, 'core_precision_unknown': unknown,
           'results': results}
    target = root / 'strong_continue_fn.json'
    with target.open('w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        f.write('\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
