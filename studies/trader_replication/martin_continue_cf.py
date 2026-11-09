"""CF: trace the first-touch proxy through H3 and the prior-entry state."""
from collections import Counter
import gc
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from . import ticket_t4, watchlist
from .martin_continue_a import required_fields
from .martin_continue_bq import _ROLL_MEAN, activity_ranks, chunked_roll_mean
from .martin_continue_bv import daily_name_score, daily_pool_book
from .martin_continue_ce import first_touch
from .martin_list import ema
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, hold_sim


def prior_state(e9, e21, low, touch, entry_day):
    state, last_touch = 'unknown', None
    for day in range(1, entry_day):
        valid = all(np.isfinite(x) for x in (e9[day], e21[day], low[day], e9[day - 1], e21[day - 1]))
        if not valid:
            state, last_touch = 'unknown', None
        elif e9[day] <= e21[day]:
            state, last_touch = 'not_above', None
        elif e9[day - 1] <= e21[day - 1]:
            state, last_touch = 'waiting', None
        elif touch[day]:
            state, last_touch = 'touched', day
        elif state == 'not_above':
            state, last_touch = 'unknown', None
    return {'state': state, 'touch_age': entry_day - last_touch if last_touch is not None else None}


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
    e21 = ema(D.c.astype(float), 21).astype(np.float32)
    first = first_touch(D.e9, e21, D.l)
    prior = json.loads((root / 'studies/trader_replication/reports/gap_review/strong_continue_ce.json').read_text())
    previous = {(w['date'], w['code']): w for w in prior['windows']}
    windows = []
    for day, j, _, _, date in D.big:
        code = str(D.A['codes'][j])
        peak = day + 1 + int(np.nanargmax(D.h[day + 1:day + 21, j]))
        end = min(day + 10, peak - 1)
        raw_dates, first_dates, events = [], [], []
        for d in range(day, end + 1):
            is_candidate = any(e[1] == j for e in raw[d])
            if is_candidate:
                raw_dates.append(D.days[d])
            if first[d, j] and is_candidate:
                first_dates.append(D.days[d])
            if first[d, j]:
                h3 = bool(holding[d, j])
                recovered = bool(D.c[d, j] > D.e9[d, j])
                extension = bool(np.nan_to_num(fields['ext21'][d, j], nan=99) <= 8.0)
                events.append({'day': D.days[d], 'active': bool(mask[d, j]), 'h3': h3,
                               'recovered': recovered, 'extension_ok': extension, 'candidate': is_candidate})
                if is_candidate != (h3 and recovered and extension and np.isfinite(D.c[d, j]) and np.isfinite(D.l[d, j])):
                    raise AssertionError('first-touch event and original candidate conditions differ')
        record = previous[(date, code)]
        if raw_dates != record['all_list'] or first_dates != record['first']:
            raise AssertionError(f'CE candidate window does not match: {code} {date}')
        windows.append({'date': date, 'code': code,
                        'prior_state': prior_state(D.e9[:, j], e21[:, j], D.l[:, j], first[:, j], day),
                        'events': events})
    if len(previous) != len(windows):
        raise AssertionError('CE window count differs')
    summaries = {}
    for year in ('2024', '2025', '2026'):
        rows = [w for w in windows if w['date'].startswith(year)]
        stages = {'windows': len(rows), 'first_touch': sum(bool(w['events']) for w in rows),
                  'first_and_active': sum(any(e['active'] for e in w['events']) for w in rows),
                  'first_and_h3': sum(any(e['h3'] for e in w['events']) for w in rows),
                  'first_h3_recovered': sum(any(e['h3'] and e['recovered'] for e in w['events']) for w in rows),
                  'first_h3_recovered_extension': sum(any(e['h3'] and e['recovered'] and e['extension_ok'] for e in w['events']) for w in rows),
                  'first_candidate': sum(any(e['candidate'] for e in w['events']) for w in rows)}
        ages = [w['prior_state']['touch_age'] for w in rows if w['prior_state']['touch_age'] is not None]
        summaries[year] = {'stages': stages, 'prior_states': dict(Counter(w['prior_state']['state'] for w in rows)),
                           'prior_touch_ages': ages, 'prior_touch_age_median': float(np.median(ages)) if ages else None}
    paths = ('studies/trader_replication/martin_continue_cf.py', 'studies/trader_replication/martin_continue_ce.py',
             'studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_bv.py',
             'studies/trader_replication/martin_strong.py', 'studies/trader_replication/martin_strong_scan.py')
    out = {'dataset_digest': D.A['digest'], 'summaries': summaries, 'windows': windows,
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}}
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_cf.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
