"""CG: test the established fresh20 leader list outside the H3 holdings."""
import gc
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from . import panels, ticket_t4, watchlist
from .martin_continue_a import required_fields
from .martin_continue_bq import _ROLL_MEAN, activity_ranks, chunked_roll_mean
from .martin_continue_bv import daily_name_score
from .martin_list import ema
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, hold_sim


def leader_stack(close):
    stack, known = np.zeros(close.shape, dtype=bool), np.zeros(close.shape, dtype=bool)
    for start in range(0, close.shape[1], 64):
        sl = slice(start, start + 64)
        c = close[:, sl].astype(float)
        e9, e21, e50 = (ema(c, n) for n in (9, 21, 50))
        known[:, sl] = np.isfinite(c) & np.isfinite(e9) & np.isfinite(e21) & np.isfinite(e50)
        stack[:, sl] = known[:, sl] & (e9 > e21) & (e21 > e50) & (c > e21)
    return stack, known


def lagged_fresh20(stack, known):
    fresh = np.zeros(stack.shape, dtype=bool)
    fresh[21:] = stack[20:-1] & ~stack[:-21] & known[20:-1] & known[:-21]
    return fresh


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
        raise ValueError('dataset digest differs from the registered v1')
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
    del fields
    gc.collect()
    stack, known = leader_stack(D.A['close'])
    fresh = lagged_fresh20(stack, known)
    del stack, known
    codes = np.asarray(D.A['codes']).astype(str)
    selected, sizes, totals = {}, {}, {}
    for day in range(len(D.days)):
        outside = mask[day] & ~holding[day]
        names = np.flatnonzero(outside & fresh[day])
        order = np.lexsort((codes[names], -score[day, names]))
        selected[day] = names[order].tolist()
        sizes[day], totals[day] = len(names), int(outside.sum())
    prior = json.loads((root / 'studies/trader_replication/reports/gap_review/strong_continue_n.json').read_text())
    previous = {(x['day'], x['ticker']): x for x in prior['rows']}
    rows = []
    for d, j, ticker, _, day in D.his:
        if not (mask[d, j] and not holding[d, j]):
            continue
        key = (day, ticker)
        if key not in previous:
            raise AssertionError(f'H3-missed trade not in N: {key}')
        names = selected[d]
        rank = names.index(int(j)) + 1 if int(j) in names else None
        rows.append({'day': day, 'ticker': ticker, 'big': previous[key]['big'], 'rank': rank,
                     'candidate_count': sizes[d], 'outside_count': totals[d]})
    if {(x['day'], x['ticker']) for x in rows} != set(previous):
        raise AssertionError('H3-missed trade identities differ from N')
    years = {}
    for year in ('2024', '2025', '2026'):
        dates = [d for d, s in enumerate(D.days) if s.startswith(year) and panels.WINDOW[0] <= s <= panels.WINDOW[1]]
        subset = [r for r in rows if r['day'].startswith(year)]
        counts = {}
        for label, sample in (('all', subset), ('big', [r for r in subset if r['big'] is True])):
            eligible = [r for r in sample if r['rank'] is not None]
            counts[label] = {'n': len(sample), 'fresh': len(eligible),
                             'top1': sum(r['rank'] is not None and r['rank'] <= 1 for r in sample),
                             'top2': sum(r['rank'] is not None and r['rank'] <= 2 for r in sample),
                             'top4': sum(r['rank'] is not None and r['rank'] <= 4 for r in sample),
                             'random_outside_top4_expected': float(sum(min(4, r['candidate_count']) / max(1, r['outside_count']) for r in sample)),
                             'random_fresh_top4_expected': float(sum(min(4, r['candidate_count']) / r['candidate_count'] for r in eligible))}
        years[year] = {'groups': counts, 'median_daily_width': float(np.median([sizes[d] for d in dates])),
                       'mean_share_outside': float(np.mean([sizes[d] / max(1, totals[d]) for d in dates]))}
    expected = {'2024': 4, '2025': 7, '2026': 2}
    for year, count in expected.items():
        if years[year]['groups']['big']['n'] != count:
            raise AssertionError(f'{year} big-trade denominator differs from the preregistration')
    windows = []
    for d, j, _, _, day in D.big:
        peak = d + 1 + int(np.nanargmax(D.h[d + 1:d + 21, j]))
        end = min(d + 10, peak - 1)
        h3 = any(holding[t, j] for t in range(d, end + 1))
        extra = any(int(j) in selected[t][:4] for t in range(d, end + 1))
        windows.append({'day': day, 'code': str(D.A['codes'][j]), 'h3': bool(h3),
                        'extra_top4': bool(extra), 'incremental': bool(extra and not h3)})
    win_years = {}
    for year in ('2024', '2025', '2026'):
        rs = [w for w in windows if w['day'].startswith(year)]
        win_years[year] = {'windows': len(rs), 'h3': sum(w['h3'] for w in rs),
                           'extra_top4': sum(w['extra_top4'] for w in rs),
                           'incremental': sum(w['incremental'] for w in rs)}
    paths = ('studies/trader_replication/martin_continue_cg.py', 'studies/trader_replication/martin_continue_a.py',
             'studies/trader_replication/martin_continue_bv.py', 'studies/trader_replication/martin_list.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/trader_replication/martin_strong.py')
    out = {'dataset_digest': D.A['digest'], 'window': list(panels.WINDOW), 'years': years, 'rows': rows,
           'window_years': win_years, 'windows': windows,
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}}
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_cg.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
