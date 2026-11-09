"""GJ: locate window and realized-trade differences in GI's leveraged paths."""
from collections import Counter, defaultdict
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
from studies.trader_replication import martin_continue_es as es
from studies.trader_replication import martin_continue_fe as fe
from studies.trader_replication import martin_continue_fn as fn
from studies.trader_replication import martin_continue_fo as fo
from studies.trader_replication import martin_continue_gi as gi
from studies.trader_replication.martin_continue_b_check import digest
from studies.trader_replication.martin_continue_bv import daily_name_score
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import HOLD, f1_rules, hold_sim, u1_entries


def key(t):
    return t['entry'], t['kind'], t['code']


def overlapping(trades, code, start, end):
    return [t for t in trades if t['code'] == code and t['side'] > 0 and t['entry'] <= end and t['exit'] >= start]


def explain_order(t, other_trades, other_trace, fixed_orders, other_name, window_start):
    k = key(t)
    rec = other_trace.get(k)
    same = next((x for x in other_trades if key(x) == k), None)
    result = {'entry': t['entry'], 'kind': t['kind'], 'exit': t['exit'], 'exit_reason': t['why'],
              'pnl': t['pnl'], 'r': t['r'], 'other_reason': rec['reason'] if rec else 'not_traced'}
    if rec and rec['reason'] == 'opened':
        if same is None or same['exit'] >= window_start:
            raise AssertionError('same order missing or would overlap window')
        result.update(classification='opened_ended_before_window', other_exit=same['exit'],
                      other_exit_reason=same['why'], other_pnl=same['pnl'], other_r=same['r'])
    elif rec and rec.get('held_entry'):
        held = [x for x in other_trades if x['code'] == t['code'] and x['entry'] == rec['held_entry']]
        if len(held) != 1 or held[0]['exit'] >= window_start:
            raise AssertionError('prior held position missing or overlaps window')
        result.update(classification='already_held', held_entry=held[0]['entry'], held_exit=held[0]['exit'],
                      held_kind=held[0]['kind'], held_exit_reason=held[0]['why'])
    elif rec:
        reason = rec['reason']
        if 'no_rebuy_day' in reason:
            classification = 'same_day_rebuy_block'
        elif 'val <= 0.001 * equity' in reason:
            classification = 'budget_or_size'
        elif 'max_open' in reason:
            classification = 'position_limit'
        elif reason == 'not_reached' or reason.startswith('take:'):
            classification = 'daily_quota_or_not_reached'
        else:
            classification = 'other_guard'
        result['classification'] = classification
        result['limiting'] = rec.get('limiting', [])
    else:
        pre = fixed_orders.get(k)
        if other_name == 'L0' and pre and pre.get('old_open_stop_precision_unknown'):
            result['classification'] = 'old_stop_precision_unknown'
        elif other_name == 'L0' and pre and pre.get('old_cancel'):
            result['classification'] = 'old_stop_cancel'
        else:
            result['classification'] = 'not_located'
    return result


def trade_stats(trades):
    closed = [t for t in trades if t['why'] != 'end']
    positive = sorted((t['pnl'] for t in closed if t['pnl'] > 0), reverse=True)
    negative = [t['pnl'] for t in closed if t['pnl'] <= 0]
    return {'opened': len(trades), 'closed': len(closed), 'end_marked': len(trades) - len(closed),
            'closed_win': len(positive), 'closed_nonpositive': len(negative),
            'ge5r': sum(t['r'] >= 5 for t in closed), 'ge10r': sum(t['r'] >= 10 for t in closed),
            'median_r': float(np.median([t['r'] for t in closed])) if closed else None,
            'median_ret': float(np.median([t['ret'] for t in closed])) if closed else None,
            'positive_pnl': sum(positive), 'nonpositive_pnl': sum(negative),
            'net_closed_pnl': sum(t['pnl'] for t in closed),
            'top10_share_positive': sum(positive[:10]) / sum(positive) if positive else None,
            'exit_reasons': dict(Counter(t['why'] for t in closed))}


