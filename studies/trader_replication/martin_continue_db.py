"""DB: prior-close gap-anchored daily VWAP as a conservative support limit."""
import gc
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from studies import trader_data

from . import panels, ticket_t4, watchlist
from .martin_continue_a import required_fields
from .martin_continue_bq import _ROLL_MEAN, activity_ranks, chunked_roll_mean
from .martin_continue_bv import daily_name_score
from .martin_continue_co import opening_and_intraday, select_four, support_best
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, hold_sim


def anchored_levels(opening, high, low, close, volume, turnover):
    """Prior-close VWAP since the last valid >=10% upward opening gap."""
    n, m = close.shape
    level = np.full((n, m), np.nan, dtype=np.float32)
    valid_bars = np.zeros((n, m), dtype=bool)
    gaps = np.zeros((n, m), dtype=bool)
    nominal, shares = np.zeros(m), np.zeros(m)
    active = np.zeros(m, dtype=bool)
    for d in range(n - 1):
        o, h, l, c, v, t = (np.asarray(a[d], dtype=float) for a in (opening, high, low, close, volume, turnover))
        valid = (np.isfinite(o) & np.isfinite(h) & np.isfinite(l) & np.isfinite(c)
                 & np.isfinite(v) & np.isfinite(t) & (o > 0) & (h > 0) & (l > 0) & (c > 0)
                 & (v > 0) & (t > 0) & (l <= np.minimum(o, c)) & (h >= np.maximum(o, c)))
        with np.errstate(divide='ignore', invalid='ignore'):
            avg = t / v
        valid &= (avg >= l * .995) & (avg <= h * 1.005)
        valid_bars[d] = valid
        active &= valid
        nominal[~active], shares[~active] = 0, 0
        gap = np.zeros(m, dtype=bool)
        if d:
            previous = close[d - 1]
            gap = valid & np.isfinite(previous) & (previous > 0) & (o >= previous * 1.10)
        gaps[d] = gap
        nominal[gap], shares[gap] = 0, 0
        active |= gap
        nominal[active] += t[active]
        shares[active] += v[active]
        level[d + 1, active] = (nominal[active] / shares[active]).astype(np.float32)
    return level, valid_bars, gaps


def window_result(allow, gap, intraday, survived, start, stop, j):
    s = slice(start, stop)
    allowed = allow[s, j]
    gap, intraday, survived = gap[s, j], intraday[s, j], survived[s, j]
    return {'ordered': bool(allowed.any()), 'gap': bool((allowed & gap).any()),
            'intraday': bool((allowed & intraday).any()), 'touch': bool((allowed & (gap | intraday)).any()),
            'survive': bool((allowed & survived).any()), 'gap_survive': bool((allowed & gap & survived).any()),
            'intraday_survive': bool((allowed & intraday & survived).any())}


