"""DI: recheck H3 matched opportunity after one observation per stock per 21 sessions."""
from collections import defaultdict
import gc
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from . import panels, ticket_t4, watchlist
from .martin_continue_a import required_fields
from .martin_continue_bq import _ROLL_MEAN, activity_ranks, chunked_roll_mean
from .martin_continue_bu import trigger
from .martin_continue_bv import daily_name_score
from .martin_continue_cr import json_default
from .martin_continue_ct import simulate_candidate
from .martin_continue_cv import METRICS, compare_cells
from .martin_continue_da import SEED, moving_blocks
from .martin_list import ema
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, hold_sim


def select_spaced(day, names, last):
    """Same prior-only spacing across groups and dates; results do not enter selection."""
    eligible = names[day - last[names] > 20]
    last[eligible] = day
    return eligible


def main():
    if os.environ.get('TRADER_DATA_MODE') != 'frozen' or os.environ.get('TRADER_DATA_TAG') != 'trader-data-v1':
        raise ValueError('explicitly select the registered frozen v1 dataset')
    root = Path(__file__).resolve().parents[2]
    reports = root / 'studies/trader_replication/reports/gap_review'
    paths = {key: reports / f'strong_continue_{key}.json' for key in ('ct', 'cv')}
    sources = {key: json.loads(path.read_text()) for key, path in paths.items()}
    old = ticket_t4.ranks
    try:
        ticket_t4.ranks = activity_ranks
        D = Data()
    finally:
        ticket_t4.ranks = old
    pin = json.loads((root / 'studies/trader_replication/DATA_PIN.json').read_text())['trader-data-v1']['us']
    if D.A['digest'] != pin or any(p['dataset_digest'] != pin for p in sources.values()):
        raise ValueError('frozen dataset digest mismatch')
    if sources['cv']['source_ct_sha256'] != hashlib.sha256(paths['ct'].read_bytes()).hexdigest():
        raise ValueError('CT reference mismatch')
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
    del score
    gc.collect()
    e21 = np.empty(D.c.shape, dtype=np.float32)
    for start in range(0, D.c.shape[1], 64):
        sl = slice(start, start + 64)
        e21[:, sl] = ema(D.c[:, sl].astype(float), 21).astype(np.float32)
    reference = {(r['day'], r['code']): r for r in sources['ct']['candidates']}
    if len(reference) != len(sources['ct']['candidates']):
        raise ValueError('duplicate CT candidate')
    cv_days = {r['date']: r for r in sources['cv']['daily']}
    codes = np.asarray(D.A['codes']).astype(str)
    windows, window_days = [], defaultdict(list)
    for day, j, ticker, _, date in D.big:
        peak = day + 1 + int(np.nanargmax(D.h[day + 1:day + 21, j]))
        last_day = min(day + 10, peak - 1)
        idx = len(windows)
        windows.append({'date': date, 'ticker': ticker, 'h3': False, 'other': False})
        for k in range(day, last_day + 1):
            window_days[k].append((idx, j))
    last = np.full(len(codes), -100000, dtype=np.int32)
    daily, seen = [], set()
    retained = {year: {'h3': set(), 'other': set()} for year in ('2024', '2025', '2026')}
    candidate_counts = {year: {'h3': 0, 'other': 0} for year in retained}
    for d in range(1, len(D.days)):
        date = D.days[d]
        if date > panels.WINDOW[1]:
            break
        c, l, h = D.c[d], D.l[d], D.h[d - 1]
        pullback = (fields['lowe9'][d] <= .1) & (c > D.e9[d])
        breakout = (c > h) & (fields['cpos'][d] >= .5)
        valid = mask[d] & (pullback | breakout) & (np.nan_to_num(fields['ext21'][d], nan=99) <= 8.) & np.isfinite(c) & np.isfinite(l)
        names = np.flatnonzero(valid)
        picked = select_spaced(d, names, last)
        if date < panels.WINDOW[0]:
            continue
        chosen = np.zeros(len(codes), dtype=bool)
        chosen[picked] = True
        prev_adr = D.adr[d - 1]
        adr_pool = prev_adr[mask[d] & np.isfinite(prev_adr) & (prev_adr > 0)]
        boundaries = np.quantile(adr_pool, [1 / 3, 2 / 3]) if len(adr_pool) else None
        all_cells = defaultdict(lambda: {'h3': [], 'other': []})
        keep_cells = defaultdict(lambda: {'h3': [], 'other': []})
        totals = {side: {'candidates': 0, 'quick_known': 0, 'final_known': 0, 'missing_adr': 0} for side in ('h3', 'other')}
        kept_totals = {side: dict(v) for side, v in totals.items()}
        for idx, j in window_days.get(d, []):
            if valid[j] and chosen[j]:
                windows[idx]['h3' if holding[d, j] else 'other'] = True
        for j in names:
            side = 'h3' if holding[d, j] else 'other'
            fill = float(c[j])
            stop = min(max(float(l[j]), fill * .95), fill * .99)
            outcome = simulate_candidate(D.o[:, j], D.h[:, j], D.l[:, j], D.c[:, j], e21[:, j], d, fill, stop)
            key = (date, codes[j])
            if side == 'h3':
                prev = reference.get(key)
                if prev is None or prev['fill'] != fill or abs(prev['stop'] - stop) > 1e-10 or prev['outcome'] != outcome:
                    raise AssertionError('H3 candidate differs from CT: ' + str(key))
                seen.add(key)
            for target in (totals[side], kept_totals[side] if chosen[j] else None):
                if target is not None:
                    target['candidates'] += 1
                    target['quick_known'] += outcome['quick'] is not None
                    target['final_known'] += outcome['ret'] is not None
                    target['missing_adr'] += boundaries is None or not np.isfinite(prev_adr[j]) or prev_adr[j] <= 0
            if chosen[j]:
                retained[date[:4]][side].add(codes[j])
                candidate_counts[date[:4]][side] += 1
            adr = prev_adr[j]
            if boundaries is None or not np.isfinite(adr) or adr <= 0:
                continue
            cell = (trigger(bool(pullback[j]), bool(breakout[j])), int(np.searchsorted(boundaries, adr, side='right')))
            all_cells[cell][side].append(outcome)
            if chosen[j]:
                keep_cells[cell][side].append(outcome)
        current = {'date': date, 'totals': totals, 'matched': compare_cells(all_cells)}
        if current != cv_days[date]:
            raise AssertionError('full matching differs from CV on ' + date)
        daily.append({'date': date, 'totals': kept_totals, 'matched': compare_cells(keep_cells)})
        if len(daily) % 100 == 0:
            print('completed days', len(daily), flush=True)
    if seen != set(reference) or len(daily) != len(cv_days):
        raise AssertionError('candidate or session count differs from CV')
    rng = np.random.default_rng(SEED)
    years = {}
    for year in retained:
        rows = [d for d in daily if d['date'].startswith(year)]
        matched = moving_blocks(rows, rng)
        totals = {side: {k: sum(d['totals'][side][k] for d in rows)
                         for k in ('candidates', 'quick_known', 'final_known', 'missing_adr')}
                  for side in ('h3', 'other')}
        for side in totals:
            v = totals[side]
            if v['candidates'] != candidate_counts[year][side]:
                raise AssertionError('candidate counts mismatch')
            v['unique_codes'] = len(retained[year][side])
            v['quick_unknown'] = v['candidates'] - v['quick_known']
            v['final_unknown'] = v['candidates'] - v['final_known']
        subset = [w for w in windows if w['date'].startswith(year)]
        years[year] = {'totals': totals, 'matched': matched,
                       'windows': {'total': len(subset), 'h3': sum(w['h3'] for w in subset),
                                   'other': sum(w['other'] for w in subset),
                                   'other_incremental': sum(w['other'] and not w['h3'] for w in subset)}}
    paths_code = ('studies/trader_replication/martin_continue_di.py', 'studies/trader_replication/martin_continue_cv.py',
                  'studies/trader_replication/martin_continue_da.py', 'studies/trader_replication/martin_continue_ct.py',
                  'studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_bq.py',
                  'studies/trader_replication/martin_continue_bu.py', 'studies/trader_replication/martin_continue_bv.py',
                  'studies/trader_replication/martin_continue_cr.py', 'studies/trader_replication/martin_list.py',
                  'studies/trader_replication/martin_strong.py', 'studies/trader_replication/martin_strong_scan.py')
    out = {'dataset_digest': pin, 'window': list(panels.WINDOW), 'spacing_sessions': 21, 'seed': SEED,
           'years': years, 'daily': daily, 'windows': windows,
           'reference_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths.values()},
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths_code}}
    target = reports / 'strong_continue_di.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False, default=json_default) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
