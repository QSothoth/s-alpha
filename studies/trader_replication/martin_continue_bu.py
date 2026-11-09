"""BU: attribute original U1 list entries to their exact daily trigger types."""
from collections import Counter
import gc
import hashlib
import json
from pathlib import Path

import numpy as np

from . import panels, system, ticket_t4, watchlist
from .martin_continue_a import required_fields
from .martin_continue_bq import _ROLL_MEAN, activity_ranks, chunked_roll_mean
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, name_score, u1_entries

GROUPS = ('pullback_only', 'breakout_only', 'both')


def trigger(pullback, breakout):
    if pullback and breakout:
        return 'both'
    if pullback:
        return 'pullback_only'
    if breakout:
        return 'breakout_only'
    raise ValueError('list entry satisfies neither original trigger')


def describe(rows):
    closed = [t for t in rows if t['why'] != 'end']
    opened = [t for t in rows if t['why'] == 'end']
    ret = np.array([t['ret'] for t in closed], dtype=float)
    invested_ret = np.array([t['ret_invested'] for t in closed], dtype=float)
    def basis(values):
        win, loss = values[values > 0], values[values < 0]
        aw = float(win.mean()) if len(win) else None
        al = float(loss.mean()) if len(loss) else None
        return {'win': len(win) / len(values) if len(values) else None,
                'avg_win': aw, 'avg_loss': al,
                'payoff': aw / -al if aw is not None and al is not None else None,
                'mean': float(values.mean()) if len(values) else None}
    invested = sum(e['price'] * e['shares'] for t in closed for e in t['executions']
                   if e['action'] in ('entry', 'add'))
    return {'entries': len(rows), 'closed': len(closed), 'open_at_end': len(opened),
            'initial_basis': basis(ret), 'invested_basis': basis(invested_ret),
            'weighted_invested': sum(t['pnl'] for t in closed) / invested if invested else None,
            'initial_above_30pct': int(np.sum(ret >= .30)),
            'median_stop_width': float(np.median([t['risk_pct'] for t in rows])) if rows else None,
            'closed_pnl': float(sum(t['pnl'] for t in closed)),
            'open_mark_pnl': float(sum(t['pnl'] for t in opened)),
            'exit_reasons': dict(Counter(t['why'] for t in closed))}


def coverage(D, rows):
    result = {y: {g: 0 for g in GROUPS} | {'windows': 0} for y in ('2024', '2025', '2026')}
    for day, j, _, _, date in D.big:
        peak = day + 1 + int(np.nanargmax(D.h[day + 1:day + 21, j]))
        end = min(day + 10, peak - 1)
        year = date[:4]
        result[year]['windows'] += 1
        code = str(D.A['codes'][j])
        for group in GROUPS:
            result[year][group] += int(any(t['code'] == code and D.di[t['entry']] <= end and
                                          D.di[t['exit']] >= day for t in rows[group]))
    return result


def main():
    original = ticket_t4.ranks
    try:
        ticket_t4.ranks = activity_ranks
        D = Data()
    finally:
        ticket_t4.ranks = original
    del D.fp, D.fwd, D.raw
    for key in ('pr21', 'pr63', 'pr126', 'rank_pool', 'stack', 'tight'):
        D.A.pop(key, None)
    D.rk = D.rk.astype(np.int32)
    gc.collect()
    try:
        watchlist.roll_mean = chunked_roll_mean
        F = required_fields(D)
    finally:
        watchlist.roll_mean = _ROLL_MEAN
    mask = active(D, F)
    score = name_score(D, F, mask, HOLD['H3'])
    holding = hold_sim(score, 12, 36)
    book = u1_entries(D, F, holding, score)
    lookup = {}
    counts = {y: {g: {'total': 0, 'stop_le_3pct': 0} for g in GROUPS} for y in ('2024', '2025', '2026')}
    for day, row in enumerate(book):
        if not panels.WINDOW[0] <= D.days[day] <= panels.WINDOW[1]:
            continue
        for e in row:
            if e[5] != 'list':
                continue
            j = e[1]
            pullback = F['lowe9'][day, j] <= .1 and D.c[day, j] > D.e9[day, j]
            breakout = D.c[day, j] > D.h[day - 1, j] and F['cpos'][day, j] >= .5
            group = trigger(pullback, breakout)
            k = D.days[day], str(D.A['codes'][j])
            if k in lookup:
                raise ValueError('duplicate list signal identity')
            lookup[k] = group
            rec = counts[D.days[day][:4]][group]
            rec['total'] += 1
            rec['stop_le_3pct'] += int(1 - e[4] / e[3] <= .03 + 1e-12)
    del F, mask, score, holding
    gc.collect()
    ru = f1_rules(D, 6, (1, 3))
    curve, dates, trades = system.simulate(D.base.px(D.A), D.base.ema_inputs(D.A, D.pool, ru),
                                           ru, book, *panels.WINDOW, audit=True)
    root = Path(__file__).resolve().parents[2]
    previous = json.loads((root / 'studies/trader_replication/reports/gap_review/strong_continue_bt.json').read_text())
    years = system.stats(curve, dates, trades)['by_year']
    for year in years:
        if abs(years[year] - previous['results']['U1']['metrics']['by_year'][year]) > 1e-10:
            raise AssertionError(f'U1 {year} account does not match BT')
    grouped = {g: [] for g in GROUPS}
    for t in trades:
        if t['kind'] == 'list':
            grouped[lookup[(t['entry'], t['code'])]].append(t)
    result = {}
    for year in ('2024', '2025', '2026'):
        result[year] = {g: describe([t for t in grouped[g] if t['entry'].startswith(year)]) for g in GROUPS}
    paths = ('studies/trader_replication/martin_continue_bu.py', 'studies/trader_replication/martin_continue_a.py',
             'studies/trader_replication/martin_continue_bq.py', 'studies/trader_replication/martin_strong.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/trader_replication/system.py')
    out = {'dataset_digest': D.A['digest'], 'account_years': years, 'candidates': counts,
           'trades_by_entry_year': result, 'prepeak_ten_day': coverage(D, grouped),
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}}
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_bu.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), flush=True)


if __name__ == '__main__':
    main()