def pnl_components(old, new):
    a, b = {key(t): t for t in old}, {key(t): t for t in new}
    if len(a) != len(old) or len(b) != len(new):
        raise ValueError('duplicate trade key')
    all_keys = sorted(set(a) | set(b))
    result = {}
    for year in ('2024', '2025', '2026'):
        selected = [k for k in all_keys if k[0].startswith(year)]
        both = [k for k in selected if k in a and k in b and a[k]['why'] != 'end' and b[k]['why'] != 'end']
        old_only = [k for k in selected if k in a and k not in b and a[k]['why'] != 'end']
        new_only = [k for k in selected if k in b and k not in a and b[k]['why'] != 'end']
        uncertain = [k for k in selected if (k in a and a[k]['why'] == 'end') or (k in b and b[k]['why'] == 'end')]
        if len(both) + len(old_only) + len(new_only) + len(uncertain) != len(selected):
            raise AssertionError('trade classification incomplete')
        def amounts(keys, side):
            vals = [side[k]['pnl'] for k in keys]
            return {'count': len(vals), 'positive': sum(v for v in vals if v > 0),
                    'nonpositive': sum(v for v in vals if v <= 0), 'net': sum(vals)}
        result[year] = {'matched_old': amounts(both, a), 'matched_new': amounts(both, b),
                        'old_only': amounts(old_only, a), 'new_only': amounts(new_only, b),
                        'end_marked_keys': len(uncertain),
                        'end_marked_old_closed': amounts([k for k in uncertain if k in a and a[k]['why'] != 'end'], a),
                        'end_marked_new_closed': amounts([k for k in uncertain if k in b and b[k]['why'] != 'end'], b)}
        for side, name in ((a, 'old'), (b, 'new')):
            reported = sum(result[year][part]['net'] for part in
                           (('matched_' + name), (name + '_only'), ('end_marked_' + name + '_closed')))
            actual = sum(t['pnl'] for k, t in side.items() if k[0].startswith(year) and t['why'] != 'end')
            if abs(reported - actual) > 1e-9:
                raise AssertionError('closed PnL classification differs')
    return result


