"""CE: describe the first EMA9 touch after an EMA9/21 bullish cross."""
import gc
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from . import panels, ticket_t4, watchlist
from .martin_continue_a import required_fields
from .martin_continue_bq import _ROLL_MEAN, activity_ranks, chunked_roll_mean
from .martin_continue_bv import daily_name_score, daily_pool_book
from .martin_continue_bz import run
from .martin_list import ema
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, merge, sized


def first_touch(e9, e21, low):
    result = np.zeros(e9.shape, dtype=bool)
    waiting = np.zeros(e9.shape[1], dtype=bool)
    for day in range(1, len(e9)):
        valid = (np.isfinite(e9[day]) & np.isfinite(e21[day]) & np.isfinite(low[day]) &
                 np.isfinite(e9[day - 1]) & np.isfinite(e21[day - 1]))
        above = e9[day] > e21[day]
        cross = valid & above & (e9[day - 1] <= e21[day - 1])
        touch = valid & (low[day] <= e9[day])
        result[day] = waiting & valid & above & ~cross & touch
        waiting = np.where(cross, True, waiting & valid & above & ~touch)
    return result


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
    raw = daily_pool_book(D, fields, holding, score)
    u1 = merge(D.reg, sized(raw, .5))
    e21 = ema(D.c.astype(float), 21).astype(np.float32)
    first = first_touch(D.e9, e21, D.l)
    del e21, fields, mask, score, holding
    gc.collect()
    candidates = {'first': set(), 'other': set(), 'all_list': set()}
    for d, row in enumerate(raw):
        if not panels.WINDOW[0] <= D.days[d] <= panels.WINDOW[1]:
            continue
        for e in row:
            j = e[1]
            candidates['all_list'].add((d, j))
            if D.l[d, j] <= D.e9[d, j] and D.c[d, j] > D.e9[d, j]:
                candidates['first' if first[d, j] else 'other'].add((d, j))
    stats = {}
    for year in ('2024', '2025', '2026'):
        stats[year] = {}
        for group in ('first', 'other'):
            keys = sorted((d, j) for d, j in candidates[group] if D.days[d].startswith(year))
            observed, hits, widths = 0, 0, []
            for d, j in keys:
                fill, low = float(D.c[d, j]), float(D.l[d, j])
                stop = min(max(low, fill * .95), fill * .99)
                widths.append((fill - stop) / fill)
                highs = D.h[d + 1:d + 21, j]
                if len(highs) == 20 and np.isfinite(highs).all():
                    observed += 1
                    hits += bool(np.max(highs) >= fill * 1.30)
            stats[year][group] = {'candidates': len(keys), 'complete_20': observed, 'unknown_20': len(keys) - observed,
                                  'hits_30': hits, 'hit_rate': hits / observed if observed else None,
                                  'median_initial_stop': float(np.median(widths)) if widths else None}
    windows = []
    for day, j, _, _, date in D.big:
        peak = day + 1 + int(np.nanargmax(D.h[day + 1:day + 21, j]))
        end = min(day + 10, peak - 1)
        item = {'date': date, 'code': str(D.A['codes'][j])}
        for group in ('all_list', 'first', 'other'):
            hits = [D.days[d] for d in range(day, end + 1) if (d, j) in candidates[group]]
            item[group] = hits
        windows.append(item)
    by_year = {}
    for year in ('2024', '2025', '2026'):
        subset = [w for w in windows if w['date'].startswith(year)]
        by_year[year] = {'windows': len(subset), **{g: sum(bool(w[g]) for w in subset)
                                                      for g in ('all_list', 'first', 'other')}}
    print('account U1', flush=True)
    baseline = run(D, u1, f1_rules(D, 6, (1, 3)))
    prior = json.loads((root / 'studies/trader_replication/reports/gap_review/strong_continue_cc.json').read_text())['results']['U1']['metrics']
    for year in ('2024', '2025', '2026'):
        actual = baseline['metrics']
        if abs(actual['by_year'][year] - prior['by_year'][year]) > 1e-10 or actual['entries_by_year'][year] != prior['entries_by_year'][year]:
            raise AssertionError(f'U1 {year} baseline differs from CC')
    paths = ('studies/trader_replication/martin_continue_ce.py', 'studies/trader_replication/martin_continue_a.py',
             'studies/trader_replication/martin_continue_bv.py', 'studies/trader_replication/martin_strong.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/trader_replication/system.py')
    out = {'dataset_digest': D.A['digest'], 'window': list(panels.WINDOW), 'candidate_stats': stats,
           'windows_by_year': by_year, 'windows': windows, 'baseline': baseline,
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}}
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_ce.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
