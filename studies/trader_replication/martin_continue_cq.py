"""CQ: trace U1 handling of actual CORE-only registered entries."""
from collections import Counter
import gc
import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np

from . import compare, panels, system, ticket_t4, watchlist
from .martin_continue_a import required_fields
from .martin_continue_ar import condition_lines
from .martin_continue_b_check import digest
from .martin_continue_bq import _ROLL_MEAN, activity_ranks, chunked_roll_mean
from .martin_continue_bs import key_trades
from .martin_continue_bu import describe
from .martin_continue_bv import daily_name_score, daily_pool_book
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, merge, sized


def classify(events):
    if not events:
        return 'not_reached'
    if len(events) > 1:
        return 'multiple_attempts'
    event = events[0]
    if event['reason'] == 'opened':
        return 'opened'
    if 'held_side' in event:
        return 'held_same_side' if event['held_side'] == event['side'] else 'held_opposite_side'
    if event.get('limits'):
        return 'amount_too_small:' + '+'.join(event['limits'])
    return event['reason']


def main():
    if os.environ.get('TRADER_DATA_MODE') != 'frozen' or os.environ.get('TRADER_DATA_TAG') != 'trader-data-v1':
        raise ValueError('explicitly select the registered frozen v1 dataset')
    root = Path(__file__).resolve().parents[2]
    original = ticket_t4.ranks
    try:
        ticket_t4.ranks = activity_ranks
        D = Data()
    finally:
        ticket_t4.ranks = original
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
    cp_path, be_path = (report_root / name for name in ('strong_continue_cp.json', 'strong_continue_be.json'))
    cp, be = (json.loads(p.read_text()) for p in (cp_path, be_path))
    if cp['dataset_digest'] != D.A['digest'] or be['dataset_digest'] != D.A['digest']:
        raise ValueError('CP or BE reference data differs')
    accounts = {}
    lo, hi = (int(np.searchsorted(D.A['days'], d, side=side)) for d, side in ((panels.WINDOW[0], 'left'), (panels.WINDOW[1], 'right')))
    for name, entries in (('CORE', D.reg), ('U1', book)):
        print('baseline', name, flush=True)
        curve, dates, trades = system.simulate(px, ema, rules, entries, *panels.WINDOW, audit=True)
        metrics = compare.metrics(curve, dates, trades, entries, lo, hi)
        for year in ('2024', '2025', '2026'):
            if (abs(metrics['by_year'][year] - cp['accounts'][name]['metrics']['by_year'][year]) > 1e-10 or
                sum(t['entry'].startswith(year) for t in trades) != cp['accounts'][name]['metrics']['entries_by_year'][year]):
                raise AssertionError(name + ' ' + year + ' differs from CP')
        accounts[name] = trades
    core, u1 = key_trades(accounts['CORE']), key_trades(accounts['U1'])
    target = core.keys() - u1.keys()
    for year in ('2024', '2025', '2026'):
        count = sum(k[0].startswith(year) for k in target)
        ref = sum(cp['pairs']['CORE_vs_U1'][year]['left_only'][kind]['entries'] for kind in ('list', 'other'))
        if count != ref:
            raise AssertionError('CORE-only target count differs from CP')
    codes = D.A['codes']
    source = Path(system.__file__).resolve()
    conditions = condition_lines(source)
    records = {key: [] for key in target}

    def local_trace(frame, event, arg):
        fn, loc = frame.f_code.co_name, frame.f_locals
        relevant = (fn == 'take' and event == 'line' and (fn, frame.f_lineno) in conditions)
        relevant |= fn == 'open_pos' and event == 'return'
        if not relevant or not all(k in loc for k in ('d', 'j', 'side', 'kind')):
            return local_trace
        key = (D.days[loc['d']], str(codes[loc['j']]), int(loc['side']), loc['kind'])
        if key not in target:
            return local_trace
        if fn == 'take':
            records[key].append({'reason': 'take: ' + conditions[(fn, frame.f_lineno)], 'side': key[2]})
            return local_trace
        if arg is not None:
            records[key].append({'reason': 'opened', 'side': key[2]})
            return local_trace
        reason = conditions.get((fn, frame.f_lineno), f'unknown return line {frame.f_lineno}')
        item = {'reason': 'open_pos: ' + reason, 'side': key[2]}
        held = loc.get('pos', {}).get(loc['j'])
        if held is not None:
            item.update(held_kind=held.kind, held_entry=D.days[held.d0], held_side=held.side)
        if reason == 'val <= 0.001 * equity' and loc['equity'] > 0:
            v = {'risk_budget': float(loc['frac'] / loc['width']), 'position_cap': float(loc['cap']),
                 'gross_room': float(loc['room'] / loc['equity'])}
            minimum = min(v.values())
            item['components'] = v
            item['limits'] = sorted(k for k, value in v.items() if abs(value - minimum) < 1e-12)
        records[key].append(item)
        return local_trace

    def dispatch(frame, event, arg):
        if event == 'call' and frame.f_code.co_name in ('take', 'open_pos') and Path(frame.f_code.co_filename).resolve() == source:
            return local_trace
        return None

    print('trace U1', flush=True)
    try:
        sys.settrace(dispatch)
        _, _, replay = system.simulate(px, ema, rules, book, *panels.WINDOW, audit=True)
    finally:
        sys.settrace(None)
    if digest(replay) != digest(accounts['U1']):
        raise AssertionError('U1 execution path changed while tracing')
    rows = []
    for key in sorted(target):
        t, events = core[key], records[key]
        category = classify(events)
        if category == 'opened':
            raise AssertionError('CORE-only key was unexpectedly opened by U1')
        rows.append({'entry': key[0], 'code': key[1], 'side': key[2], 'kind': key[3],
                     'category': category, 'events': events,
                     'core_trade': {'ret': t['ret'], 'ret_invested': t['ret_invested'], 'pnl': t['pnl'],
                                    'why': t['why'], 'days': t['days']}})
    years = {}
    for year in ('2024', '2025', '2026', 'all'):
        subset = [r for r in rows if year == 'all' or r['entry'].startswith(year)]
        groups = {}
        for category in sorted({r['category'] for r in subset}):
            keys = [(r['entry'], r['code'], r['side'], r['kind']) for r in subset if r['category'] == category]
            groups[category] = describe([core[k] for k in keys])
            closed = [core[k]['days'] for k in keys if core[k]['why'] != 'end']
            groups[category]['median_days_closed'] = float(np.median(closed)) if closed else None
        years[year] = {'targets': len(subset), 'groups': groups}
    windows = []
    for w in be['windows']:
        code = 'US.' + w['ticker']
        chosen = [r for r in rows if r['side'] > 0 and r['code'] == code and w['date'] <= r['entry'] <= w['end']]
        windows.append({'date': w['date'], 'ticker': w['ticker'], 'targets': len(chosen),
                        'categories': sorted({r['category'] for r in chosen}),
                        'u1_held': w['stage'] == 'held'})
    window_years = {}
    for year in ('2024', '2025', '2026', 'all'):
        subset = [w for w in windows if year == 'all' or w['date'].startswith(year)]
        counts = Counter(category for w in subset for category in w['categories'])
        window_years[year] = {'windows': len(subset), 'any_target': sum(w['targets'] > 0 for w in subset),
                              'categories': dict(counts), 'u1_held': sum(w['u1_held'] for w in subset)}
    paths = ('studies/trader_replication/martin_continue_cq.py', 'studies/trader_replication/martin_continue_ar.py',
             'studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_bq.py',
             'studies/trader_replication/martin_continue_bu.py', 'studies/trader_replication/martin_continue_bv.py',
             'studies/trader_replication/martin_continue_bs.py', 'studies/trader_replication/system.py',
             'studies/martin_luk/notes/trades.csv')
    out = {'dataset_digest': D.A['digest'], 'window': list(panels.WINDOW), 'years': years, 'records': rows,
           'windows': windows, 'window_years': window_years, 'u1_trades_digest': digest(replay),
           'reference_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (cp_path, be_path)},
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}}
    out_path = report_root / 'strong_continue_cq.json'
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('wrote', out_path, flush=True)


if __name__ == '__main__':
    main()
