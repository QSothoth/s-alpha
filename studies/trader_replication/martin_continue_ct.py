"""CT: prior-close scanner recency on fixed H3 trial candidates."""
from collections import Counter, defaultdict
import gc
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from . import panels, ticket_t4, watchlist
from .martin_continue_a import required_fields, rolling_float32
from .martin_continue_bq import _ROLL_MEAN, activity_ranks, chunked_roll_mean
from .martin_continue_bv import daily_name_score, daily_pool_book
from .martin_continue_cr import json_default
from .martin_list import ema
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, hold_sim


def simulate_candidate(opening, high, low, close, e21, day, fill, stop, cost=.0005):
    """Independent position, with separately matured 20-day and final labels."""
    quick = None
    for k in range(day + 1, min(day + 121, len(close))):
        o, h, l, c, avg = opening[k], high[k], low[k], close[k], e21[k]
        if not (all(np.isfinite(v) and v > 0 for v in (o, h, l, c, avg)) and l <= min(o, c) and h >= max(o, c)):
            return {'quick': quick, 'ret': None, 'days': None, 'reason': 'invalid_bar'}
        t = k - day
        if o <= stop:
            return {'quick': False if quick is None else quick, 'ret': o / fill * (1 - cost) - (1 + cost), 'days': t, 'reason': 'gap_stop'}
        if l <= stop:
            return {'quick': False if quick is None else quick, 'ret': stop / fill * (1 - cost) - (1 + cost), 'days': t, 'reason': 'stop'}
        if t <= 20 and h >= fill * 1.3:
            quick = True
        if t == 20 and quick is None:
            quick = False
        if c < avg:
            return {'quick': False if quick is None else quick, 'ret': c / fill * (1 - cost) - (1 + cost), 'days': t, 'reason': 'ema21'}
        if t == 120:
            return {'quick': quick, 'ret': c / fill * (1 - cost) - (1 + cost), 'days': t, 'reason': 'time'}
    return {'quick': quick, 'ret': None, 'days': None, 'reason': 'end_unmatured'}


def prior_age(last_seen, day):
    """Distance from previous close; never-seen names stay explicitly unknown."""
    return None if last_seen < 0 else day - 1 - int(last_seen)


def stats(rows, key):
    output = {}
    for label, test in (('recent', lambda age: age is not None and age <= 20),
                        ('old_or_never', lambda age: age is None or age > 20)):
        group = [r for r in rows if test(r[key])]
        quick = [r['outcome']['quick'] for r in group if r['outcome']['quick'] is not None]
        done = [r['outcome'] for r in group if r['outcome']['ret'] is not None]
        output[label] = {'candidates': len(group), 'never': sum(r[key] is None for r in group),
                         'quick_known': len(quick), 'quick_unknown': len(group) - len(quick),
                         'quick_rate': sum(quick) / len(quick) if quick else None,
                         'final_known': len(done), 'final_unknown': len(group) - len(done),
                         'mean_return': float(np.mean([x['ret'] for x in done])) if done else None,
                         'win_rate': float(np.mean([x['ret'] > 0 for x in done])) if done else None,
                         'large_return_rate': float(np.mean([x['ret'] >= .30 for x in done])) if done else None,
                         'median_days': float(np.median([x['days'] for x in done])) if done else None,
                         'outcome_reasons': dict(Counter(r['outcome']['reason'] for r in group))}
    days = defaultdict(lambda: [[], []])
    for r in rows:
        quick, age = r['outcome']['quick'], r[key]
        if quick is not None:
            days[r['day']][0 if age is not None and age <= 20 else 1].append(int(quick))
    differences = [float(np.mean(a) - np.mean(b)) for a, b in days.values() if a and b]
    output['same_day'] = {'days': len(differences), 'mean_quick_difference': float(np.mean(differences)) if differences else None}
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
    expected_led20 = fields['led20']
    g21 = fields['g21']
    del mask, score, holding
    gc.collect()
    with np.errstate(all='ignore'):
        range5 = chunked_roll_mean(D.h / D.l - 1, 5)
    pot, led = np.zeros(D.c.shape, dtype=bool), np.zeros(D.c.shape, dtype=bool)
    last_pot = np.full(D.c.shape[1], -1, dtype=np.int32)
    last_led = np.full(D.c.shape[1], -1, dtype=np.int32)
    rows = []
    codes = np.asarray(D.A['codes']).astype(str)
    with np.errstate(all='ignore'):
        for day, orders in enumerate(raw):
            if panels.WINDOW[0] <= D.days[day] <= panels.WINDOW[1]:
                for entry in orders:
                    j = entry[1]
                    rows.append({'day': D.days[day], 'day_index': day, 'stock_index': j, 'code': codes[j],
                                 'fill': entry[3], 'stop': entry[4],
                                 'pot_age': prior_age(last_pot[j], day), 'led_age': prior_age(last_led[j], day)})
            if day == 0:
                continue
            eligible = (np.nan_to_num(D.to20[day]) >= 5e7) & (np.nan_to_num(range5[day]) >= .035)
            r = D.c[day] / D.c[day - 1] - 1
            names = np.flatnonzero(eligible & np.isfinite(r))
            if len(names) > 60:
                pot[day, names[np.argsort(-r[names])[:50]]] = True
            names = np.flatnonzero(eligible & np.isfinite(g21[day]))
            if len(names) > 120:
                led[day, names[np.argsort(-g21[day, names])[:100]]] = True
            last_pot[pot[day]] = day
            last_led[led[day]] = day
    del range5, pot, raw, fields, g21
    gc.collect()
    led20 = rolling_float32(led, 20)
    if not np.array_equal(led20, expected_led20, equal_nan=True):
        raise AssertionError('reconstructed leader scan differs from existing H3 field')
    del led20, expected_led20, led
    gc.collect()
    e21 = np.empty(D.c.shape, dtype=np.float32)
    for start in range(0, D.c.shape[1], 64):
        sl = slice(start, start + 64)
        e21[:, sl] = ema(D.c[:, sl].astype(float), 21).astype(np.float32)
    print('walk candidates', len(rows), flush=True)
    for row in rows:
        j, d = row.pop('stock_index'), row.pop('day_index')
        row['outcome'] = simulate_candidate(D.o[:, j], D.h[:, j], D.l[:, j], D.c[:, j], e21[:, j], d, row['fill'], row['stop'])
    results = {}
    for year in ('2024', '2025', '2026'):
        sample = [r for r in rows if r['day'].startswith(year)]
        results[year] = {'candidates': len(sample), 'pot': stats(sample, 'pot_age'), 'led': stats(sample, 'led_age')}
    paths = ('studies/trader_replication/martin_continue_ct.py', 'studies/trader_replication/martin_continue_cr.py',
             'studies/trader_replication/martin_continue_a.py',
             'studies/trader_replication/martin_continue_bq.py', 'studies/trader_replication/martin_continue_bv.py',
             'studies/trader_replication/martin_list.py', 'studies/trader_replication/martin_strong_scan.py',
             'studies/trader_replication/watchlist.py')
    out = {'dataset_digest': D.A['digest'], 'window': list(panels.WINDOW), 'years': results, 'candidates': rows,
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}}
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_ct.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False, default=json_default) + '\n', encoding='utf-8')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
