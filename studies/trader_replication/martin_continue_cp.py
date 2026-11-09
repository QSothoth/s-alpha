"""CP: reconcile actual paths of the registered, core, and satellite accounts."""
from dataclasses import fields as dataclass_fields
import gc
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from . import compare, panels, system, ticket_t4, watchlist
from .martin_continue_a import required_fields
from .martin_continue_bq import _ROLL_MEAN, activity_ranks, chunked_roll_mean
from .martin_continue_bs import key_trades
from .martin_continue_bu import describe
from .martin_continue_bv import daily_name_score, daily_pool_book
from .martin_continue_ci import plain
from .martin_continue_bt import fidelity
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, longs, merge, nl_rules, sized


def rule_value(x):
    if isinstance(x, np.ndarray):
        return {'shape': list(x.shape), 'dtype': str(x.dtype), 'sha256': hashlib.sha256(x.tobytes()).hexdigest()}
    if isinstance(x, dict):
        return {str(k): rule_value(v) for k, v in x.items()}
    if isinstance(x, (tuple, list)):
        return [rule_value(v) for v in x]
    if isinstance(x, np.generic):
        return x.item()
    if isinstance(x, (str, int, float, bool)) or x is None:
        return x
    raise TypeError(f'unsupported rule value: {type(x).__name__}')


def rule_differences(left, right):
    out = {}
    for f in dataclass_fields(left):
        a, b = rule_value(getattr(left, f.name)), rule_value(getattr(right, f.name))
        if a != b:
            out[f.name] = {'R74': a, 'CORE_U1': b}
    return out


def pair_groups(left, right, left_equity, right_equity):
    a, b = key_trades(left), key_trades(right)
    common = a.keys() & b.keys()
    groups = {'left_common': (a, common, left_equity), 'right_common': (b, common, right_equity),
              'left_only': (a, a.keys() - b.keys(), left_equity), 'right_only': (b, b.keys() - a.keys(), right_equity)}
    result = {}
    for year in ('2024', '2025', '2026'):
        result[year] = {}
        for label, (source, keys, equity) in groups.items():
            trades = [source[k] for k in sorted(keys) if k[0].startswith(year)]
            result[year][label] = {}
            for kind in ('list', 'other'):
                rows = [t for t in trades if (t['kind'] == 'list') == (kind == 'list')]
                info = describe(rows)
                closed = [t for t in rows if t['why'] != 'end']
                weights = [t['executions'][0]['price'] * t['executions'][0]['shares'] / equity[t['entry']]
                           for t in rows if equity[t['entry']] > 0]
                info['median_entry_vs_prior_close_equity'] = float(np.median(weights)) if weights else None
                info['median_days_closed'] = float(np.median([t['days'] for t in closed])) if closed else None
                result[year][label][kind] = info
        for label, source in (('left', a), ('right', b)):
            rows = [t for t in source.values() if t['entry'].startswith(year)]
            parts = [result[year][label + suffix][kind] for suffix in ('_common', '_only') for kind in ('list', 'other')]
            if sum(x['entries'] for x in parts) != len(rows):
                raise AssertionError('pair counts do not reconcile')
            if abs(sum(x['closed_pnl'] + x['open_mark_pnl'] for x in parts) - sum(t['pnl'] for t in rows)) > 1e-8:
                raise AssertionError('pair PnL does not reconcile')
    return result


