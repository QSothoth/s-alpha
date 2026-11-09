"""CV: compare H3 versus other active names in matched daily candidate strata."""
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
from .martin_list import ema
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, hold_sim


METRICS = ('quick', 'return', 'large')


def metric_value(outcome, metric):
    if metric == 'quick':
        return None if outcome['quick'] is None else float(outcome['quick'])
    if outcome['ret'] is None:
        return None
    return float(outcome['ret']) if metric == 'return' else float(outcome['ret'] >= .30)


def compare_cells(cells):
    """H3-count-weighted within-cell difference, independently for each label."""
    result = {m: {'numerator': 0., 'h3_weight': 0, 'other_n': 0, 'unmatched_h3': 0, 'cells': []} for m in METRICS}
    for key, groups in sorted(cells.items()):
        for metric in METRICS:
            h3 = [v for o in groups['h3'] if (v := metric_value(o, metric)) is not None]
            other = [v for o in groups['other'] if (v := metric_value(o, metric)) is not None]
            r = result[metric]
            if not h3 or not other:
                r['unmatched_h3'] += len(h3)
                continue
            hm, om = float(np.mean(h3)), float(np.mean(other))
            r['numerator'] += len(h3) * (hm - om)
            r['h3_weight'] += len(h3)
            r['other_n'] += len(other)
            r['cells'].append({'type': key[0], 'adr_tercile': key[1], 'h3_n': len(h3),
                               'other_n': len(other), 'h3_mean': hm, 'other_mean': om})
    return result


