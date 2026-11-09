"""GY: reconcile actual GX account paths into per-trade marked contributions."""
from collections import defaultdict
from dataclasses import replace
import gc
import json
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trader_replication import panels, system, shorts, ledger, fidelity
from studies.trader_replication import martin_continue_dp as dp
from studies.trader_replication import martin_continue_ah as ah
from studies.trader_replication import martin_continue_dg as dg
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ep as ep
from studies.trader_replication import martin_continue_er as er
from studies.trader_replication import martin_continue_fe as fe
from studies.trader_replication import martin_continue_fn as fn
from studies.trader_replication import martin_continue_fo as fo
from studies.trader_replication import martin_continue_gi as gi
from studies.trader_replication import martin_continue_gu as gu
from studies.trader_replication import martin_continue_gv as gv
from studies.trader_replication import martin_continue_gx as gx
from studies.trader_replication.martin_continue_b_check import digest
from studies.trader_replication.martin_continue_bv import daily_name_score
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import HOLD, f1_rules, hold_sim, u1_entries


def key(t):
    return (t['code'], int(t['side']), t['kind'], t['entry'])


def last_price(close, i, j):
    while i > 0 and np.isnan(close[i, j]):
        i -= 1
    v = float(close[i, j])
    if not np.isfinite(v):
        raise ValueError('missing mark for held position')
    return v


def trade_contributions(trades, dates, codes, close, rules, first, last):
    """Per trade and day, cash flow plus change in marked exposure, including borrow."""
    index = {str(day): i for i, day in enumerate(dates)}
    columns = {str(code): j for j, code in enumerate(codes)}
    out, per_day = {}, np.zeros(len(dates), dtype=np.float64)
    for t in trades:
        k = key(t)
        if k in out:
            raise AssertionError('duplicate entry key')
        events = defaultdict(list)
        for e in t['executions']:
            if e['action'] != 'end':
                events[index[e['time']]].append(e)
        start, end = index[t['entry']], index[t['exit']]
        if start < first or end > last:
            raise AssertionError('trade outside window')
        side, j, shares, start_shares = int(t['side']), columns[t['code']], 0.0, None
        years, virtual_fee = defaultdict(float), 0.0
        for d in range(start, end + 1):
            before = side * shares * last_price(close, d - 1, j) if shares else 0.0
            borrow = (rules.borrow_rate / 252 * shares * last_price(close, d - 1, j)
                      if side < 0 and shares and d > first else 0.0)
            flow = -borrow
            for e in events[d]:
                amount, price = float(e['shares']), float(e['price'])
                entering = e['action'] in ('entry', 'add')
                if entering:
                    shares += amount
                    start_shares = shares if start_shares is None else start_shares
                    flow += -amount * price * (1 + rules.buy_cost) if side > 0 else amount * price * (1 - rules.sell_cost)
                else:
                    shares -= amount
                    if start_shares and shares <= 1e-12 * start_shares:
                        shares = 0.0
                    flow += amount * price * (1 - rules.sell_cost) if side > 0 else -amount * price * (1 + rules.buy_cost)
            after = side * shares * last_price(close, d, j) if shares else 0.0
            change = flow + after - before
            per_day[d] += change
            years[str(dates[d])[:4]] += change
        if t['why'] == 'end':
            last_exec = t['executions'][-1]
            if last_exec['action'] != 'end' or abs(float(last_exec['shares']) - shares) > 1e-9:
                raise AssertionError('marked end position differs')
            virtual_fee = shares * float(last_exec['price']) * (rules.sell_cost if side > 0 else rules.buy_cost)
        elif shares:
            raise AssertionError('closed position retains shares')
        if abs(sum(years.values()) - (t['pnl'] + virtual_fee)) > 1e-8:
            raise AssertionError('trade contribution does not reconcile ' + str(k))
        out[k] = {'key': list(k), 'exit': t['exit'], 'why': t['why'], 'by_year': dict(years),
                  'pnl': t['pnl'], 'virtual_end_fee': virtual_fee, 'executions': t['executions']}
    return out, per_day


def summarize(curve, dates, first, last, per_day, recorded_margin):
    delta = np.diff(np.r_[1.0, curve])
    finance = delta - per_day[first:last + 1]
    if np.max(finance) > 1e-9 or abs(-sum(finance) - recorded_margin) > 1e-8:
        raise AssertionError('daily financing does not reconcile')
    return finance


