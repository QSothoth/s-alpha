"""GZ: freeze closed-trade feedback before the opening batch."""
from collections import Counter
from dataclasses import replace
import gc
import json
import sys
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trader_replication import panels, system, shorts, ledger, fidelity
from studies.trader_replication import martin_continue_dp as dp
from studies.trader_replication import martin_continue_dc as dc
from studies.trader_replication import martin_continue_gx as gx
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



def risk_tier(rules, score):
    if score is not None and score < 0:
        return 'low'
    if score is not None and score > 0 and rules.risk_high > 0:
        return 'high'
    return 'normal'


def feedback_trace(d, book, rules, expected_digest):
    if not rules.feedback or rules.feedback_opened:
        raise ValueError('expected closed-trade feedback')
    records = []
    source = Path(system.__file__).resolve()

    def local(frame, event, arg):
        if event != 'return' or not arg:
            return local
        v = frame.f_locals
        if not v['early']:
            raise AssertionError('non-opening entry in fixed book')
        day = str(d.days[v['d']])
        closed = v['trades']
        now_tail = closed[-rules.feedback:] if len(closed) >= rules.feedback else []
        prev = [t for t in closed if t['exit'] < day]
        prev_tail = prev[-rules.feedback:] if len(prev) >= rules.feedback else []
        at_open = [t for t in closed if t['exit'] == day]
        if any(t['why'] not in ('gap_stop', 'trail_open') for t in at_open):
            raise AssertionError('unexpected current-day closure before opening')
        prev_score = sum(t['r'] for t in prev_tail) if prev_tail else None
        current_score = sum(t['r'] for t in now_tail) if now_tail else None
        expected = prev_score if rules.feedback_prior_close else current_score
        actual = v['recent']
        if (expected is None) != (actual is None) or (expected is not None and abs(expected - actual) > 1e-12):
            raise AssertionError('feedback timing differs')
        q = v['pos'][v['j']]
        records.append({'day': day, 'code': str(d.A['codes'][v['j']]), 'kind': v['kind'],
                        'side': int(v['side']), 'opening_exit_count': len(at_open),
                        'same_day_in_tail': sum(t['exit'] == day for t in now_tail),
                        'prior_score': prev_score, 'current_score': current_score,
                        'prior_tier': risk_tier(rules, prev_score), 'current_tier': risk_tier(rules, current_score),
                        'applied_tier': risk_tier(rules, actual), 'shares': float(q.size0),
                        'entry_equity': float(v['equity']), 'fill': float(v['fill']), 'stop': float(v['stop']),
                        'closing_keys': [[t['code'], t['kind'], t['entry'], t['exit'], t['why'], t['r']]
                                         for t in now_tail]})
        return local

    def dispatch(frame, event, arg):
        if event == 'call' and frame.f_code.co_name == 'open_pos' and Path(frame.f_code.co_filename).resolve() == source:
            return local
        return None

    px, ema = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules)
    try:
        sys.settrace(dispatch)
        _, _, trades = system.simulate(px, ema, rules, book, *panels.WINDOW, audit=True)
    finally:
        sys.settrace(None)
    if digest(trades) != expected_digest:
        raise AssertionError('tracing changed account')
    if sorted((r['day'], r['code'], r['kind']) for r in records) != sorted(
            (t['entry'], t['code'], t['kind']) for t in trades):
        raise AssertionError('traced entry set differs')
    years = {}
    for year in ('2024', '2025', '2026'):
        sample = [r for r in records if r['day'].startswith(year)]
        years[year] = {'entries': len(sample), 'opening_exit_before_entry': sum(bool(r['opening_exit_count']) for r in sample),
                       'same_day_in_feedback': sum(bool(r['same_day_in_tail']) for r in sample),
                       'risk_tier_differs': sum(r['prior_tier'] != r['current_tier'] for r in sample),
                       'transitions': dict(Counter(r['prior_tier'] + '->' + r['current_tier'] for r in sample
                                                   if r['prior_tier'] != r['current_tier']))}
    return {'years': years, 'entries': records}, trades


