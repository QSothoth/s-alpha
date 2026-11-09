"""BZ: compare fixed 3R/5R partial sales with existing list management."""
from collections import Counter
from dataclasses import replace
import gc
import hashlib
import json
from pathlib import Path

import numpy as np

from . import compare, panels, system, ticket_t4, watchlist
from .martin_continue_a import required_fields
from .martin_continue_bm import describe
from .martin_continue_bq import _ROLL_MEAN, activity_ranks, chunked_roll_mean
from .martin_continue_bt import fidelity
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, name_score, nl_rules, pool_book2, u1_entries


def partial_list(rules):
    if rules.unit_adr or rules.trail_after_trim:
        raise ValueError('R units or post-trim trail differ from the preregistered policy')
    management = dict(rules.management_by_kind)
    management['list'] = {**management.get('list', {}), 'trims': (3, 5), 'trim_frac': .15}
    return replace(rules, management_by_kind=management)


def run(D, book, rules):
    px, em = D.base.px(D.A), D.base.ema_inputs(D.A, D.pool, rules)
    track = {}
    curve, dates, trades = system.simulate(px, em, rules, book, *panels.WINDOW, audit=True, track=track)
    a = int(np.searchsorted(D.A['days'], panels.WINDOW[0]))
    b = int(np.searchsorted(D.A['days'], panels.WINDOW[1], side='right'))
    metrics = compare.metrics(curve, dates, trades, book, a, b)
    metrics['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in trades) for y in ('2024', '2025', '2026')}
    metrics['average_close_positions'] = float(np.mean(track['open']))
    metrics['max_close_positions'] = max(track['open'])
    closed = [t for t in trades if t['why'] != 'end']
    metrics['invested_basis'] = describe(closed, 'ret_invested')
    trim_counts = Counter()
    trim_positions = Counter()
    for t in trades:
        if t['kind'] != 'list':
            continue
        years = set()
        for e in t['executions']:
            if e['action'] == 'trim':
                year = e['time'][:4]
                trim_counts[year] += 1
                years.add(year)
        for year in years:
            trim_positions[year] += 1
    return {'metrics': metrics, 'fidelity': fidelity(D, trades),
            'trim_executions': dict(trim_counts), 'trim_positions': dict(trim_positions)}


def main():
    original = ticket_t4.ranks
    try:
        ticket_t4.ranks = activity_ranks
        D = Data()
    finally:
        ticket_t4.ranks = original
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
    score = name_score(D, fields, mask, HOLD['H3'])
    holding = hold_sim(score, 12, 36)
    u1 = u1_entries(D, fields, holding, score)
    raw = pool_book2(D, fields, holding, score, True, 8.0, None, False)
    sat = [[((2.0,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:6])
            for e in row] for row in raw]
    del fields, mask, score, holding, raw
    gc.collect()
    lever = f1_rules(D, 6, (1, 3))
    limited = replace(lever, max_open=11)
    unlevered = nl_rules(D, 6)
    cases = {'U1': (u1, lever), 'BZ1': (u1, partial_list(lever)),
             'AY1': (u1, limited), 'BZ2': (u1, partial_list(limited)),
             'SAT6': (sat, unlevered), 'BZ3': (sat, partial_list(unlevered))}
    result = {}
    for name, (book, rules) in cases.items():
        print('account', name, flush=True)
        result[name] = run(D, book, rules)
    root = Path(__file__).resolve().parents[2]
    prior_bp = json.loads((root / 'studies/trader_replication/reports/gap_review/strong_continue_bp.json').read_text())['results']
    prior_s59 = json.loads((root / 'studies/trader_replication/reports/gap_review/strong_s59.json').read_text())
    for name, expected in (('U1', prior_bp['U1']['metrics']['by_year']),
                           ('AY1', prior_bp['AY1']['metrics']['by_year']),
                           ('SAT6', prior_s59['SAT6']['by_year'])):
        for year, value in expected.items():
            if abs(result[name]['metrics']['by_year'][year] - value) > 1e-10:
                raise AssertionError(f'{name} {year} baseline differs from the recorded output')
    paths = ('studies/trader_replication/martin_continue_bz.py', 'studies/trader_replication/martin_continue_a.py',
             'studies/trader_replication/martin_continue_bm.py', 'studies/trader_replication/martin_continue_bq.py',
             'studies/trader_replication/martin_continue_bt.py', 'studies/trader_replication/martin_strong.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/trader_replication/system.py')
    out = {'dataset_digest': D.A['digest'], 'window': list(panels.WINDOW), 'results': result,
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}}
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_bz.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), flush=True)


if __name__ == '__main__':
    main()
