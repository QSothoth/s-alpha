"""DM: fixed 2.5% open stop against V's prior-ADR stop on identical orders."""
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
from .martin_continue_bv import daily_name_score, daily_pool_book
from .martin_continue_cr import json_default
from .martin_continue_cv import compare_cells
from .martin_continue_da import SEED
from .martin_continue_dj import estimates
from .martin_continue_dk import next_open_outcome
from .martin_list import ema
from .martin_strong import Data, lag
from .martin_strong_scan import HOLD, active, hold_sim


def paired_labels(left, right):
    """Compare each outcome only where both stops have a known result."""
    a, b = {}, {}
    for metric in ('quick', 'ret'):
        x, y = left.get(metric), right.get(metric)
        a[metric], b[metric] = (x, y) if x is not None and y is not None else (None, None)
    return a, b


def main():
    if os.environ.get('TRADER_DATA_MODE') != 'frozen' or os.environ.get('TRADER_DATA_TAG') != 'trader-data-v1':
        raise ValueError('explicitly select frozen v1')
    root = Path(__file__).resolve().parents[2]
    reports = root / 'studies/trader_replication/reports/gap_review'
    paths = {k: reports / f'strong_continue_{k}.json' for k in ('r', 'v')}
    prior = {k: json.loads(p.read_text()) for k, p in paths.items()}
    if prior['v']['prior_report_sha256'] != hashlib.sha256(paths['r'].read_bytes()).hexdigest():
        raise ValueError('V prior report digest differs')
    old = ticket_t4.ranks
    try:
        ticket_t4.ranks = activity_ranks
        D = Data()
    finally:
        ticket_t4.ranks = old
    pin = json.loads((root / 'studies/trader_replication/DATA_PIN.json').read_text())['trader-data-v1']['us']
    if D.A['digest'] != pin or any(p['dataset_digest'] != pin for p in prior.values()):
        raise ValueError('frozen dataset differs')
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
    book = daily_pool_book(D, fields, holding, score)
    del fields, mask, score, holding
    gc.collect()
    width = np.maximum(.01, np.minimum(.025, lag(D.adr) / 2))
    chosen = np.zeros(D.c.shape, bool)
    for d in range(1, len(D.days)):
        entries = sorted((e for e in book[d - 1] if np.isfinite(width[d, e[1]])), key=lambda e: e[0])
        for e in entries[:6]:
            chosen[d, e[1]] = True
    opened = chosen & np.isfinite(D.o) & (D.o > 0) & np.isfinite(D.l)
    legacy_survive = opened & (D.l > D.o * (1 - width))
    codes = {str(code): j for j, code in enumerate(D.A['codes'])}
    v_rows, windows = [], []
    for r in prior['r']['rows']:
        d, peak, j = D.di[r['day']], D.di[r['peak_day']], codes['US.' + r['ticker']]
        end = min(d + 10, peak - 1)
        span = range(d, end + 1)
        v_row = {'day': r['day'], 'ticker': r['ticker'], 'peak_day': r['peak_day'],
                 'selected': any(chosen[s, j] for s in span), 'opened': any(opened[s, j] for s in span),
                 'survived': any(legacy_survive[s, j] for s in span)}
        if r['first_gap'] == 'no_narrow':
            v_rows.append(v_row)
        windows.append({**v_row, 'first_gap': r['first_gap']})
    if v_rows != prior['v']['rows']:
        raise AssertionError('V eleven target windows differ')
    for year in ('2024', '2025', '2026', 'all'):
        subset = v_rows if year == 'all' else [r for r in v_rows if r['day'].startswith(year)]
        expected = prior['v']['years'][year]
        if len(subset) != expected['n'] or any(sum(r[k] for r in subset) != expected['counts'][k]
                                               for k in ('selected', 'opened', 'survived')):
            raise AssertionError('V annual window count differs')
    e21 = np.empty(D.c.shape, dtype=np.float32)
    for start in range(0, D.c.shape[1], 64):
        sl = slice(start, start + 64)
        e21[:, sl] = ema(D.c[:, sl].astype(float), 21).astype(np.float32)
    daily, candidates = [], []
    for d in range(1, len(D.days)):
        date = D.days[d]
        if not panels.WINDOW[0] <= date <= panels.WINDOW[1]:
            continue
        cells = defaultdict(lambda: {'h3': [], 'other': []})
        for j in np.flatnonzero(chosen[d]):
            op = D.A['open'][d, j]
            w = float(width[d, j])
            if np.isfinite(op) and op > 0:
                a = next_open_outcome(D.A['open'][:, j], D.A['high'][:, j], D.A['low'][:, j],
                                      D.A['close'][:, j], e21[:, j], d, float(op) * .975)
                b = next_open_outcome(D.A['open'][:, j], D.A['high'][:, j], D.A['low'][:, j],
                                      D.A['close'][:, j], e21[:, j], d, float(op) * (1 - w))
            else:
                a = b = {'status': 'missing_open', 'quick': None, 'ret': None, 'days': None}
            aa, bb = paired_labels(a, b)
            cells[('same_order', 0)]['h3'].append(aa)
            cells[('same_order', 0)]['other'].append(bb)
            candidates.append({'day': date, 'code': str(D.A['codes'][j]), 'width_v': w,
                               'legacy_survive': bool(legacy_survive[d, j]), 'fixed': a, 'v_price': b})
        daily.append({'date': date, 'matched': compare_cells(cells)})
    by_key = {(r['day'], r['code']): r for r in candidates}
    if len(by_key) != len(candidates):
        raise ValueError('duplicate daily order')
    for w in windows:
        start, peak, code = D.di[w['day']], D.di[w['peak_day']], 'US.' + w['ticker']
        end = min(start + 10, peak - 1)
        sample = [by_key.get((D.days[d], code)) for d in range(start, end + 1)]
        sample = [r for r in sample if r]
        w['v_price_survived'] = any(r['v_price']['status'] == 'entered' for r in sample)
        w['fixed_survived'] = any(r['fixed']['status'] == 'entered' for r in sample)
    rng = np.random.default_rng(SEED)
    years = {}
    for year in ('2024', '2025', '2026'):
        sample = [r for r in candidates if r['day'].startswith(year)]
        both = [r for r in sample if r['fixed']['status'] != 'missing_open' and r['v_price']['status'] != 'missing_open']
        actual = [r for r in both if r['fixed']['status'] != 'invalid_entry_bar' and r['v_price']['status'] != 'invalid_entry_bar']
        years[year] = {'orders': len(sample), 'valid_entry_bars': len(actual),
                       'missing_or_invalid': len(sample) - len(actual),
                       'median_v_width': float(np.median([r['width_v'] for r in sample])) if sample else None,
                       'v_day_stops': sum(r['v_price']['status'] == 'stop_day0' for r in actual),
                       'fixed_day_stops': sum(r['fixed']['status'] == 'stop_day0' for r in actual),
                       'v_only_survives': sum(r['v_price']['status'] == 'entered' and r['fixed']['status'] == 'stop_day0' for r in actual),
                       'fixed_only_survives': sum(r['fixed']['status'] == 'entered' and r['v_price']['status'] == 'stop_day0' for r in actual),
                       'legacy_changed_day_survival': sum(r['legacy_survive'] != (r['v_price']['status'] == 'entered') for r in actual),
                       'matched': estimates([r for r in daily if r['date'].startswith(year)], rng)}
    code = ('studies/trader_replication/martin_continue_dm.py', 'studies/trader_replication/martin_continue_dk.py',
            'studies/trader_replication/martin_continue_v.py', 'studies/trader_replication/martin_continue_dj.py',
            'studies/trader_replication/martin_continue_ct.py', 'studies/trader_replication/martin_continue_cv.py',
            'studies/trader_replication/martin_continue_da.py', 'studies/trader_replication/martin_continue_a.py',
            'studies/trader_replication/martin_continue_bq.py', 'studies/trader_replication/martin_continue_bv.py',
            'studies/trader_replication/martin_strong.py', 'studies/trader_replication/martin_strong_scan.py')
    result = {'dataset_digest': pin, 'window': list(panels.WINDOW), 'seed': SEED, 'years': years,
              'windows': windows, 'days': daily, 'candidates': candidates,
              'references_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths.values()},
              'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in code}}
    target = reports / 'strong_continue_dm.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False, default=json_default) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