def year_estimate(daily, metric, rng):
    usable = [d['matched'][metric] for d in daily if d['matched'][metric]['h3_weight']]
    weight = np.array([x['h3_weight'] for x in usable], dtype=float)
    numerator = np.array([x['numerator'] for x in usable], dtype=float)
    if not len(usable):
        return {'days': 0, 'h3_weight': 0, 'difference': None, 'interval95': None}
    draw = rng.integers(0, len(usable), size=(1000, len(usable)))
    boot = numerator[draw].sum(1) / weight[draw].sum(1)
    return {'days': len(usable), 'h3_weight': int(weight.sum()),
            'difference': float(numerator.sum() / weight.sum()),
            'interval95': [float(x) for x in np.quantile(boot, [.025, .975])],
            'unmatched_h3': sum(d['matched'][metric]['unmatched_h3'] for d in daily)}


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
    active_mask = active(D, fields)
    score = daily_name_score(fields, active_mask, HOLD['H3'])
    holding = hold_sim(score, 12, 36)
    del score
    gc.collect()
    e21 = np.empty(D.c.shape, dtype=np.float32)
    for start in range(0, D.c.shape[1], 64):
        sl = slice(start, start + 64)
        e21[:, sl] = ema(D.c[:, sl].astype(float), 21).astype(np.float32)
    ct_path = root / 'studies/trader_replication/reports/gap_review/strong_continue_ct.json'
    ct = json.loads(ct_path.read_text())
    if ct['dataset_digest'] != D.A['digest']:
        raise ValueError('CT reference dataset differs')
    reference = {(r['day'], r['code']): r for r in ct['candidates']}
    if len(reference) != len(ct['candidates']):
        raise ValueError('duplicate candidate key in CT')
    codes = np.asarray(D.A['codes']).astype(str)
    windows, window_days = [], defaultdict(list)
    for day, j, ticker, _, date in D.big:
        peak = day + 1 + int(np.nanargmax(D.h[day + 1:day + 21, j]))
        last = min(day + 10, peak - 1)
        idx = len(windows)
        windows.append({'date': date, 'ticker': ticker, 'h3_candidate': False, 'outside_candidate': False})
        for k in range(day, last + 1):
            window_days[k].append((idx, j))
    daily, seen = [], set()
    for d in range(1, len(D.days)):
        date = D.days[d]
        if not (panels.WINDOW[0] <= date <= panels.WINDOW[1]):
            continue
        c, l, h = D.c[d], D.l[d], D.h[d - 1]
        pullback = (fields['lowe9'][d] <= .1) & (c > D.e9[d])
        breakout = (c > h) & (fields['cpos'][d] >= .5)
        valid = active_mask[d] & (pullback | breakout) & (np.nan_to_num(fields['ext21'][d], nan=99) <= 8.) & np.isfinite(c) & np.isfinite(l)
        names = np.flatnonzero(valid)
        prev_adr = D.adr[d - 1]
        adr_pool = prev_adr[active_mask[d] & np.isfinite(prev_adr) & (prev_adr > 0)]
        boundaries = np.quantile(adr_pool, [1 / 3, 2 / 3]) if len(adr_pool) else None
        cells = defaultdict(lambda: {'h3': [], 'other': []})
        totals = {side: {'candidates': 0, 'quick_known': 0, 'final_known': 0, 'missing_adr': 0} for side in ('h3', 'other')}
        for idx, j in window_days.get(d, []):
            if valid[j]:
                windows[idx]['h3_candidate' if holding[d, j] else 'outside_candidate'] = True
        for j in names:
            side = 'h3' if holding[d, j] else 'other'
            fill = float(c[j])
            stop = min(max(float(l[j]), fill * .95), fill * .99)
            outcome = simulate_candidate(D.o[:, j], D.h[:, j], D.l[:, j], D.c[:, j], e21[:, j], d, fill, stop)
            key = (date, codes[j])
            if side == 'h3':
                previous = reference.get(key)
                if previous is None or previous['fill'] != fill or abs(previous['stop'] - stop) > 1e-10 or previous['outcome'] != outcome:
                    raise AssertionError('H3 candidate or label differs from CT: ' + str(key))
                seen.add(key)
            t = totals[side]
            t['candidates'] += 1
            t['quick_known'] += outcome['quick'] is not None
            t['final_known'] += outcome['ret'] is not None
            adr = prev_adr[j]
            if boundaries is None or not np.isfinite(adr) or adr <= 0:
                t['missing_adr'] += 1
                continue
            group = trigger(bool(pullback[j]), bool(breakout[j]))
            tercile = int(np.searchsorted(boundaries, adr, side='right'))
            cells[(group, tercile)][side].append(outcome)
        daily.append({'date': date, 'totals': totals, 'matched': compare_cells(cells)})
        if len(daily) % 100 == 0:
            print('completed days', len(daily), flush=True)
    if seen != set(reference):
        raise AssertionError('H3 candidate identities differ from CT')
    rng = np.random.default_rng(20261101)
    years = {}
    for year in ('2024', '2025', '2026'):
        subset = [d for d in daily if d['date'].startswith(year)]
        totals = {side: {k: sum(d['totals'][side][k] for d in subset)
                         for k in ('candidates', 'quick_known', 'final_known', 'missing_adr')}
                  for side in ('h3', 'other')}
        for v in totals.values():
            v['quick_unknown'] = v['candidates'] - v['quick_known']
            v['final_unknown'] = v['candidates'] - v['final_known']
        wr = [w for w in windows if w['date'].startswith(year)]
        years[year] = {'totals': totals, 'matched': {m: year_estimate(subset, m, rng) for m in METRICS},
                       'windows': {'total': len(wr), 'h3': sum(w['h3_candidate'] for w in wr),
                                   'outside': sum(w['outside_candidate'] for w in wr),
                                   'outside_incremental': sum(w['outside_candidate'] and not w['h3_candidate'] for w in wr)}}
    paths = ('studies/trader_replication/martin_continue_cv.py', 'studies/trader_replication/martin_continue_ct.py',
             'studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_bq.py',
             'studies/trader_replication/martin_continue_bu.py', 'studies/trader_replication/martin_continue_bv.py',
             'studies/trader_replication/martin_list.py', 'studies/trader_replication/martin_strong_scan.py')
    out = {'dataset_digest': D.A['digest'], 'window': list(panels.WINDOW), 'bootstrap_seed': 20261101,
           'bootstrap_draws': 1000, 'years': years, 'daily': daily, 'windows': windows,
           'source_ct_sha256': hashlib.sha256(ct_path.read_bytes()).hexdigest(),
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}}
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_cv.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False, default=json_default) + '\n', encoding='utf-8')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
