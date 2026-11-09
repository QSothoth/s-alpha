"""CN: prior-close S43 coil ranks in N's existing peer list, diagnostic only."""
import datetime as dt
import gc
import hashlib
import json
import os
from pathlib import Path
import warnings

import numpy as np

from . import panels, ticket_t4, watchlist
from .martin_continue_a import required_fields
from .martin_continue_bq import _ROLL_MEAN, activity_ranks, chunked_roll_mean
from .martin_continue_bv import daily_name_score
from .martin_continue_n import peer_flags
from .martin_list import ema
from .martin_strong import Data, pct
from .martin_strong_scan import HOLD, active, hold_sim


def prior_week_tight(A, target_days):
    """The S43 words() lag, evaluated by columns without wide weekly panels."""
    weeks = [dt.date.fromisoformat(str(x)).isocalendar()[:2] for x in A['days']]
    ends = [i for i in range(len(weeks)) if i + 1 == len(weeks) or weeks[i + 1] != weeks[i]]
    starts = [0] + [i + 1 for i in ends[:-1]]
    targets = np.asarray(target_days, dtype=int)
    # words() maps each row to the preceding complete week, then shifts a day.
    indexes = np.searchsorted(ends, targets - 1, side='left') - 1
    out = np.full((len(targets), A['close'].shape[1]), np.nan, dtype=np.float32)
    for start in range(0, out.shape[1], 64):
        sl = slice(start, start + 64)
        wr = np.full((len(ends), out[:, sl].shape[1]), np.nan)
        with warnings.catch_warnings(), np.errstate(all='ignore'):
            warnings.simplefilter('ignore', RuntimeWarning)
            for i, (first, last) in enumerate(zip(starts, ends)):
                hi = np.nanmax(A['high'][first:last + 1, sl].astype(float), axis=0)
                lo = np.nanmin(A['low'][first:last + 1, sl].astype(float), axis=0)
                wr[i] = hi / lo - 1
            ratio = wr / watchlist.roll_mean(wr, 10)
        valid = indexes >= 0
        out[valid, sl] = ratio[indexes[valid]]
    return out


def prior_squeeze(close, e9, adr, target_days):
    out = np.full((len(target_days), close.shape[1]), np.nan, dtype=np.float32)
    valid = np.asarray(target_days) > 0
    dates = np.asarray(target_days)[valid] - 1
    for start in range(0, close.shape[1], 64):
        sl = slice(start, start + 64)
        e21 = ema(close[:, sl].astype(float), 21).astype(np.float32)
        with np.errstate(all='ignore'):
            out[valid, sl] = np.abs(e9[dates, sl] / e21[dates] - 1) / adr[dates, sl]
    return out


def rank_coil(names, active_row, fields, squeeze, weekly, day, codes):
    """Existing S43 equal percentiles; only ordering, no membership changes."""
    total = np.zeros(active_row.shape, dtype=np.float32)
    for values in (fields['act20'][day - 1], fields['stay250'][day - 1],
                   fields['fast250'][day - 1], -squeeze, -weekly):
        total += np.nan_to_num(pct(values[None, :], active_row[None, :])[0] - .5)
    return names[np.lexsort((codes[names], -total[names]))]


