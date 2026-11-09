"""CO: conservative next-session fills for a precommitted S4 support limit."""
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


def support_best(close, high, e9):
    """S4's three previously known support levels, built by stock chunks."""
    out = np.full(close.shape, np.nan, dtype=np.float32)
    for start in range(0, close.shape[1], 64):
        sl = slice(start, start + 64)
        e21 = ema(close[:, sl].astype(float), 21).astype(np.float32)
        prev = close[:-1, sl]
        for values in (e9[:-1, sl], e21[:-1]):
            good = np.isfinite(values) & (values > 0) & (values <= prev)
            out[1:, sl] = np.fmax(out[1:, sl], np.where(good, values, np.nan))
        values, prev2 = high[:-2, sl], close[1:-1, sl]
        good = np.isfinite(values) & (values > 0) & (values <= prev2)
        out[2:, sl] = np.fmax(out[2:, sl], np.where(good, values, np.nan))
    return out


def opening_and_intraday(level, opening, low):
    """Return validity, gap fill, intraday fill, and conservative same-day survival."""
    valid = np.isfinite(opening) & np.isfinite(low) & (opening > 0) & (low > 0) & (low <= opening)
    available = np.isfinite(level) & (level > 0) & valid
    gap = available & (opening <= level)
    intraday = available & (opening > level) & (low <= level)
    price = np.where(gap, opening, level)
    survive = (gap | intraday) & (low > price * .975)
    return valid, gap, intraday, survive


def select_four(order, score, codes):
    chosen = np.zeros(order.shape, dtype=bool)
    for day in range(len(order)):
        names = np.flatnonzero(order[day])
        rank = np.lexsort((codes[names], -score[day, names]))
        chosen[day, names[rank[:4]]] = True
    return chosen


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
    del fields, mask
    gc.collect()
    level = support_best(D.c, D.h, D.e9)
    orders = holding & np.isfinite(level)
    codes = np.asarray(D.A['codes']).astype(str)
    selected = select_four(orders, score, codes)
    valid, gap, intraday, survive = opening_and_intraday(level, D.o, D.l)
    touch = gap | intraday
    # Recreate S exactly, without the new invalid-bar checks.
    old_touch = orders & np.isfinite(D.o) & np.isfinite(D.l) & (D.o > level) & (D.l <= level)
    old_survive = old_touch & (D.l > level * .975)
    prior_r_path = root / 'studies/trader_replication/reports/gap_review/strong_continue_r.json'
    prior_s_path = root / 'studies/trader_replication/reports/gap_review/strong_continue_s.json'
    prior_r, prior_s = (json.loads(p.read_text()) for p in (prior_r_path, prior_s_path))
    if any(p['dataset_digest'] != D.A['digest'] for p in (prior_r, prior_s)):
        raise ValueError('S or R reference dataset differs')
    old_rows = {(x['day'], x['ticker']): x for x in prior_s['rows']}
    ix = {c: j for j, c in enumerate(codes)}
    rows = []
    for p in prior_r['rows']:
        start, peak, j = D.di[p['day']], D.di[p['peak_day']], ix['US.' + p['ticker']]
        stop = min(start + 10, peak - 1) + 1
        old = {'ordered': bool(orders[start:stop, j].any()), 'touched': bool(old_touch[start:stop, j].any()),
               'survived_day': bool(old_survive[start:stop, j].any())}
        if p['first_gap'] == 'no_narrow' and old != old_rows[(p['day'], p['ticker'])]['levels']['S4']:
            raise AssertionError('old S4 differs for ' + p['day'] + ' ' + p['ticker'])
        group = {}
        for label, allowed in (('all', orders), ('top4', selected)):
            group[label] = {'ordered': bool(allowed[start:stop, j].any()),
                'gap': bool((allowed[start:stop, j] & gap[start:stop, j]).any()),
                'intraday': bool((allowed[start:stop, j] & intraday[start:stop, j]).any()),
                'touch': bool((allowed[start:stop, j] & touch[start:stop, j]).any()),
                'survive': bool((allowed[start:stop, j] & survive[start:stop, j]).any()),
                'gap_survive': bool((allowed[start:stop, j] & gap[start:stop, j] & survive[start:stop, j]).any()),
                'intraday_survive': bool((allowed[start:stop, j] & intraday[start:stop, j] & survive[start:stop, j]).any())}
        rows.append({'day': p['day'], 'ticker': p['ticker'], 'peak_day': p['peak_day'],
                     'first_gap': p['first_gap'], 'original_s4': old, 'groups': group})
    years = {}
    for year in ('2024', '2025', '2026', 'all'):
        sample = [r for r in rows if r['first_gap'] == 'no_narrow' and (year == 'all' or r['day'].startswith(year))]
        windows = [r for r in rows if year == 'all' or r['day'].startswith(year)]
        dates = np.array([i for i, d in enumerate(D.days) if (year == 'all' or d.startswith(year)) and panels.WINDOW[0] <= d <= panels.WINDOW[1]])
        results = {}
        for label, allowed in (('all', orders), ('top4', selected)):
            cols = ('ordered', 'gap', 'intraday', 'touch', 'survive', 'gap_survive', 'intraday_survive')
            results[label] = {'target': {key: sum(r['groups'][label][key] for r in sample) for key in cols},
                'all_windows': {key: sum(r['groups'][label][key] for r in windows) for key in cols},
                'median_daily_orders': float(np.median(allowed[dates].sum(1))),
                'median_daily_touches': float(np.median((allowed[dates] & touch[dates]).sum(1))),
                'median_daily_survived': float(np.median((allowed[dates] & survive[dates]).sum(1))),
                'invalid_order_days': int((allowed[dates] & ~valid[dates]).sum())}
        old_result = {'ordered': sum(r['original_s4']['ordered'] for r in sample),
                      'touched': sum(r['original_s4']['touched'] for r in sample),
                      'survived_day': sum(r['original_s4']['survived_day'] for r in sample)}
        expected = prior_s['years'][year]['levels']['S4']
        if any(old_result[k] != expected[k] for k in old_result):
            raise AssertionError('old S4 aggregate differs for ' + year)
        years[year] = {'target_n': len(sample), 'window_n': len(windows), 'original_s4': old_result, 'results': results}
    paths = ('studies/trader_replication/martin_continue_co.py', 'studies/trader_replication/martin_continue_s.py',
             'studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_bq.py',
             'studies/trader_replication/martin_continue_bv.py', 'studies/trader_replication/martin_list.py',
             'studies/trader_replication/martin_strong.py', 'studies/trader_replication/martin_strong_scan.py',
             'studies/martin_luk/notes/trades.csv')
    out = {'dataset_digest': D.A['digest'], 'window': list(panels.WINDOW), 'years': years, 'rows': rows,
           'source_reports_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (prior_r_path, prior_s_path)},
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}}
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_co.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
