"""FO: execute prior-close-confirmed R adds at the next qualifying open."""
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
from studies.trader_replication import martin_continue_fn as fn
from studies.trader_replication.martin_continue_b_check import digest
from studies.trader_replication.martin_continue_bm import describe
from studies.trader_replication.martin_continue_bt import fidelity
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import HOLD, f1_rules, hold_sim, u1_entries
from studies.trader_replication.martin_continue_bv import daily_name_score


def check_add_events(d, trades, events):
    codes = {str(code): j for j, code in enumerate(d.A['codes'])}
    previous = {}
    for event in events:
        day, j = d.di[event['day']], codes[event['code']]
        level, status = event['level'], event['status']
        if status == 'confirmed':
            close = float(d.A['close'][day, j])
            if event['day'] != event['signal_day'] or not np.isfinite(close) or close < level:
                raise AssertionError('invalid add confirmation')
            continue
        if event['signal_day'] >= event['day']:
            raise AssertionError('add event not after confirmation')
        op = float(d.A['open'][day, j])
        if status == 'missing_open':
            if np.isfinite(op) and op > 0:
                raise AssertionError('valid opening marked missing')
            continue
        if not np.isfinite(op) or op <= 0 or event['opening'] != op:
            raise AssertionError('invalid event opening')
        if status == 'precision_unknown' and np.float32(op) != np.float32(level):
            raise AssertionError('precision event differs')
        if status == 'open_below_level' and (op > level or np.float32(op) == np.float32(level)):
            raise AssertionError('cancellation differs')
        if status in ('filled', 'budget_rejected') and (op <= level or np.float32(op) == np.float32(level)):
            raise AssertionError('add attempted without qualifying open')
        if status != 'position_exit':
            order = (event['entry_day'], event['code'])
            if day in previous and order < previous[day]:
                raise AssertionError('add priority differs')
            previous[day] = order
    filled = Counter((e['day'], e['code'], e['opening']) for e in events if e['status'] == 'filled')
    actual = Counter((e['time'], t['code'], e['price']) for t in trades for e in t['executions'] if e['action'] == 'add')
    if filled != actual:
        raise AssertionError('filled add events differ from execution ledger')
    return {y: dict(Counter(e['status'] for e in events if e['day'].startswith(y)))
            for y in ('2024', '2025', '2026')}


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
    events = track.get('add_orders', [])
    event_counts = check_add_events(d, trades, events) if rules.add_next_open else {}
    pending = [{'code': t['code'], **t['state']['add_pending']} for t in trades
               if t['why'] == 'end' and 'add_pending' in t['state']]
    keys = [[t['code'], int(t['side']), t['kind'], t['entry'], t['exit'], t['why']] for t in trades]
    return {'metrics': m, 'fidelity': fidelity(d, trades), 'trade_keys': keys, 'trades_digest': digest(trades),
            'exit_reasons': dict(Counter(t['why'] for t in trades)),
            'add_events': events, 'add_event_counts': event_counts, 'pending_adds': pending}


def main():
    root = du.REPORTS
    path, er_path, ep_path = (root / 'strong_continue_fn.json', root / 'strong_continue_er.json',
                              root / 'strong_continue_ep_full.json')
    ref, ref_er, ep_ref = json.loads(path.read_text()), json.loads(er_path.read_text()), json.loads(ep_path.read_text())
    old_system = root / 'source_pins/system_pre_fo.py.txt'
    if (ref['script_sha256'] != sha(Path(fn.__file__)) or ref['system_sha256'] != sha(old_system) or
            ref_er['script_sha256'] != sha(Path(er.__file__)) or ref_er['ep_sha256'] != sha(ep_path) or
            not ep_ref['original_peer_replayed']):
        raise ValueError('FN / ER / EP source differs')
    ref = {'dataset_digest': ref['dataset_digest'], 'list_counts': ref['list_counts'],
           'core_counts': ref['core_counts'], 'core_precision_unknown': ref['core_precision_unknown'],
           'results': {name: ref['results'][name] for name in ('FN2', 'FN4')}}
    del ref_er, ep_ref
    gc.collect()
    dataset = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if dataset.digest() != ref['dataset_digest']:
        raise ValueError('dataset differs')
    d = du.make_data(dataset)
    fields, mask, unused_holding = du.compute_fields(d)
    del unused_holding
    gc.collect()
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
    score = daily_name_score(fields, mask, HOLD['H3'])
    holding = hold_sim(score, 12, 36)
    u1 = u1_entries(d, fields, holding, score)
    del score, holding
    u1_open, list_counts = ah.delayed_list(d, u1)
    if list_counts != ref['list_counts'] or er.ambiguous_orders(d, u1):
        raise AssertionError('FN list counts differ or precision unknown')
    core = [[e for e in row if e[2] > 0 and e[5] != 'list'] for row in u1]
    core_open, core_counts = dg.next_open(core, d.A['open'], d.A['low'], d.days)
    core_open, unknown = fe.remove_precision_unknown(core_open, d.days, d.A['codes'])
    unknown = [x for x in unknown if panels.WINDOW[0] <= x[0] <= panels.WINDOW[1]]
    if core_counts != ref['core_counts'] or unknown != ref['core_precision_unknown']:
        raise AssertionError('FN core orders differ')
    _, long_only = fn.build_books(u1_open, core_open)
    del fields, mask, u1, core, u1_open, core_open
    gc.collect()
    lever = f1_rules(d, 6, (1, 3))
    delayed = replace(lever, intraday_kinds=tuple(lever.intraday_kinds) + ('list', 'n1'))
    lagged = replace(delayed, trail_next_open=True)
    cases = [('FN2', delayed), ('FN4', replace(fn.no_adds(delayed), trail_next_open=True)),
             ('FO0', lagged), ('FO1', replace(lagged, add_next_open=True))]
    results = {}
    for name, rules in cases:
        print('account', name, flush=True)
        results[name] = account(d, long_only, rules)
        if name in ('FN2', 'FN4'):
            a, b = results[name], ref['results'][name]
            if a['trade_keys'] != b['trade_keys'] or a['fidelity'] != b['fidelity']:
                raise AssertionError('FN baseline trade keys / fidelity differ ' + name)
            for year in ('2024', '2025', '2026'):
                if (abs(a['metrics']['by_year'][year] - b['metrics']['by_year'][year]) > 1e-10 or
                        a['metrics']['entries_by_year'][year] != b['metrics']['entries_by_year'][year]):
                    raise AssertionError('FN baseline differs ' + name + ' ' + year)
    out = {'dataset_digest': ref['dataset_digest'], 'fn_sha256': sha(path), 'er_sha256': sha(er_path),
           'old_system_sha256': sha(old_system), 'system_sha256': sha(Path(system.__file__)),
           'script_sha256': sha(Path(__file__)), 'list_counts': list_counts,
           'core_counts': core_counts, 'core_precision_unknown': unknown, 'results': results}
    target = root / 'strong_continue_fo.json'
    with target.open('w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        f.write('\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