def residuals(D):
    out = np.zeros(D.c.shape, dtype=np.float32)
    with warnings.catch_warnings(), np.errstate(all='ignore'):
        warnings.simplefilter('ignore', RuntimeWarning)
        for day in range(1, len(D.days)):
            r = D.c[day] / D.c[day - 1] - 1
            med = np.nanmedian(np.where(D.rk[day] < 300, r, np.nan))
            out[day] = np.nan_to_num(r - med)
    return out


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
    prior_path = root / 'studies/trader_replication/reports/gap_review/strong_continue_o.json'
    prior = json.loads(prior_path.read_text())
    if prior['dataset_digest'] != D.A['digest']:
        raise ValueError('O reference dataset differs')
    ref = {(x['day'], x['ticker']): x for x in prior['rows']}
    ledger = [(d, j, ticker, day) for d, j, ticker, _, day in D.his
              if D.U[d, j] and mask[d, j] and not holding[d, j]]
    if {(day, ticker) for d, j, ticker, day in ledger} != set(ref):
        raise AssertionError('O reference ledger differs')
    windows, needed = [], {d for d, _, _, _ in ledger}
    for d, j, _, _, day in D.big:
        peak = d + 1 + int(np.nanargmax(D.h[d + 1:d + 21, j]))
        last = min(d + 10, peak - 1)
        windows.append((d, j, day, last))
        needed.update(range(d, last + 1))
    targets = sorted(needed)
    weekly = prior_week_tight(D.A, targets)
    squeeze = prior_squeeze(D.c, D.e9, D.adr, targets)
    rr = residuals(D)
    codes = np.asarray(D.A['codes']).astype(str)
    ranks, sizes = {}, {}
    for i, day in enumerate(targets):
        pool, leaders = np.flatnonzero(mask[day] & ~holding[day]), np.flatnonzero(holding[day])
        rising = np.isfinite(D.c[day - 1, leaders]) & np.isfinite(D.c[day - 6, leaders]) & (D.c[day - 1, leaders] > D.c[day - 6, leaders])
        peer, _ = peer_flags(rr[day - 40:day, pool], rr[day - 40:day, leaders], rising)
        names = pool[peer]
        ordered = rank_coil(names, mask[day], fields, squeeze[i], weekly[i], day, codes)
        ranks[day] = {int(j): n + 1 for n, j in enumerate(ordered)}
        sizes[day] = len(names)
    rows = []
    for day, j, ticker, date in ledger:
        old = ref[(date, ticker)]
        rank = ranks[day].get(int(j))
        if (rank is not None) != (old['rank'] is not None) or sizes[day] != old['n1_count']:
            raise AssertionError(f'N1 differs from O for {date} {ticker}')
        rows.append({'day': date, 'ticker': ticker, 'big': old['big'], 'n1_count': sizes[day],
                     'original_rank': old['rank'], 'coil_rank': rank})
    years = {}
    for year in ('2024', '2025', '2026'):
        groups = {}
        for label in ('all', 'big'):
            sample = [r for r in rows if r['day'].startswith(year) and (label == 'all' or r['big'] is True)]
            groups[label] = {'n': len(sample), 'in_n1': sum(r['coil_rank'] is not None for r in sample),
                'coil': {str(k): sum(r['coil_rank'] is not None and r['coil_rank'] <= k for r in sample) for k in (1, 2, 4)},
                'original': {str(k): sum(r['original_rank'] is not None and r['original_rank'] <= k for r in sample) for k in (1, 2, 4)},
                'random_expected': {str(k): sum(min(k, r['n1_count']) / r['n1_count'] for r in sample if r['coil_rank'] is not None) for k in (1, 2, 4)}}
        years[year] = {'n1_width': prior['years'][year]['n1_width'], **groups}
    for year, n in {'2024': 4, '2025': 7, '2026': 2}.items():
        if years[year]['big']['n'] != n:
            raise AssertionError('big-trade denominator differs from O')
    window_rows = []
    for day, j, date, last in windows:
        h3 = any(holding[t, j] for t in range(day, last + 1))
        extra = any(ranks[t].get(int(j), 999) <= 4 for t in range(day, last + 1))
        window_rows.append({'day': date, 'ticker': codes[j], 'h3': bool(h3), 'coil_top4': bool(extra),
                            'incremental': bool(extra and not h3)})
    window_years = {}
    for year in ('2024', '2025', '2026'):
        sample = [x for x in window_rows if x['day'].startswith(year)]
        window_years[year] = {'windows': len(sample), 'h3': sum(x['h3'] for x in sample),
            'coil_top4': sum(x['coil_top4'] for x in sample), 'incremental': sum(x['incremental'] for x in sample)}
    paths = ('studies/trader_replication/martin_continue_cn.py', 'studies/trader_replication/martin_continue_n.py',
             'studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_bv.py',
             'studies/trader_replication/martin_words.py', 'studies/trader_replication/martin_list.py',
             'studies/trader_replication/watchlist.py', 'studies/trader_replication/martin_strong.py',
             'studies/trader_replication/martin_continue_bq.py', 'studies/trader_replication/martin_strong_scan.py',
             'studies/martin_luk/notes/trades.csv')
    out = {'dataset_digest': D.A['digest'], 'window': list(panels.WINDOW), 'years': years, 'rows': rows,
           'windows': window_rows, 'window_years': window_years,
           'prior_report_sha256': hashlib.sha256(prior_path.read_bytes()).hexdigest(),
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}}
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_cn.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