def main():
    root = du.REPORTS
    gx_path = root / 'strong_continue_gx.json'
    gx_ref = json.loads(gx_path.read_text())
    if gx_ref['script_sha256'] != sha(Path(gx.__file__)) or gx_ref['system_sha256'] != sha(Path(system.__file__)):
        raise ValueError('GX reference source differs')
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
    do_path, dp_path = root / 'strong_continue_do.json', root / 'strong_continue_dp.json'
    do, previous = json.loads(do_path.read_text()), json.loads(dp_path.read_text())
    if do['dataset_digest'] != data_digest or previous['dataset_digest'] != data_digest or previous['reference_sha256'] != sha(do_path):
        raise ValueError('DO / DP data or reference differs')
    source_root = Path(__file__).resolve().parents[2]
    for ref in (do, previous):
        for path, expected_hash in ref['code_sha256'].items():
            if path != 'studies/trader_replication/system.py' and sha(source_root / path) != expected_hash:
                raise ValueError('short source differs: ' + path)
    sc = d.cfg.get('short', {})
    if (sc.get('setups'), sc.get('pool'), sc.get('gate'), sc.get('max_new')) != (['Z15'], 'U7', 'below50', 1):
        raise ValueError('short configuration differs')
    short_books, order_audits, precision = {}, {}, {}
    for original in ('DO0', 'DO1'):
        book, audit = dp.orders_from_saved(d.A, d.days, do['preselected_orders'][original], sc, True)
        if audit != previous['orders'][original + '_open']:
            raise AssertionError('DP short orders differ: ' + original)
        marketable = {(r['day'], r['code']) for r in audit if r['status'] == 'marketable_open'}
        short_books[original] = [[e for e in row if (d.days[i], str(d.A['codes'][e[1]])) in marketable]
                                 for i, row in enumerate(book)]
        order_audits[original] = audit
        precision[original] = {'open_limit': [r for r in audit if r['open'] is not None and
            np.float32(r['open']) == np.float32(r['level'])],
            'high_stop': [{'day': d.days[i], 'code': str(d.A['codes'][e[1]]),
                           'high': float(d.A['high'][i, e[1]]), 'stop': float(e[4])}
                          for i, row in enumerate(short_books[original]) for e in row
                          if np.float32(d.A['high'][i, e[1]]) == np.float32(e[4])]}
    actual_short = [t for t in d.base.trades() if t.side == 'short' and t.dated and
                    ledger.market(t.ticker) == 'us' and panels.WINDOW[0] <= t.entry_date <= panels.WINDOW[1]]
    located, missing = fidelity.locate(actual_short, d.A['days'], d.A['codes'], prefix='US.', has=d.A['has'])
    ledger_rows = [{'id': t.id, 'ticker': t.ticker, 'entry_date': t.entry_date,
                    'window_lo': d.days[a], 'window_hi': d.days[b], 'precision': t.precision}
                   for t, j, a, b in located]
    del do, previous
    gc.collect()
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
    lever = f1_rules(d, 6, (1, 3))
    lever = replace(lever, intraday_kinds=tuple(lever.intraday_kinds) + ('list', 'n1'),
                    trail_next_open=True, add_next_open=True, no_rebuy_day=True)
    if lever.nft_days or lever.short_exit_signal or lever.gross_close:
        raise AssertionError('short close execution has an unverified condition')
    mg = dict(lever.management_by_kind)
    if 's_Z15' not in mg:
        raise AssertionError('original short management missing')
    mg['s_Z50'] = dict(mg['s_Z15'])
    candidate = replace(lever, management_by_kind=mg, short_trim_day=0, short_trim_day_frac=0.0,
                        intraday_kinds=tuple(lever.intraday_kinds) + ('s_Z15', 's_Z50'))
    if any(mg[k].get('trail_next_open', True) is False for k in ('s_Z15', 's_Z50')):
        raise AssertionError('short trail uses same close')
    cases = []
    for hit, suffix in ((None, 'original'), (True, 'hit'), (False, 'nohit')):
        long_book = old_book if hit is None else gv.sensitive_book(old_book, d.days, d.A['codes'], keys, hit)[0]
        cases.append(('L0:' + suffix, long_book, lever))
        for name in ('DO0', 'DO1'):
            cases.append((name + ':' + suffix, shorts.combine(long_book, short_books[name]), candidate))
    results, accounts = {}, {}
    first = int(np.searchsorted(d.A['days'], panels.WINDOW[0]))
    last = int(np.searchsorted(d.A['days'], panels.WINDOW[1], side='right')) - 1
    for name, book, rules in cases:
        print('account', name, flush=True)
        result = fo.account(d, book, rules)
        if result != gx_ref['results'][name]:
            raise AssertionError('GX account differs: ' + name)
        results[name] = result['trades_digest']
        if name.endswith(':original'):
            continue
        px, ema, track = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules), {}
        curve, dates, trades = system.simulate(px, ema, rules, book, *panels.WINDOW, audit=True, track=track)
        if digest(trades) != result['trades_digest']:
            raise AssertionError('trade audit differs')
        contrib, per_day = trade_contributions(trades, d.A['days'], d.A['codes'], d.A['close'], rules, first, last)
        finance = summarize(curve, dates, first, last, per_day, track['margin'])
        accounts[name] = {'trades': contrib, 'curve': curve, 'finance': finance, 'dates': dates,
                          'executions': [(e['time'], t['code'], t['kind'], t['entry'], e['action'],
                                          e['price'], e['shares']) for t in trades for e in t['executions']
                                         if e['action'] != 'end'],
                          'short_entries': sorted(t['entry'] for t in trades if t['side'] < 0)}
    comparisons = {}
    for suffix in ('hit', 'nohit'):
        baseline = accounts['L0:' + suffix]
        for variant in ('DO0', 'DO1'):
            name = variant + ':' + suffix
            current = accounts[name]
            if not np.array_equal(baseline['dates'], current['dates']):
                raise AssertionError('account calendars differ')
            first_short = current['short_entries'][0]
            before = np.array([str(x) < first_short for x in current['dates']])
            if not np.allclose(baseline['curve'][before], current['curve'][before], rtol=0, atol=1e-12):
                raise AssertionError('equity differs before first short')
            prior = lambda a: sorted(e for e in a['executions'] if e[0] < first_short)
            if prior(baseline) != prior(current):
                raise AssertionError('executions differ before first short')
            base_trades, new_trades = baseline['trades'], current['trades']
            base_long = {k for k in base_trades if k[1] > 0}
            new_long = {k for k in new_trades if k[1] > 0}
            common, removed, added = base_long & new_long, base_long - new_long, new_long - base_long
            short = {k for k in new_trades if k[1] < 0}
            if any(k[1] < 0 for k in base_trades):
                raise AssertionError('baseline has short positions')
            years, yearly_trades = {}, []
            for y in ('2024', '2025', '2026'):
                idx = [i for i, date in enumerate(current['dates']) if str(date).startswith(y)]
                if not idx:
                    raise AssertionError('missing year')
                a, b = idx[0], idx[-1]
                base0 = float(baseline['curve'][a - 1]) if a else 1.0
                new0 = float(current['curve'][a - 1]) if a else 1.0
                db = float(baseline['curve'][b] - base0)
                dn = float(current['curve'][b] - new0)
                amount = lambda tr, ks: sum(tr[k]['by_year'].get(y, 0.0) for k in ks)
                parts = {
                    'common_long': amount(new_trades, common) - amount(base_trades, common),
                    'removed_long': -amount(base_trades, removed),
                    'added_long': amount(new_trades, added),
                    'short': amount(new_trades, short),
                    'financing': float(sum(current['finance'][a:b + 1]) - sum(baseline['finance'][a:b + 1])),
                }
                if abs(sum(parts.values()) - (dn - db)) > 1e-8:
                    raise AssertionError('annual contribution does not reconcile')
                normalized = {k: v / base0 for k, v in parts.items()}
                denominator = dn * (1 / new0 - 1 / base0)
                roi_delta = dn / new0 - db / base0
                if abs(sum(normalized.values()) + denominator - roi_delta) > 1e-10:
                    raise AssertionError('annual return difference does not reconcile')
                years[y] = {'base_start': base0, 'candidate_start': new0, 'baseline_return': db / base0,
                            'candidate_return': dn / new0, 'difference': roi_delta,
                            'parts_equity_units': parts, 'parts_over_baseline_start': normalized,
                            'denominator_effect': denominator,
                            'entry_counts': {'common': sum(k[3].startswith(y) for k in common),
                                             'removed': sum(k[3].startswith(y) for k in removed),
                                             'added': sum(k[3].startswith(y) for k in added),
                                             'short': sum(k[3].startswith(y) for k in short)}}
            for group, account, ks in (('common_baseline', base_trades, common), ('common_candidate', new_trades, common),
                                       ('removed', base_trades, removed), ('added', new_trades, added),
                                       ('short', new_trades, short)):
                for k in sorted(ks):
                    yearly_trades.append({'group': group, **account[k]})
            comparisons[name] = {'first_short': first_short, 'pre_short_dates_checked': int(before.sum()),
                                 'years': years, 'trades': yearly_trades}
    out = {'dataset_digest': data_digest, 'gx_sha256': sha(gx_path), 'system_sha256': sha(Path(system.__file__)),
           'script_sha256': sha(Path(__file__)), 'account_digests': results, 'comparisons': comparisons}
    target = root / 'strong_continue_gy.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False,
                                 default=json_default) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