def main():
    root = du.REPORTS
    gi_path, es_path = root / 'strong_continue_gi.json', root / 'strong_continue_es.json'
    ref, windows_ref = json.loads(gi_path.read_text()), json.loads(es_path.read_text())
    if (ref['script_sha256'] != sha(Path(gi.__file__)) or ref['system_sha256'] != sha(Path(system.__file__))
            or windows_ref['script_sha256'] != sha(Path(es.__file__)) or ref['dataset_digest'] != windows_ref['dataset_digest']):
        raise ValueError('GI / ES source or data differs')
    dataset = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if dataset.digest() != ref['dataset_digest']:
        raise ValueError('dataset differs')
    expected = {name: ref['results'][name] for name in ('L0', 'L1_hit')}
    traces = {name: {(r['day'], r['kind'], r['code']): r for r in ref['traces'][name]['orders']}
              for name in ('L0', 'L1_hit')}
    fixed_orders = {(r['day'], r['kind'], r['code']): r for r in ref['fixed_hit_orders']}
    counts, list_counts, old_unknown = ref['old_core_counts'], ref['old_list_counts'], ref['old_core_precision_unknown']
    fixed_counts, fixed_rows = ref['fixed_hit_counts'], ref['fixed_hit_orders']
    windows = windows_ref['results']['U1']['windows']
    if len(windows) != 25:
        raise ValueError('ES window count differs')
    del ref, windows_ref
    gc.collect()
    d = du.make_data(dataset)
    fields, mask, unused_holding = du.compute_fields(d)
    del unused_holding
    gc.collect()
    old = ep.original_eligibility(d)
    replay, old_pot = ep.peer_potential(d, old)
    for i, day in enumerate(d.days):
        if not np.array_equal(replay[i], fields['peer_pot'][i], equal_nan=True):
            raise AssertionError('old peer potential differs ' + day)
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
        raise AssertionError('original list differs')
    core = [[e for e in row if e[2] > 0 and e[5] != 'list'] for row in u1]
    core_open, got_core = dg.next_open(core, d.A['open'], d.A['low'], d.days)
    core_open, unknown = fe.remove_precision_unknown(core_open, d.days, d.A['codes'])
    unknown = [x for x in unknown if panels.WINDOW[0] <= x[0] <= panels.WINDOW[1]]
    if got_core != counts or unknown != old_unknown:
        raise AssertionError('original core differs')
    _, old_book = fn.build_books(list_open, core_open)
    new_book, got_fixed_counts, got_fixed_rows = gi.fixed_book(d, core, u1, True)
    if got_fixed_counts != fixed_counts or got_fixed_rows != fixed_rows:
        raise AssertionError('fixed stop order stream differs')
    del fields, mask, u1, core, list_open, core_open, got_fixed_rows, fixed_rows
    gc.collect()
    rules = f1_rules(d, 6, (1, 3))
    rules = replace(rules, intraday_kinds=tuple(rules.intraday_kinds) + ('list', 'n1'),
                    trail_next_open=True, add_next_open=True, no_rebuy_day=True)
    px, ema = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules)
    account_trades = {}
    for name, book in (('L0', old_book), ('L1_hit', new_book)):
        print('account', name, flush=True)
        actual = fo.account(d, book, rules)
        if actual != expected[name]:
            raise AssertionError('GI full account differs ' + name)
        _, _, trades = system.simulate(px, ema, rules, book, *panels.WINDOW, audit=True)
        if digest(trades) != actual['trades_digest']:
            raise AssertionError('GI trade digest differs ' + name)
        gi.assert_no_same_day_rebuy(trades)
        account_trades[name] = trades
    details = []
    for w in windows:
        code, start, end = w['code'], w['date'], w['end']
        old = overlapping(account_trades['L0'], code, start, end)
        new = overlapping(account_trades['L1_hit'], code, start, end)
        evidence = []
        if old and not new:
            evidence = [explain_order(t, account_trades['L1_hit'], traces['L1_hit'], fixed_orders, 'L1_hit', start) for t in old]
        elif new and not old:
            evidence = [explain_order(t, account_trades['L0'], traces['L0'], fixed_orders, 'L0', start) for t in new]
        details.append({'code': code, 'date': start, 'end': end, 'old_held': bool(old), 'new_held': bool(new),
                        'old_positions': [key(t) for t in old], 'new_positions': [key(t) for t in new],
                        'evidence': evidence})
    yearly = {}
    for year in ('2024', '2025', '2026'):
        subset = [r for r in details if r['date'].startswith(year)]
        yearly[year] = {'windows': len(subset), 'old_held': sum(r['old_held'] for r in subset),
                        'new_held': sum(r['new_held'] for r in subset),
                        'old_only': sum(r['old_held'] and not r['new_held'] for r in subset),
                        'new_only': sum(r['new_held'] and not r['old_held'] for r in subset)}
        for name, field in (('L0', 'old_held'), ('L1_hit', 'new_held')):
            if yearly[year][field] != expected[name]['fidelity']['prepeak_ten_day'][year]['held']:
                raise AssertionError('window count differs ' + name + ' ' + year)
    per_trade = {name: {year: {kind: trade_stats([t for t in trades if t['entry'].startswith(year) and t['kind'] == kind])
                              for kind in ('n1', 'list')} for year in ('2024', '2025', '2026')}
                 for name, trades in account_trades.items()}
    records = {name: [{k: t[k] for k in ('code', 'kind', 'entry', 'exit', 'why', 'pnl', 'r', 'ret', 'ret_invested')}
                      for t in trades] for name, trades in account_trades.items()}
    out = {'dataset_digest': dataset.digest(), 'gi_sha256': sha(gi_path), 'es_sha256': sha(es_path),
           'system_sha256': sha(Path(system.__file__)), 'script_sha256': sha(Path(__file__)),
           'years': yearly, 'windows': details, 'trade_stats': per_trade,
           'pnl_components': pnl_components(account_trades['L0'], account_trades['L1_hit']), 'trades': records}
    target = root / 'strong_continue_gj.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False,
                                 default=json_default) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