def window_records(D, reference, histories):
    codes = {str(c)[3:]: str(c) for c in D.A['codes'] if str(c).startswith('US.')}
    output = []
    for w in reference['windows']:
        code, first, last = codes[w['ticker']], D.di[w['date']], D.di[w['end']]
        accounts = {}
        for name, trades in histories.items():
            selected = [t for t in trades if t['code'] == code and t['side'] > 0 and
                        D.di[t['entry']] <= last and D.di[t['exit']] >= first]
            positions = [{'entry': t['entry'], 'exit': t['exit'], 'kind': t['kind'], 'why': t['why'],
                          'days': t['days'], 'ret': t['ret'], 'ret_invested': t['ret_invested'], 'pnl': t['pnl']}
                         for t in selected]
            accounts[name] = {'held': bool(selected), 'list': any(t['kind'] == 'list' for t in selected),
                              'other': any(t['kind'] != 'list' for t in selected), 'positions': positions}
        if accounts['U1']['held'] != (w['stage'] == 'held'):
            raise AssertionError('U1 window differs from BE: ' + w['date'] + ' ' + w['ticker'])
        output.append({'date': w['date'], 'ticker': w['ticker'], 'end': w['end'], 'accounts': accounts})
    return output


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
    u1 = merge(D.reg, sized(raw, .5))
    sat = plain(raw)
    del fields, mask, score, holding, raw
    gc.collect()
    lever, plain_rules = f1_rules(D, 6, (1, 3)), nl_rules(D, 6)
    cases = {'R74': (D.reg, D.rules), 'CORE': (D.reg, lever), 'U1': (u1, lever),
             'REG6': (longs(D.reg), plain_rules), 'SAT6': (sat, plain_rules)}
    report_root = root / 'studies/trader_replication/reports/gap_review'
    bv_path = report_root / 'strong_continue_bv_trader-data-v1.json'
    an_path, bz_path, be_path = (report_root / x for x in ('strong_continue_an.json', 'strong_continue_bz.json', 'strong_continue_be.json'))
    bv, an, bz, be = (json.loads(p.read_text()) for p in (bv_path, an_path, bz_path, be_path))
    if any(x['dataset_digest'] != D.A['digest'] for x in (bv, an, bz, be)):
        raise ValueError('reference dataset differs')
    refs = {'R74': bv['results']['R74'], 'CORE': an['results']['CORE'], 'U1': bz['results']['U1'],
            'REG6': bv['results']['REG6'], 'SAT6': bz['results']['SAT6']}
    histories, equities, result = {}, {}, {}
    px = D.base.px(D.A)
    lo, hi = (int(np.searchsorted(D.A['days'], d, side=side)) for d, side in ((panels.WINDOW[0], 'left'), (panels.WINDOW[1], 'right')))
    for name, (book, rules) in cases.items():
        print('account', name, flush=True)
        track = {}
        em = D.base.ema_inputs(D.A, D.pool, rules)
        curve, dates, trades = system.simulate(px, em, rules, book, *panels.WINDOW, audit=True, track=track)
        metrics = compare.metrics(curve, dates, trades, book, lo, hi)
        metrics['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in trades) for y in ('2024', '2025', '2026')}
        for year in ('2024', '2025', '2026'):
            if abs(metrics['by_year'][year] - refs[name]['metrics']['by_year'][year]) > 1e-10 or metrics['entries_by_year'][year] != refs[name]['metrics']['entries_by_year'][year]:
                raise AssertionError(f'{name} {year} does not match registered account')
        end_fee = sum(e['price'] * e['shares'] * (rules.sell_cost if t['side'] > 0 else rules.buy_cost)
                      for t in trades for e in t['executions'] if e['action'] == 'end')
        pnl = sum(t['pnl'] for t in trades)
        residual = float(curve[-1] - 1 - pnl)
        expected = float(-track['margin'] + end_fee)
        if abs(residual - expected) > 1e-8:
            raise AssertionError(f'{name} equity and trade PnL do not reconcile: {residual} vs {expected}')
        histories[name] = trades
        equities[name] = dict(zip(map(str, dates), map(float, np.concatenate(([1.0], curve[:-1])))))
        result[name] = {'metrics': metrics, 'fidelity': fidelity(D, trades),
                        'average_gross': float(np.mean(track['gross'])),
                        'account_reconciliation': {'equity_change': float(curve[-1] - 1), 'trade_pnl': pnl,
                            'margin': float(track['margin']), 'assumed_end_exit_fee': float(end_fee),
                            'residual': residual}}
    pairs = {}
    for a, b in (('R74', 'CORE'), ('CORE', 'U1'), ('R74', 'U1'), ('REG6', 'SAT6')):
        pairs[a + '_vs_' + b] = pair_groups(histories[a], histories[b], equities[a], equities[b])
    overlap_without_kind = {}
    for a, b in (('R74', 'CORE'), ('CORE', 'U1'), ('R74', 'U1'), ('REG6', 'SAT6')):
        overlap_without_kind[a + '_vs_' + b] = {}
        for year in ('2024', '2025', '2026'):
            left = {(t['entry'], t['code'], t['side']) for t in histories[a] if t['entry'].startswith(year)}
            right = {(t['entry'], t['code'], t['side']) for t in histories[b] if t['entry'].startswith(year)}
            overlap_without_kind[a + '_vs_' + b][year] = {'left': len(left), 'right': len(right), 'common': len(left & right)}
    windows = window_records(D, be, histories)
    window_summary = {}
    for year in ('2024', '2025', '2026', 'all'):
        subset = [w for w in windows if year == 'all' or w['date'].startswith(year)]
        window_summary[year] = {'windows': len(subset), 'accounts': {name: {k: sum(w['accounts'][name][k] for w in subset)
            for k in ('held', 'list', 'other')} for name in histories},
            'R74_and_U1': {'both': sum(w['accounts']['R74']['held'] and w['accounts']['U1']['held'] for w in subset),
                'R74_only': sum(w['accounts']['R74']['held'] and not w['accounts']['U1']['held'] for w in subset),
                'U1_only': sum(w['accounts']['U1']['held'] and not w['accounts']['R74']['held'] for w in subset),
                'neither': sum(not w['accounts']['U1']['held'] and not w['accounts']['R74']['held'] for w in subset)}}
    paths = ('studies/trader_replication/martin_continue_cp.py', 'studies/trader_replication/martin_continue_bs.py',
             'studies/trader_replication/martin_continue_bu.py', 'studies/trader_replication/martin_continue_a.py',
             'studies/trader_replication/martin_continue_bv.py', 'studies/trader_replication/martin_continue_bq.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/trader_replication/system.py',
             'studies/martin_luk/notes/trades.csv')
    out = {'dataset_digest': D.A['digest'], 'window': list(panels.WINDOW), 'accounts': result,
           'rule_differences': rule_differences(D.rules, lever), 'pairs': pairs,
           'entry_overlap_without_kind': overlap_without_kind, 'windows': windows,
           'window_summary': window_summary,
           'reference_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (bv_path, an_path, bz_path, be_path)},
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}}
    target = report_root / 'strong_continue_cp.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
