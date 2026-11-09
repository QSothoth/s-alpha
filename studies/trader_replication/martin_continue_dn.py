"""DN: audit the original Z1 against observed first 50-EMA retests."""
from collections import Counter
import gc
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from . import panels, shorts, ticket_t4
from .martin_continue_bq import activity_ranks
from .martin_continue_bv import martin_rules
from .martin_continue_cr import json_default
from .martin_strong import Data


def first_retest(close, high, e50):
    """A break is known after its close; the first subsequent touch consumes it."""
    n, m = close.shape
    first = np.zeros((n, m), dtype=bool)
    prior = np.zeros((n, m), dtype=np.int8)  # 0 no observed break, 1 waiting, 2 already touched
    state = np.zeros(m, dtype=np.int8)
    for d in range(1, n):
        valid = (np.isfinite(close[d - 1]) & np.isfinite(close[d]) & np.isfinite(high[d]) &
                 np.isfinite(e50[d - 1]) & np.isfinite(e50[d]) & (close[d - 1] > 0) &
                 (close[d] > 0) & (high[d] > 0) & (e50[d - 1] > 0) & (e50[d] > 0))
        state[~valid] = 0
        prior[d] = state
        touch = valid & (state == 1) & (high[d] >= .99 * e50[d - 1])
        first[d] = touch
        state[touch] = 2
        state[valid & (close[d] >= e50[d])] = 0
        crossed = valid & (close[d - 1] > e50[d - 1]) & (close[d] < e50[d])
        state[crossed] = 1
    return first, prior


def z1_chunks(A, pool, block=64):
    """Call the existing implementation per independent stock column block."""
    n, m = pool.shape
    result = np.zeros((n, m), dtype=bool)
    weekly = np.zeros((n, m), dtype=bool)
    for start in range(0, m, block):
        sl = slice(start, start + block)
        a = {'days': A['days'], **{k: A[k][:, sl] for k in ('open', 'high', 'low', 'close', 'e9', 'e21', 'e50', 'tight')}}
        result[:, sl] = martin_rules.short_signals(a, pool[:, sl])['Z1']
        w9 = martin_rules.weekly_ema(a['close'], a['days'], 9)
        w21 = martin_rules.weekly_ema(a['close'], a['days'], 21)
        weekly[:, sl] = martin_rules.prev(w9 < w21)
    return result, weekly


def main():
    if os.environ.get('TRADER_DATA_MODE') != 'frozen' or os.environ.get('TRADER_DATA_TAG') != 'trader-data-v1':
        raise ValueError('explicitly select frozen v1')
    root = Path(__file__).resolve().parents[2]
    reports = root / 'studies/trader_replication/reports/gap_review'
    dc_path = reports / 'strong_continue_dc.json'
    dc = json.loads(dc_path.read_text())
    old = ticket_t4.ranks
    try:
        ticket_t4.ranks = activity_ranks
        D = Data()
    finally:
        ticket_t4.ranks = old
    pin = json.loads((root / 'studies/trader_replication/DATA_PIN.json').read_text())['trader-data-v1']['us']
    if D.A['digest'] != pin or dc['dataset_digest'] != pin:
        raise ValueError('dataset differs from DC')
    A, sc = D.A, D.cfg.get('short', {})
    if sc.get('pool') != 'U7' or sc.get('gate') != 'below50':
        raise ValueError('registered comparison settings differ')
    pool = martin_rules.pool_for(A, sc['pool'])
    gate = shorts.gate_days(A, sc['gate'])
    for key in ('pr21', 'pr63', 'pr126', 'rank_pool', 'stack'):
        A.pop(key, None)
    del D.fp, D.fwd, D.raw, D.o, D.h, D.l, D.c, D.t, D.adr, D.to20, D.U, D.rk
    gc.collect()
    print('building original Z1 by stock chunks', flush=True)
    original, weekly = z1_chunks(A, pool)
    print('auditing original Z1 formula on full cached panel', flush=True)
    full = martin_rules.short_signals(A, pool)['Z1']
    if not np.array_equal(original, full):
        raise AssertionError('chunked original Z1 differs from full original Z1')
    del full
    gc.collect()
    first, states = first_retest(A['close'], A['high'], A['e50'])
    years = {}
    for year in ('2024', '2025', '2026'):
        days = np.array([str(x).startswith(year) and panels.WINDOW[0] <= str(x) <= panels.WINDOW[1] for x in A['days']])
        z, f, st = original[days], first[days], states[days]
        if np.any(z & ~f & (st == 1)):
            raise AssertionError('valid original touch is not recognized as first retest')
        years[year] = {'z1_stock_days': int(z.sum()), 'first_retest_stock_days': int(f.sum()),
                       'z1_first_stock_days': int((z & f).sum()),
                       'z1_no_observed_break': int((z & ~f & (st == 0)).sum()),
                       'z1_first_already_consumed': int((z & ~f & (st == 2)).sum()),
                       'z1_gate': int((z & gate[days, None]).sum()),
                       'z1_first_gate': int((z & f & gate[days, None]).sum())}
        if years[year]['z1_stock_days'] != sum(years[year][k] for k in ('z1_first_stock_days', 'z1_no_observed_break', 'z1_first_already_consumed')):
            raise AssertionError('original Z1 categories do not exhaust')
    ci = {str(c): j for j, c in enumerate(A['codes'])}
    records = []
    for r in dc['ledger']:
        j = ci['US.' + r['ticker']]
        days = []
        for old_day in r['days']:
            d = D.di[old_day['day']]
            days.append({'day': old_day['day'], 'pool_u7': bool(pool[d, j]), 'weekly_down': bool(weekly[d, j]),
                         'e9_below_e21': bool(d and A['e9'][d - 1, j] < A['e21'][d - 1, j]),
                         'market_gate': bool(gate[d]), 'first_retest': bool(first[d, j]),
                         'original_z1': bool(original[d, j]), 'z1_first': bool(original[d, j] and first[d, j]),
                         'z1_gate': bool(original[d, j] and gate[d]),
                         'z1_first_gate': bool(original[d, j] and first[d, j] and gate[d]),
                         'prior_state': int(states[d, j])})
        records.append({'id': r['id'], 'ticker': r['ticker'], 'entry_date': r['entry_date'], 'precision': r['precision'],
                        'days': days})
    ledger = {}
    for year in ('2024', '2025', '2026', 'all'):
        subset = [r for r in records if year == 'all' or r['entry_date'].startswith(year)]
        ledger[year] = {'located': len(subset)}
        for k in ('pool_u7', 'weekly_down', 'e9_below_e21', 'market_gate', 'first_retest',
                  'original_z1', 'z1_first', 'z1_gate', 'z1_first_gate'):
            hit = [r['id'] for r in subset if any(d[k] for d in r['days'])]
            ledger[year][k] = {'count': len(hit), 'ids': hit}
    code = ('studies/trader_replication/martin_continue_dn.py', 'studies/martin_luk/replicate.py',
            'studies/martin_luk/selection.py', 'studies/martin_luk/luk.py',
            'studies/trader_replication/martin_continue_bv.py', 'studies/trader_replication/shorts.py',
            'studies/martin_luk/notes/trades.csv')
    out = {'dataset_digest': pin, 'window': list(panels.WINDOW), 'years': years, 'ledger': ledger, 'records': records,
           'reference_sha256': hashlib.sha256(dc_path.read_bytes()).hexdigest(),
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in code}}
    target = reports / 'strong_continue_dn.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False, default=json_default) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
