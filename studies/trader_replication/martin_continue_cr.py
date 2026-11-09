"""CR: pair existing U1 positions with all same-side CORE-only signals."""
from collections import Counter
import gc
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from . import compare, panels, system, ticket_t4, watchlist
from .martin_continue_a import required_fields
from .martin_continue_b_check import digest
from .martin_continue_bq import _ROLL_MEAN, activity_ranks, chunked_roll_mean
from .martin_continue_bs import key_trades
from .martin_continue_bu import describe
from .martin_continue_bv import daily_name_score, daily_pool_book
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, merge, sized


def close_path(trade, days, close, buy_cost, sell_cost):
    """Rebuild closed long's end-of-session PnL; no account financing."""
    if trade['side'] != 1 or trade['why'] == 'end':
        raise ValueError('close_path requires an actually closed long position')
    positions = {d: i for i, d in enumerate(days)}
    start, end = positions[trade['entry']], positions[trade['exit']]
    executions = trade['executions']
    cash = shares = invested = 0.0
    cursor, observations, missing = 0, [], 0
    for d in range(start, end + 1):
        while cursor < len(executions) and executions[cursor]['time'] == days[d]:
            e = executions[cursor]
            value = e['price'] * e['shares']
            if e['action'] in ('entry', 'add'):
                shares += e['shares']
                invested += value
                cash -= value * (1 + buy_cost)
            elif e['action'] == 'end':
                raise ValueError('end marker cannot appear for a closed position')
            else:
                shares -= e['shares']
                cash += value * (1 - sell_cost)
            cursor += 1
        if invested <= 0:
            raise AssertionError('entry is missing')
        if abs(shares) < 1e-12:
            shares = 0.0
            observations.append((days[d], cash / invested))
        elif np.isfinite(close[d]) and close[d] > 0:
            observations.append((days[d], (cash + shares * close[d]) / invested))
        else:
            missing += 1
    if cursor != len(executions) or shares != 0:
        raise AssertionError('execution records do not close on the recorded exit date')
    if abs(cash / invested - trade['ret_invested']) > 1e-9:
        raise AssertionError('reconstructed invested return differs from the engine')
    if not observations:
        return {'peak_date': None, 'peak_return': None, 'peak_minus_final': None, 'missing_days': missing}
    peak_day, peak = max(observations, key=lambda item: item[1])
    return {'peak_date': peak_day, 'peak_return': float(peak),
            'peak_minus_final': float(peak - trade['ret_invested']), 'missing_days': missing}


def json_default(value):
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f'unsupported JSON value: {type(value).__name__}')


def trade_view(t):
    e = t['executions']
    return {'entry': t['entry'], 'exit': t['exit'], 'kind': t['kind'], 'why': t['why'],
            'fill': t['fill'], 'initial_stop': t['stop'], 'days': t['days'],
            'ret_initial': t['ret'], 'ret_invested': t['ret_invested'],
            'adds': sum(x['action'] == 'add' for x in e), 'trims': sum(x['action'] == 'trim' for x in e)}


def summarize_positions(trades, paths):
    closed = [t for t in trades if t['why'] != 'end']
    ds = [paths[(t['entry'], t['code'], t['side'], t['kind'])]['peak_minus_final'] for t in closed]
    peaks = [paths[(t['entry'], t['code'], t['side'], t['kind'])]['peak_return'] for t in closed]
    gaps = [v for v in ds if v is not None]
    available = [v for v in peaks if v is not None]
    return {'positions': describe(trades), 'median_days_closed': float(np.median([t['days'] for t in closed])) if closed else None,
            'added_positions': sum(any(e['action'] == 'add' for e in t['executions']) for t in trades),
            'closed_reasons': dict(Counter(t['why'] for t in closed)),
            'median_peak_day_return': float(np.median(available)) if available else None,
            'median_peak_minus_final': float(np.median(gaps)) if gaps else None,
            'maximum_peak_minus_final': float(max(gaps)) if gaps else None,
            'closed_with_missing_price_days': sum(paths[(t['entry'], t['code'], t['side'], t['kind'])]['missing_days'] > 0 for t in closed)}