def main():
    if os.environ.get('TRADER_DATA_MODE') != 'frozen' or os.environ.get('TRADER_DATA_TAG') != 'trader-data-v1':
        raise ValueError('explicitly select frozen v1')
    root = Path(__file__).resolve().parents[2]
    report = root / 'studies/trader_replication/reports/gap_review'
    prior_path = report / 'strong_continue_co.json'
    prior = json.loads(prior_path.read_text())
    old = ticket_t4.ranks
    try:
        ticket_t4.ranks = activity_ranks
        D = Data()
    finally:
        ticket_t4.ranks = old
    pin = json.loads((root / 'studies/trader_replication/DATA_PIN.json').read_text())['trader-data-v1']['us']
    if D.A['digest'] != pin or prior['dataset_digest'] != pin:
        raise ValueError('dataset digest mismatch')
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
    panel = trader_data.load('us', mode='frozen')
    if (panel['digest'] != pin or not np.array_equal(panel['days'], D.A['days'])
            or not np.array_equal(panel['codes'], D.A['codes'])):
        raise AssertionError('volume panel identity differs')
    for name, actual in (('open', D.o), ('high', D.h), ('low', D.l), ('close', D.c), ('turnover', D.t)):
        if not np.array_equal(panel[name], actual, equal_nan=True):
            raise AssertionError('volume panel OHLC / turnover differs: ' + name)
    volume = panel['volume']
    del panel
    gc.collect()
    levels, valid_bars, anchors = anchored_levels(D.o, D.h, D.l, D.c, volume, D.t)
    del volume
    prior_close = np.empty_like(D.c)
    prior_close[0] = np.nan
    prior_close[1:] = D.c[:-1]
    valid_support = np.isfinite(levels) & (levels > 0) & np.isfinite(prior_close) & (levels <= prior_close)
    old_level = support_best(D.c, D.h, D.e9)
    codes = np.asarray(D.A['codes']).astype(str)
    ix = {c: j for j, c in enumerate(codes)}
    scenarios = {}
    for name, lev, orders in (('S4', old_level, holding & np.isfinite(old_level)),
                              ('AVWAP', levels, holding & valid_support)):
        valid, gap, intraday, survive = opening_and_intraday(lev, D.o, D.l)
        scenarios[name] = {'all': orders, 'top4': select_four(orders, score, codes),
                           'valid': valid, 'gap': gap, 'intraday': intraday, 'survive': survive}
    rows = []
    for previous in prior['rows']:
        start, peak, j = D.di[previous['day']], D.di[previous['peak_day']], ix['US.' + previous['ticker']]
        stop = min(start + 10, peak - 1) + 1
        groups = {}
        for name, data in scenarios.items():
            groups[name] = {label: window_result(data[label], data['gap'], data['intraday'], data['survive'], start, stop, j)
                            for label in ('all', 'top4')}
        if groups['S4'] != previous['groups']:
            raise AssertionError('CO S4 window differs: ' + previous['day'] + ' ' + previous['ticker'])
        rows.append({'day': previous['day'], 'ticker': previous['ticker'], 'peak_day': previous['peak_day'],
                     'first_gap': previous['first_gap'], 'groups': groups})
    if len(rows) != 25:
        raise AssertionError('original window count differs')
    result = {}
    cols = ('ordered', 'gap', 'intraday', 'touch', 'survive', 'gap_survive', 'intraday_survive')
    for year in ('2024', '2025', '2026', 'all'):
        sample = [r for r in rows if r['first_gap'] == 'no_narrow' and (year == 'all' or r['day'].startswith(year))]
        windows = [r for r in rows if year == 'all' or r['day'].startswith(year)]
        dates = np.asarray([i for i, d in enumerate(D.days) if (year == 'all' or d.startswith(year))
                            and panels.WINDOW[0] <= d <= panels.WINDOW[1]])
        counts = {}
        for name, data in scenarios.items():
            counts[name] = {}
            for label in ('all', 'top4'):
                allowed = data[label]
                target = {key: sum(r['groups'][name][label][key] for r in sample) for key in cols}
                all_windows = {key: sum(r['groups'][name][label][key] for r in windows) for key in cols}
                value = {'target': target, 'all_windows': all_windows,
                         'median_daily_orders': float(np.median(allowed[dates].sum(1))),
                         'median_daily_touches': float(np.median((allowed[dates] & (data['gap'][dates] | data['intraday'][dates])).sum(1))),
                         'median_daily_survived': float(np.median((allowed[dates] & data['survive'][dates]).sum(1))),
                         'invalid_order_days': int((allowed[dates] & ~data['valid'][dates]).sum())}
                if name == 'S4' and value != prior['years'][year]['results'][label]:
                    raise AssertionError('CO S4 annual result differs: ' + year + ' ' + label)
                if name == 'AVWAP':
                    value['incremental_target_survive'] = sum(r['groups'][name][label]['survive'] and
                        not r['groups']['S4'][label]['survive'] for r in sample)
                    value['incremental_all_windows_survive'] = sum(r['groups'][name][label]['survive'] and
                        not r['groups']['S4'][label]['survive'] for r in windows)
                counts[name][label] = value
        dprev = dates[dates > 0] - 1
        quality = {'h3_name_days': int(holding[dates].sum()),
                   'invalid_previous_bar_in_h3': int((holding[dates[dates > 0]] & ~valid_bars[dprev]).sum()),
                   'anchor_available_name_days': int((holding[dates] & np.isfinite(levels[dates])).sum()),
                   'qualified_support_name_days': int((holding[dates] & valid_support[dates]).sum()),
                   'valid_gap_anchor_events': int(anchors[dates].sum())}
        result[year] = {'target_n': len(sample), 'window_n': len(windows), 'results': counts, 'quality': quality}
    paths = ('studies/trader_replication/martin_continue_db.py', 'studies/trader_replication/martin_continue_co.py',
             'studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_bq.py',
             'studies/trader_replication/martin_continue_bv.py', 'studies/trader_replication/martin_list.py',
             'studies/trader_replication/martin_strong.py', 'studies/trader_replication/martin_strong_scan.py',
             'studies/trader_data/panel.py', 'studies/martin_luk/notes/trades.csv')
    out = {'dataset_digest': pin, 'window': list(panels.WINDOW), 'years': result, 'rows': rows,
           'source_co_sha256': hashlib.sha256(prior_path.read_bytes()).hexdigest(),
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}}
    target = report / 'strong_continue_db.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
