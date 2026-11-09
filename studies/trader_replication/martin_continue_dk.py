"""DK: prior-signal strong close against same-day candidates at next open."""
from collections import Counter, defaultdict
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
from .martin_continue_bv import daily_name_score, daily_pool_book
from .martin_continue_cr import json_default
from .martin_continue_ct import simulate_candidate
from .martin_continue_cv import compare_cells
from .martin_continue_da import SEED
from .martin_continue_dj import estimates
from .martin_list import ema
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, hold_sim


def strong_close(opening, high, low, close):
    if not (all(np.isfinite(v) and v > 0 for v in (opening, high, low, close))
            and low <= min(opening, close) and high >= max(opening, close) and high > low):
        return None
    return bool((close - low) / (high - low) >= .7)


def next_open_outcome(opening, high, low, close, e21, day, stop):
    o = opening[day]
    if not np.isfinite(o) or o <= 0:
        return {'status': 'missing_open', 'quick': None, 'ret': None, 'days': None}
    if o <= stop:
        return {'status': 'cancel_gap', 'quick': None, 'ret': None, 'days': None}
    h, l, c = high[day], low[day], close[day]
    if not (all(np.isfinite(v) and v > 0 for v in (h, l, c)) and l <= min(o, c) and h >= max(o, c)):
        return {'status': 'invalid_entry_bar', 'quick': None, 'ret': None, 'days': None}
    if l <= stop:
        return {'status': 'stop_day0', 'quick': False,
                'ret': float(stop / o * (1 - .0005) - (1 + .0005)), 'days': 0}
    outcome = simulate_candidate(opening, high, low, close, e21, day, float(o), stop)
    if h >= 1.3 * o:
        outcome['quick'] = True
    return {'status': 'entered', **outcome}


