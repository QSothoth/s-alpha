"""CH: audit historical fold training dates and U1's dependency on score caches."""
import gc
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from . import panels, ticket_t4, watchlist
from .martin_continue_a import required_fields
from .martin_continue_bq import _ROLL_MEAN, activity_ranks, chunked_roll_mean
from .martin_continue_bz import run
from .martin_continue_ca import books
from .martin_strong import Data
from .martin_strong_scan import active, f1_rules
from .martin_words import FOLDS
from .pick_model import K


def fold_counts(dates):
    return [{'start': a, 'end': z, 'test_rows': sum(a <= day <= z for day in dates),
             'train_before': sum(day < a for day in dates),
             'train_after': sum(day > z for day in dates)} for a, z in FOLDS]


def main():
    if os.environ.get('TRADER_DATA_MODE') != 'frozen' or os.environ.get('TRADER_DATA_TAG') != 'trader-data-v1':
        raise ValueError('explicitly select the registered frozen v1 dataset')
    root = Path(__file__).resolve().parents[2]
    old_ranks, old_load = ticket_t4.ranks, np.load
    blocked = []

    def guarded_load(file, *args, **kwargs):
        if isinstance(file, (str, bytes, os.PathLike)) and os.path.basename(os.fsdecode(file)) in ('m1_score.npy', 'm2_score.npy'):
            blocked.append(os.path.basename(os.fsdecode(file)))
            raise AssertionError('historical noncausal score cache read attempted')
        return old_load(file, *args, **kwargs)

    try:
        np.load = guarded_load
        ticket_t4.ranks = activity_ranks
        D = Data()
        ticket_t4.ranks = old_ranks
        pin = json.loads((root / 'studies/trader_replication/DATA_PIN.json').read_text())['trader-data-v1']['us']
        if D.A['digest'] != pin:
            raise ValueError('dataset digest differs from the registered v1')
        dates = [t.entry_date for t, j, _, _ in D.base.located(D.A, D.base.trades())
                 if t.side == 'long' and t.dated and t.entry_date >= '2024-01-02'
                 and t.entry_date in D.di and D.rk[D.di[t.entry_date], j] < K]
        counts = fold_counts(dates)
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
        u1, _ = books(D, fields, mask, 'H3')
        del fields, mask
        gc.collect()
        print('account U1 with score-cache read blocked', flush=True)
        account = run(D, u1, f1_rules(D, 6, (1, 3)))
    finally:
        ticket_t4.ranks = old_ranks
        np.load = old_load
    previous = json.loads((root / 'studies/trader_replication/reports/gap_review/strong_continue_cc.json').read_text())['results']['U1']['metrics']
    for year in ('2024', '2025', '2026'):
        actual = account['metrics']
        if abs(actual['by_year'][year] - previous['by_year'][year]) > 1e-10 or actual['entries_by_year'][year] != previous['entries_by_year'][year]:
            raise AssertionError(f'U1 {year} baseline differs from CC')
    paths = ('studies/trader_replication/martin_continue_ch.py', 'studies/trader_replication/martin_m1.py',
             'studies/trader_replication/martin_m2.py', 'studies/trader_replication/martin_words.py',
             'studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_ca.py',
             'studies/trader_replication/system.py')
    out = {'dataset_digest': D.A['digest'], 'window': list(panels.WINDOW), 'qualified_trade_rows': len(dates),
           'folds': counts, 'blocked_cache_attempts': blocked, 'u1': account,
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}}
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_ch.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
