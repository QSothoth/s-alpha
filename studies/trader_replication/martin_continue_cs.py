"""CS: re-evaluate R49's fixed climax exit in current accounts."""
from collections import Counter
from dataclasses import replace
import gc
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from studies.martin_luk.replicate import climax
from . import compare, panels, system, ticket_t4, watchlist
from .martin_continue_a import required_fields
from .martin_continue_bm import describe
from .martin_continue_bq import _ROLL_MEAN, activity_ranks, chunked_roll_mean
from .martin_continue_bt import fidelity
from .martin_continue_bv import daily_name_score, daily_pool_book
from .martin_continue_ci import plain
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, merge, nl_rules, sized


def climax_by_chunk(close, turnover):
    """The exact R49 definition with bounded stock-column working arrays."""
    out = np.zeros(close.shape, dtype=bool)
    for start in range(0, close.shape[1], 64):
        sl = slice(start, start + 64)
        out[:, sl] = climax({'close': close[:, sl], 'turnover': turnover[:, sl]}, .5)
    return out


def prior_signal(signal):
    out = np.zeros(signal.shape, dtype=bool)
    out[1:] = signal[:-1]
    return out


def account(D, book, rules, signal, lagged):
    px = D.base.px(D.A)
    # The baseline builder supplies its usual EMA and risk inputs. Inject only the
    # registered close-based exit mask, without adding another data source.
    base = replace(rules, exit_signal='')
    em = D.base.ema_inputs(D.A, D.pool, base)
    em.update({'climax50': signal, 'prior_climax50': lagged})
    track = {}
    curve, dates, trades = system.simulate(px, em, rules, book, *panels.WINDOW, audit=True, track=track)
    lo = int(np.searchsorted(D.A['days'], panels.WINDOW[0]))
    hi = int(np.searchsorted(D.A['days'], panels.WINDOW[1], side='right'))
    metrics = compare.metrics(curve, dates, trades, book, lo, hi)
    metrics['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in trades) for y in ('2024', '2025', '2026')}
    metrics['invested_basis'] = describe([t for t in trades if t['why'] != 'end'], 'ret_invested')
    metrics['max_close_positions'] = max(track['open'])
    exits, same_day_add = Counter(), Counter()
    for t in trades:
        if t['why'] == 'signal':
            y = t['exit'][:4]
            exits[y] += 1
            if any(e['action'] == 'add' and e['time'] == t['exit'] for e in t['executions']):
                same_day_add[y] += 1
    return {'metrics': metrics, 'fidelity': fidelity(D, trades),
            'signal_exits': dict(exits), 'signal_exit_same_day_add': dict(same_day_add)}


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
    raw = daily_pool_book(D, fields, holding, score)
    u1, sat = merge(D.reg, sized(raw, .5)), plain(raw)
    del fields, mask, score, holding, raw
    gc.collect()
    lever, unlevered = f1_rules(D, 6, (1, 3)), nl_rules(D, 6)
    if lever.exit_signal or unlevered.exit_signal:
        raise ValueError('registered account already has an exit signal')
    print('build climax50', flush=True)
    signal = climax_by_chunk(D.A['close'], D.A['turnover'])
    lagged = prior_signal(signal)
    counts = {year: int(sum(signal[d].sum() for d, date in enumerate(D.days)
                            if date.startswith(year) and panels.WINDOW[0] <= date <= panels.WINDOW[1]))
              for year in ('2024', '2025', '2026')}
    cases = {'U1': (u1, lever), 'CS1': (u1, replace(lever, exit_signal='climax50')),
             'CS2': (u1, replace(lever, exit_signal='prior_climax50')),
             'SAT6': (sat, unlevered), 'CS3': (sat, replace(unlevered, exit_signal='climax50')),
             'CS4': (sat, replace(unlevered, exit_signal='prior_climax50'))}
    results = {}
    for name, (book, rules) in cases.items():
        print('account', name, flush=True)
        results[name] = account(D, book, rules, signal, lagged)
    reference_path = root / 'studies/trader_replication/reports/gap_review/strong_continue_bz.json'
    reference = json.loads(reference_path.read_text())['results']
    for name in ('U1', 'SAT6'):
        for year in ('2024', '2025', '2026'):
            actual, old = results[name]['metrics'], reference[name]['metrics']
            if abs(actual['by_year'][year] - old['by_year'][year]) > 1e-10 or actual['entries_by_year'][year] != old['entries_by_year'][year]:
                raise AssertionError(f'{name} {year} differs from BZ')
    paths = ('studies/trader_replication/martin_continue_cs.py', 'studies/martin_luk/replicate.py',
             'studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_bm.py',
             'studies/trader_replication/martin_continue_bq.py', 'studies/trader_replication/martin_continue_bt.py',
             'studies/trader_replication/martin_continue_bv.py', 'studies/trader_replication/martin_strong_scan.py',
             'studies/trader_replication/system.py')
    out = {'dataset_digest': D.A['digest'], 'window': list(panels.WINDOW), 'signal_name_days': counts, 'results': results,
           'reference_sha256': hashlib.sha256(reference_path.read_bytes()).hexdigest(),
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}}
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_cs.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