def main():
    if os.environ.get('TRADER_DATA_MODE') != 'frozen' or os.environ.get('TRADER_DATA_TAG') != 'trader-data-v1':
        raise ValueError('explicitly select frozen v1')
    root = Path(__file__).resolve().parents[2]
    reports = root / 'studies/trader_replication/reports/gap_review'
    paths = {k: reports / f'strong_continue_{k}.json' for k in ('ct', 'ah')}
    src = {k: json.loads(p.read_text()) for k, p in paths.items()}
    old = ticket_t4.ranks
    try:
        ticket_t4.ranks = activity_ranks
        D = Data()
    finally:
        ticket_t4.ranks = old
    pin = json.loads((root / 'studies/trader_replication/DATA_PIN.json').read_text())['trader-data-v1']['us']
    if D.A['digest'] != pin or any(p['dataset_digest'] != pin for p in src.values()):
        raise ValueError('frozen dataset differs from references')
    del D.fp, D.fwd, D.raw
    for k in ('pr21', 'pr63', 'pr126', 'rank_pool', 'stack', 'tight'):
        D.A.pop(k, None)
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
    book = daily_pool_book(D, fields, holding, score)
    del score, holding
    gc.collect()
    e21 = np.empty(D.c.shape, dtype=np.float32)
    for start in range(0, D.c.shape[1], 64):
        sl = slice(start, start + 64)
        e21[:, sl] = ema(D.c[:, sl].astype(float), 21).astype(np.float32)
    codes = np.asarray(D.A['codes']).astype(str)
    reference = {(r['day'], r['code']): r for r in src['ct']['candidates']}
    seen = set()
    for d, orders in enumerate(book):
        if panels.WINDOW[0] <= D.days[d] <= panels.WINDOW[1]:
            for e in orders:
                key = (D.days[d], codes[e[1]])
                ref = reference.get(key)
                if ref is None or ref['fill'] != e[3] or abs(ref['stop'] - e[4]) > 1e-10:
                    raise AssertionError('H3 candidate differs from CT: ' + str(key))
                seen.add(key)
    if seen != set(reference):
        raise AssertionError('H3 candidate identities differ from CT')
    counts = Counter()
    days, rows = [], []
    for d in range(1, len(D.days)):
        date = D.days[d]
        if not panels.WINDOW[0] <= date <= panels.WINDOW[1]:
            continue
        s = d - 1
        orders = sorted(book[s], key=lambda e: e[0])[:6]
        adr = D.adr[s - 1] if s else np.full(len(codes), np.nan)
        adr_pool = adr[mask[s] & np.isfinite(adr) & (adr > 0)]
        boundaries = np.quantile(adr_pool, [1 / 3, 2 / 3]) if len(adr_pool) else None
        cells = defaultdict(lambda: {'h3': [], 'other': []})
        for e in orders:
            j, stop = e[1], e[4]
            year = date[:4]
            counts[(year, 'preselected')] += 1
            op, lo = D.A['open'][d, j], D.A['low'][d, j]
            if not np.isfinite(op) or not np.isfinite(lo) or op <= 0:
                counts[(year, 'missing')] += 1
            elif op <= stop:
                counts[(year, 'open_below_stop')] += 1
            else:
                counts[(year, 'fillable')] += 1
                if lo <= stop:
                    counts[(year, 'day_stop')] += 1
            state = strong_close(D.o[s, j], D.h[s, j], D.l[s, j], D.c[s, j])
            outcome = next_open_outcome(D.A['open'][:, j], D.A['high'][:, j], D.A['low'][:, j], D.A['close'][:, j], e21[:, j], d, stop)
            row = {'signal': D.days[s], 'day': date, 'code': codes[j],
                   'group': 'unknown' if state is None else ('strong' if state else 'other'),
                   'signal_fill': e[3], 'stop': stop,
                   'open': float(op) if np.isfinite(op) else None, 'outcome': outcome}
            rows.append(row)
            if state is None or outcome['status'] in ('missing_open', 'cancel_gap', 'invalid_entry_bar'):
                continue
            if boundaries is None or not np.isfinite(adr[j]) or adr[j] <= 0:
                continue
            pull = bool(fields['lowe9'][s, j] <= .1 and D.c[s, j] > D.e9[s, j])
            br = bool(D.c[s, j] > D.h[s - 1, j] and fields['cpos'][s, j] >= .5)
            key = (trigger(pull, br), int(np.searchsorted(boundaries, adr[j], side='right')))
            cells[key]['h3' if state else 'other'].append(outcome)
        days.append({'date': date, 'matched': compare_cells(cells)})
    actual_counts = {':'.join(k): v for k, v in sorted(counts.items())}
    if actual_counts != src['ah']['candidate_counts']:
        raise AssertionError('preselected opening counts differ from AH')
    windows = []
    for start, j, ticker, _, date in D.big:
        peak = start + 1 + int(np.nanargmax(D.h[start + 1:start + 21, j]))
        end = min(start + 10, peak - 1)
        groups = {r['group'] for r in rows if r['code'] == codes[j] and start <= D.di[r['day']] <= end
                  and r['outcome']['status'] == 'entered'}
        windows.append({'date': date, 'ticker': ticker, 'strong': 'strong' in groups, 'other': 'other' in groups})
    rng = np.random.default_rng(SEED)
    result = {}
    for year in ('2024', '2025', '2026'):
        selected = [r for r in rows if r['day'].startswith(year)]
        groups = {}
        for group in ('strong', 'other', 'unknown'):
            sample = [r for r in selected if r['group'] == group]
            groups[group] = {'preselected': len(sample), 'unique_codes': len({r['code'] for r in sample}),
                             'status': dict(Counter(r['outcome']['status'] for r in sample)),
                             'quick_known': sum(r['outcome']['quick'] is not None for r in sample),
                             'final_known': sum(r['outcome']['ret'] is not None for r in sample)}
        subset = [w for w in windows if w['date'].startswith(year)]
        result[year] = {'groups': groups, 'matched': estimates([r for r in days if r['date'].startswith(year)], rng),
                        'windows': {'total': len(subset), 'strong': sum(w['strong'] for w in subset),
                                    'other': sum(w['other'] for w in subset),
                                    'strong_only': sum(w['strong'] and not w['other'] for w in subset)}}
    code = ('studies/trader_replication/martin_continue_dk.py', 'studies/trader_replication/martin_continue_dj.py',
            'studies/trader_replication/martin_continue_ct.py', 'studies/trader_replication/martin_continue_cv.py',
            'studies/trader_replication/martin_continue_da.py', 'studies/trader_replication/martin_continue_a.py',
            'studies/trader_replication/martin_continue_bq.py', 'studies/trader_replication/martin_continue_bu.py',
            'studies/trader_replication/martin_continue_bv.py', 'studies/trader_replication/martin_list.py',
            'studies/trader_replication/martin_strong.py', 'studies/trader_replication/martin_strong_scan.py')
    out = {'dataset_digest': pin, 'window': list(panels.WINDOW), 'years': result, 'days': days, 'candidates': rows,
           'windows': windows, 'candidate_counts': actual_counts, 'seed': SEED,
           'references_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths.values()},
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in code}}
    target = reports / 'strong_continue_dk.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False, default=json_default) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
