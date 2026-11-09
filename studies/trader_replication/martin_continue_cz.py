"""CZ: give same-close new entries priority over adds to old positions."""
from collections import Counter
from dataclasses import replace
import gc
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import sys
from pathlib import Path

import numpy as np

from . import compare, panels, system, ticket_t4, watchlist
from .martin_continue_a import required_fields
from .martin_continue_bm import describe
from .martin_continue_bq import _ROLL_MEAN, activity_ranks, chunked_roll_mean
from .martin_continue_bt import fidelity
from .martin_continue_bv import daily_name_score, daily_pool_book
from .martin_continue_cr import json_default
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, merge, sized


def account(D, book, rules, engine=system):
    track = {}
    curve, dates, trades = engine.simulate(D.base.px(D.A), D.base.ema_inputs(D.A, D.pool, rules),
                                           rules, book, *panels.WINDOW, audit=True, track=track)
    lo = int(np.searchsorted(D.A['days'], panels.WINDOW[0]))
    hi = int(np.searchsorted(D.A['days'], panels.WINDOW[1], side='right'))
    metrics = compare.metrics(curve, dates, trades, book, lo, hi)
    metrics['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in trades) for y in ('2024', '2025', '2026')}
    metrics['invested_basis'] = describe([t for t in trades if t['why'] != 'end'], 'ret_invested')
    metrics['max_close_positions'] = max(track['open'])
    adds = Counter(e['time'][:4] for t in trades for e in t['executions'] if e['action'] == 'add')
    entries = {(t['entry'], t['code'], t['side'], t['kind']) for t in trades}
    if len(entries) != len(trades):
        raise AssertionError('duplicate entry identity')
    digest = hashlib.sha256(json.dumps(trades, sort_keys=True, allow_nan=False, default=json_default).encode()).hexdigest()
    curve_digest = hashlib.sha256(np.asarray(curve).tobytes()).hexdigest()
    return {'metrics': metrics, 'fidelity': fidelity(D, trades), 'adds_by_year': dict(adds),
            'trade_sha256': digest, 'curve_sha256': curve_digest}, entries


def main():
    if os.environ.get('TRADER_DATA_MODE') != 'frozen' or os.environ.get('TRADER_DATA_TAG') != 'trader-data-v1':
        raise ValueError('explicitly select frozen v1')
    root = Path(__file__).resolve().parents[2]
    report = root / 'studies/trader_replication/reports/gap_review'
    old_engine = report / 'source_pins/system_pre_cz.py.txt'
    cw_path, bz_path = (report / name for name in ('strong_continue_cw.json', 'strong_continue_bz.json'))
    cw, bz = (json.loads(p.read_text()) for p in (cw_path, bz_path))
    old_digest = hashlib.sha256(old_engine.read_bytes()).hexdigest()
    if old_digest != cw['code_sha256']['studies/trader_replication/system.py']:
        raise AssertionError('previous engine differs from CW')
    original = ticket_t4.ranks
    try:
        ticket_t4.ranks = activity_ranks
        D = Data()
    finally:
        ticket_t4.ranks = original
    pin = json.loads((root / 'studies/trader_replication/DATA_PIN.json').read_text())['trader-data-v1']['us']
    if D.A['digest'] != pin or bz['dataset_digest'] != pin:
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
    raw = daily_pool_book(D, fields, holding, score)
    book = merge(D.reg, sized(raw, .5))
    del fields, mask, score, holding, raw
    gc.collect()
    base = f1_rules(D, 6, (1, 3))
    if base.add_after_entries:
        raise AssertionError('baseline has modified priority')
    loader = importlib.machinery.SourceFileLoader('martin_system_pre_cz', str(old_engine))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    prior_engine = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = prior_engine
    loader.exec_module(prior_engine)
    results, keys = {}, {}
    for name, rules in (('U1', base), ('CZ1', replace(base, add_after_entries=True))):
        print('account', name, flush=True)
        results[name], keys[name] = account(D, book, rules)
    print('account U1 prior engine', flush=True)
    prior_result, prior_keys = account(D, book, base, engine=prior_engine)
    if prior_result != results['U1'] or prior_keys != keys['U1']:
        raise AssertionError('default engine changed curve, trades, or metrics')
    for year in ('2024', '2025', '2026'):
        actual, reference = results['U1']['metrics'], bz['results']['U1']['metrics']
        if (abs(actual['by_year'][year] - reference['by_year'][year]) > 1e-10
                or actual['entries_by_year'][year] != reference['entries_by_year'][year]):
            raise AssertionError('U1 baseline differs from BZ in ' + year)
    overlap = {}
    for year in ('2024', '2025', '2026'):
        a, b = ({k for k in keys[name] if k[0].startswith(year)} for name in ('U1', 'CZ1'))
        overlap[year] = {'common': len(a & b), 'only_u1': len(a - b), 'only_cz1': len(b - a)}
    paths = ('studies/trader_replication/martin_continue_cz.py', 'studies/trader_replication/martin_continue_a.py',
             'studies/trader_replication/martin_continue_bm.py', 'studies/trader_replication/martin_continue_bq.py',
             'studies/trader_replication/martin_continue_bt.py', 'studies/trader_replication/martin_continue_bv.py',
             'studies/trader_replication/martin_strong.py', 'studies/trader_replication/martin_strong_scan.py',
             'studies/trader_replication/system.py')
    out = {'dataset_digest': pin, 'window': list(panels.WINDOW), 'results': results, 'entry_overlap': overlap,
           'previous_engine_sha256': old_digest, 'default_matches_previous_engine': True,
           'reference_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (cw_path, bz_path)},
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}}
    target = report / 'strong_continue_cz.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
