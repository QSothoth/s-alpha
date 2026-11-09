"""CW: avoid adding to a long on its already-scheduled signal exit close."""
from collections import Counter
from dataclasses import replace
import gc
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from . import compare, panels, system, ticket_t4, watchlist
from .martin_continue_a import required_fields
from .martin_continue_bm import describe
from .martin_continue_bq import _ROLL_MEAN, activity_ranks, chunked_roll_mean
from .martin_continue_bt import fidelity
from .martin_continue_bv import daily_name_score, daily_pool_book
from .martin_continue_cs import climax_by_chunk, prior_signal
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, merge, sized


def account(D, book, rules, signal):
    px = D.base.px(D.A)
    em = D.base.ema_inputs(D.A, D.pool, replace(rules, exit_signal=''))
    em['prior_climax50'] = signal
    track = {}
    curve, dates, trades = system.simulate(px, em, rules, book, *panels.WINDOW, audit=True, track=track)
    lo = int(np.searchsorted(D.A['days'], panels.WINDOW[0]))
    hi = int(np.searchsorted(D.A['days'], panels.WINDOW[1], side='right'))
    metrics = compare.metrics(curve, dates, trades, book, lo, hi)
    metrics['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in trades) for y in ('2024', '2025', '2026')}
    metrics['invested_basis'] = describe([t for t in trades if t['why'] != 'end'], 'ret_invested')
    metrics['max_close_positions'] = max(track['open'])
    exits, adds, notionals = Counter(), Counter(), Counter()
    for t in trades:
        if t['why'] != 'signal':
            continue
        year = t['exit'][:4]
        exits[year] += 1
        sell = [e for e in t['executions'] if e['action'] == 'signal']
        if len(sell) != 1:
            raise AssertionError('signal exit does not have one execution')
        for e in t['executions']:
            if e['action'] == 'add' and e['time'] == t['exit']:
                if e['price'] != sell[0]['price']:
                    raise AssertionError('same-day add and exit prices differ')
                adds[year] += 1
                notionals[year] += e['price'] * e['shares']
    return {'metrics': metrics, 'fidelity': fidelity(D, trades), 'signal_exits': dict(exits),
            'signal_exit_same_day_add': dict(adds), 'same_day_add_notional': dict(notionals),
            'same_day_add_roundtrip_fees': {y: float(v * (rules.buy_cost + rules.sell_cost)) for y, v in notionals.items()}}


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
    book = merge(D.reg, sized(raw, .5))
    del fields, mask, score, holding, raw
    gc.collect()
    base = f1_rules(D, 6, (1, 3))
    if base.exit_signal or base.exit_signal_cancel_add:
        raise ValueError('baseline exit configuration differs')
    signal = prior_signal(climax_by_chunk(D.A['close'], D.A['turnover']))
    delayed = replace(base, exit_signal='prior_climax50')
    cases = {'U1': base, 'CS2': delayed, 'CW1': replace(delayed, exit_signal_cancel_add=True)}
    results = {}
    for name, rules in cases.items():
        print('account', name, flush=True)
        results[name] = account(D, book, rules, signal)
    report = root / 'studies/trader_replication/reports/gap_review'
    bz_path, cs_path = (report / name for name in ('strong_continue_bz.json', 'strong_continue_cs.json'))
    bz, cs = (json.loads(p.read_text()) for p in (bz_path, cs_path))
    if bz['dataset_digest'] != D.A['digest'] or cs['dataset_digest'] != D.A['digest']:
        raise ValueError('baseline dataset differs')
    for name, ref in (('U1', bz['results']['U1']), ('CS2', cs['results']['CS2'])):
        for year in ('2024', '2025', '2026'):
            actual, previous = results[name]['metrics'], ref['metrics']
            if abs(actual['by_year'][year] - previous['by_year'][year]) > 1e-10 or actual['entries_by_year'][year] != previous['entries_by_year'][year]:
                raise AssertionError(name + ' ' + year + ' differs from prior report')
    if results['CS2']['signal_exit_same_day_add'] != cs['results']['CS2']['signal_exit_same_day_add']:
        raise AssertionError('CS2 add-and-exit counts differ')
    if results['CW1']['signal_exit_same_day_add']:
        raise AssertionError('CW1 still adds on its signal exit day')
    old_path = report / 'source_pins/system_pre_cw.py.txt'
    old_digest = hashlib.sha256(old_path.read_bytes()).hexdigest()
    if old_digest != cs['code_sha256']['studies/trader_replication/system.py']:
        raise AssertionError('previous engine source does not match CS pin')
    paths = ('studies/trader_replication/martin_continue_cw.py', 'studies/trader_replication/martin_continue_cs.py',
             'studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_bm.py',
             'studies/trader_replication/martin_continue_bq.py', 'studies/trader_replication/martin_continue_bt.py',
             'studies/trader_replication/martin_continue_bv.py', 'studies/trader_replication/system.py')
    out = {'dataset_digest': D.A['digest'], 'window': list(panels.WINDOW), 'results': results,
           'previous_engine_sha256': old_digest,
           'reference_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (bz_path, cs_path)},
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}}
    target = report / 'strong_continue_cw.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