def main():
    if os.environ.get('TRADER_DATA_MODE') != 'frozen' or os.environ.get('TRADER_DATA_TAG') != 'trader-data-v1':
        raise ValueError('explicitly select the registered frozen v1 dataset')
    root = Path(__file__).resolve().parents[2]
    old = ticket_t4.ranks
    try:
        ticket_t4.ranks = activity_ranks
        D = Data()
    finally:
        ticket_t4.ranks = old
    pin = json.loads((root / 'studies/trader_replication/DATA_PIN.json').read_text())['trader-data-v1']['us']
    if D.A['digest'] != pin:
        raise ValueError('dataset digest differs from registered v1')
    del D.fp, D.fwd, D.raw
    for key in ('pr21', 'pr63', 'pr126', 'rank_pool', 'stack', 'tight'):
        D.A.pop(key, None)
    D.rk = D.rk.astype(np.int32)
    gc.collect()
    try:
        watchlist.roll_mean = chunked_roll_mean
        fields = required_fields(D)
    finally:
        watchlist.roll_mean = _ROLL_MEAN
    mask = active(D, fields)
    score = daily_name_score(fields, mask, HOLD['H3'])
    holding = hold_sim(score, 12, 36)
    raw = daily_pool_book(D, fields, holding, score)
    book = merge(D.reg, sized(raw, .5))
    del fields, mask, score, holding, raw
    gc.collect()
    rules = f1_rules(D, 6, (1, 3))
    px, ema = D.base.px(D.A), D.base.ema_inputs(D.A, D.pool, rules)
    report_root = root / 'studies/trader_replication/reports/gap_review'
    cp_path, cq_path = (report_root / name for name in ('strong_continue_cp.json', 'strong_continue_cq.json'))
    cp, cq = (json.loads(p.read_text()) for p in (cp_path, cq_path))
    if cp['dataset_digest'] != D.A['digest'] or cq['dataset_digest'] != D.A['digest']:
        raise ValueError('CP or CQ reference data differs')
    histories = {}
    lo, hi = (int(np.searchsorted(D.A['days'], d, side=side)) for d, side in ((panels.WINDOW[0], 'left'), (panels.WINDOW[1], 'right')))
    for name, entries in (('CORE', D.reg), ('U1', book)):
        print('account', name, flush=True)
        curve, dates, trades = system.simulate(px, ema, rules, entries, *panels.WINDOW, audit=True)
        metrics = compare.metrics(curve, dates, trades, entries, lo, hi)
        for year in ('2024', '2025', '2026'):
            if (abs(metrics['by_year'][year] - cp['accounts'][name]['metrics']['by_year'][year]) > 1e-10 or
                sum(t['entry'].startswith(year) for t in trades) != cp['accounts'][name]['metrics']['entries_by_year'][year]):
                raise AssertionError(name + ' ' + year + ' differs from CP')
        histories[name] = key_trades(trades)
        if name == 'U1' and digest(trades) != cq['u1_trades_digest']:
            raise AssertionError('U1 full trade path differs from CQ')
    core, u1 = histories['CORE'], histories['U1']
    all_targets = [r for r in cq['records'] if r['category'] == 'held_same_side']
    if len(all_targets) != 154:
        raise AssertionError('same-side targets differ from CQ')
    code_index = {str(c): j for j, c in enumerate(D.A['codes'])}
    paths, pairs = {}, []
    for r in all_targets:
        ck = (r['entry'], r['code'], r['side'], r['kind'])
        event = r['events'][0]
        uk = (event['held_entry'], r['code'], event['held_side'], event['held_kind'])
        ct, ut = core[ck], u1[uk]
        if not (ut['entry'] < r['entry'] <= ut['exit'] and ut['side'] == ct['side'] == 1):
            raise AssertionError('linked U1 position did not overlap the CORE signal')
        old_trade = r['core_trade']
        if any(abs(ct[key] - old_trade[key]) > 1e-10 for key in ('ret', 'ret_invested', 'pnl')) or ct['why'] != old_trade['why']:
            raise AssertionError('CORE trade differs from CQ')
        if uk not in paths:
            paths[uk] = None if ut['why'] == 'end' else close_path(ut, D.days, D.A['close'][:, code_index[ut['code']]], rules.buy_cost, rules.sell_cost)
        pairs.append({'signal': r['entry'], 'code': r['code'], 'core_key': list(ck), 'u1_key': list(uk),
                      'core': trade_view(ct), 'u1': trade_view(ut), 'u1_close_path': paths[uk]})
    years = {}
    for year in ('2024', '2025', '2026', 'all'):
        sample = [p for p in pairs if year == 'all' or p['signal'].startswith(year)]
        ck = {tuple(p['core_key']) for p in sample}
        uk = {tuple(p['u1_key']) for p in sample}
        core_rows, u1_rows = [core[k] for k in ck], [u1[k] for k in uk]
        events_core_winners = [p for p in sample if p['core']['why'] != 'end' and p['core']['ret_initial'] >= .30]
        years[year] = {'events': len(sample), 'unique_core': len(ck), 'unique_u1': len(uk),
                       'core': describe(core_rows), 'u1': summarize_positions(u1_rows, paths),
                       'core_initial_ge_30_events': len(events_core_winners),
                       'core_ge_30_u1_final_wins': sum(p['u1']['why'] != 'end' and p['u1']['ret_invested'] > 0 for p in events_core_winners),
                       'core_ge_30_u1_final_losses': sum(p['u1']['why'] != 'end' and p['u1']['ret_invested'] < 0 for p in events_core_winners),
                       'core_ge_30_u1_end': sum(p['u1']['why'] == 'end' for p in events_core_winners)}
    paths_to_pin = ('studies/trader_replication/martin_continue_cr.py', 'studies/trader_replication/martin_continue_cq.py',
                    'studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_bq.py',
                    'studies/trader_replication/martin_continue_bs.py', 'studies/trader_replication/martin_continue_bu.py',
                    'studies/trader_replication/martin_continue_bv.py', 'studies/trader_replication/system.py')
    out = {'dataset_digest': D.A['digest'], 'window': list(panels.WINDOW), 'years': years, 'pairs': pairs,
           'reference_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (cp_path, cq_path)},
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths_to_pin}}
    target = report_root / 'strong_continue_cr.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False, default=json_default) + '\n', encoding='utf-8')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
