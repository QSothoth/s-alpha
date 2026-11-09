"""CA: replay the existing H4 consolidation group in fixed accounts."""
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
from .martin_continue_bz import run
from .martin_list import ema
from .martin_strong import Data, roll_ext
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, merge, nl_rules, sized


def coil_fields(D):
    """Exactly the negative squeeze and ten-day range defined by library()."""
    with np.errstate(all='ignore'):
        e21 = ema(D.c.astype(float), 21).astype(np.float32)
        squeeze = -(np.abs(D.e9 / e21 - 1) / D.adr)
        del e21
        high = roll_ext(D.h, 10, np.nanmax)
        low = roll_ext(D.l, 10, np.nanmin)
        narrow = -((high / low - 1) / D.adr)
    return {'nsq': squeeze, 'nr10': narrow}


def books(D, fields, mask, group):
    score = daily_name_score(fields, mask, HOLD[group])
    holding = hold_sim(score, 12, 36)
    raw = daily_pool_book(D, fields, holding, score)
    u1 = merge(D.reg, sized(raw, .5))
    sat = [[((2.0,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:6])
            for e in row] for row in raw]
    return u1, sat


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
    u1, sat = books(D, fields, mask, 'H3')
    print('H3 books built', flush=True)
    fields.update(coil_fields(D))
    u1_coil, sat_coil = books(D, fields, mask, 'H4')
    del fields, mask
    gc.collect()
    lever, plain = f1_rules(D, 6, (1, 3)), nl_rules(D, 6)
    cases = {'U1': (u1, lever), 'CA1': (u1_coil, lever),
             'SAT6': (sat, plain), 'CA2': (sat_coil, plain)}
    results = {}
    for name, (book, rules) in cases.items():
        print('account', name, flush=True)
        results[name] = run(D, book, rules)
    baseline = json.loads((root / 'studies/trader_replication/reports/gap_review/strong_continue_bz.json').read_text())['results']
    for name in ('U1', 'SAT6'):
        for year, expected in baseline[name]['metrics']['by_year'].items():
            if abs(results[name]['metrics']['by_year'][year] - expected) > 1e-10:
                raise AssertionError(f'{name} {year} baseline differs from BZ')
    paths = ('studies/trader_replication/martin_continue_ca.py', 'studies/trader_replication/martin_continue_a.py',
             'studies/trader_replication/martin_continue_bq.py', 'studies/trader_replication/martin_continue_bv.py',
             'studies/trader_replication/martin_continue_bz.py', 'studies/trader_replication/martin_strong.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/trader_replication/system.py')
    out = {'dataset_digest': D.A['digest'], 'window': list(panels.WINDOW), 'results': results,
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}}
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_ca.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), flush=True)


if __name__ == '__main__':
    main()