def main():
    root = du.REPORTS
    old_engine = root / 'source_pins/system_pre_gz.py.txt'
    gx_path = root / 'strong_continue_gx.json'
    gx_ref = json.loads(gx_path.read_text())
    if gx_ref['script_sha256'] != sha(Path(gx.__file__)) or gx_ref['system_sha256'] != sha(old_engine):
        raise ValueError('GX / prior engine differs')
    ref_path = root / 'strong_continue_gi.json'
    ref = json.loads(ref_path.read_text())
    if ref['script_sha256'] != sha(Path(gi.__file__)) or ref['system_sha256'] != sha(old_engine):
        raise ValueError('GI source or engine differs')
    dataset = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    data_digest = dataset.digest()
    if data_digest != ref['dataset_digest']:
        raise ValueError('dataset differs')
    gu_path = root / 'strong_continue_gu.json'
    base = json.loads(gu_path.read_text())
    if (base['script_sha256'] != sha(Path(gu.__file__)) or base['gi_sha256'] != sha(ref_path) or
            base['dataset_digest'] != data_digest or base['system_sha256'] != sha(old_engine)):
        raise ValueError('GU source or dataset differs')
    expected = base['results']
    expected_low, expected_open = base['low_precision_unknown'], base['old_open_precision_unknown']
    del base
    gv_path = root / 'strong_continue_gv.json'
    sensitivity = json.loads(gv_path.read_text())
    if (sensitivity['script_sha256'] != sha(Path(gv.__file__)) or sensitivity['gu_sha256'] != sha(gu_path) or
            sensitivity['dataset_digest'] != data_digest or sensitivity['system_sha256'] != sha(old_engine) or
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
    for hit, suffix in ((True, 'hit'), (False, 'nohit')):
        long_book = gv.sensitive_book(old_book, d.days, d.A['codes'], keys, hit)[0]
        for name, book, rules in (('L0', long_book, lever),
                                  ('DO0', shorts.combine(long_book, short_books['DO0']), candidate),
                                  ('DO1', shorts.combine(long_book, short_books['DO1']), candidate)):
            cases.append((name + ':' + suffix + ':old', book, rules))
            cases.append((name + ':' + suffix + ':prior', book, replace(rules, feedback_prior_close=True)))
    results, traces, checks = {}, {}, {}
    for name, book, rules in cases:
        print('account', name, flush=True)
        result = fo.account(d, book, rules)
        prior_name = name.rsplit(':', 1)[0]
        if name.endswith(':old') and result != gx_ref['results'][prior_name]:
            raise AssertionError('prior GX account differs: ' + name)
        trace, trades = feedback_trace(d, book, rules, result['trades_digest'])
        gi.assert_no_same_day_rebuy(trades)
        signal = fc.signal_audit(d, trades)
        short_trades = [t for t in trades if t['side'] < 0]
        if any(t['why'] in ('day_trim', 'signal', 'no_follow') for t in short_trades):
            raise AssertionError('unverified short close execution')
        hits = [{'id': row['id'], 'ticker': row['ticker'], 'entry_date': row['entry_date'],
                 'model_entries': [t['entry'] for t in short_trades if t['code'] == 'US.' + row['ticker']
                                   and row['window_lo'] <= t['entry'] <= row['window_hi']]}
                for row in ledger_rows]
        results[name], traces[name] = result, trace
        checks[name] = {'trail_audit': signal, 'short_by_year': {y: dc.account_summary(trades, y)
                        for y in ('2024', '2025', '2026')}, 'short_ledger': hits}
    out = {'dataset_digest': data_digest, 'gx_sha256': sha(gx_path), 'old_engine_sha256': sha(old_engine),
           'system_sha256': sha(Path(system.__file__)), 'script_sha256': sha(Path(__file__)),
           'short_config': sc, 'short_precision': precision, 'missing_ledger_ids': missing,
           'located_ledger': ledger_rows, 'results': results, 'feedback_traces': traces, 'checks': checks}
    target = root / 'strong_continue_gz.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False,
                                 default=json_default) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
