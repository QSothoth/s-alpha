"""EZ: rerun DG1 after correcting the existing gross-cost implementation."""
from collections import Counter
from dataclasses import replace
import gc
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from . import compare, panels, system, ticket_t4
from .martin_continue_b_check import digest
from .martin_continue_bm import describe
from .martin_continue_bq import activity_ranks
from .martin_continue_bt import fidelity
from .martin_continue_cr import json_default
from .martin_strong import Data
from .martin_strong_scan import longs, nl_rules


def next_open(book, opens, lows, days):
    """Retain every prior-close candidate and priority; tomorrow's low only sets stop execution."""
    result = [[] for _ in book]
    counts = Counter()
    for day in range(1, len(book)):
        for e in book[day - 1]:
            year = days[day][:4]
            within = panels.WINDOW[0] <= days[day] <= panels.WINDOW[1]
            def count(label):
                if within:
                    counts[(year, label)] += 1
            count('preselected')
            j, stop = e[1], e[4]
            op, low = opens[day, j], lows[day, j]
            if not np.isfinite(op) or op <= 0:
                count('missing_open')
                continue
            if op <= stop:
                count('open_below_stop')
                continue
            if not np.isfinite(low):
                raise ValueError('missing intraday low prevents stop simulation')
            count('fillable')
            day_exit = float(stop) if low <= stop else None
            if day_exit is not None:
                count('day_stop')
            result[day].append((e[0], j, e[2], float(op), stop, e[5], day_exit) + e[7:])
    return result, {':'.join(k): v for k, v in sorted(counts.items())}


def main():
    if os.environ.get('TRADER_DATA_MODE') != 'frozen' or os.environ.get('TRADER_DATA_TAG') != 'trader-data-v1':
        raise ValueError('explicitly select frozen v1')
    root = Path(__file__).resolve().parents[2]
    reports = root / 'studies/trader_replication/reports/gap_review'
    reference_path = reports / 'strong_continue_dg.json'
    ref = json.loads(reference_path.read_text())
    original = ticket_t4.ranks
    try:
        ticket_t4.ranks = activity_ranks
        D = Data()
    finally:
        ticket_t4.ranks = original
    pin = json.loads((root / 'studies/trader_replication/DATA_PIN.json').read_text())['trader-data-v1']['us']
    if D.A['digest'] != pin or ref['dataset_digest'] != pin:
        raise ValueError('frozen dataset differs from reference')
    reg = [[((1.0,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:6])
            for e in row] for row in longs(D.reg)]
    delayed, counts = next_open(reg, D.A['open'], D.A['low'], D.days)
    kinds = sorted({e[5] for row in delayed for e in row})
    rules = nl_rules(D, 6)
    delayed_rules = replace(rules, intraday_kinds=tuple(sorted(set(rules.intraday_kinds) | set(kinds))))
    del D.fp, D.fwd, D.raw
    for k in ('pr21', 'pr63', 'pr126', 'rank_pool', 'stack', 'tight'):
        D.A.pop(k, None)
    D.rk = D.rk.astype(np.int32)
    gc.collect()
    px, ema = D.base.px(D.A), D.base.ema_inputs(D.A, D.pool, rules)
    start = int(np.searchsorted(D.A['days'], panels.WINDOW[0]))
    end = int(np.searchsorted(D.A['days'], panels.WINDOW[1], side='right'))
    results = {}
    if counts != ref['candidates']:
        raise AssertionError('DG1 candidate counts differ')
    for name, book, ru in (('DG1', delayed, delayed_rules), ('DG1_cash', delayed, replace(delayed_rules, gross_cost=True))):
        track = {}
        curve, dates, trades = system.simulate(px, ema, ru, book, *panels.WINDOW, audit=True, track=track)
        metrics = compare.metrics(curve, dates, trades, book, start, end)
        metrics['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in trades) for y in ('2024', '2025', '2026')}
        metrics['invested_basis'] = describe([t for t in trades if t['why'] != 'end'], 'ret_invested')
        metrics['max_close_gross'] = float(max(track['gross']))
        metrics['close_days_gross_over_one'] = int(sum(g > 1 + 1e-9 for g in track['gross']))
        metrics['max_close_positions'] = max(track['open'])
        if name == 'DG1':
            old = ref['results']['DG1']
            if digest(trades) != old['trades_digest']:
                raise AssertionError('DG1 baseline trades differ')
            for year in ('2024', '2025', '2026'):
                if abs(metrics['by_year'][year] - old['metrics']['by_year'][year]) > 1e-10 or metrics['entries_by_year'][year] != old['metrics']['entries_by_year'][year]:
                    raise AssertionError('DG1 baseline differs: ' + year)
        results[name] = {'metrics': metrics, 'fidelity': fidelity(D, trades), 'trades_digest': digest(trades),
                         'curve_sha256': hashlib.sha256(np.asarray(curve).tobytes()).hexdigest(),
                         'same_day_stop_entries_by_year': {y: sum(t['entry'].startswith(y) and t['why'] == 'stop_day0' for t in trades)
                                                           for y in ('2024', '2025', '2026')}}
    code = ('studies/trader_replication/martin_continue_ez.py', 'studies/trader_replication/martin_continue_ev.py', 'studies/trader_replication/martin_continue_dg.py', 'studies/trader_replication/martin_continue_g.py',
            'studies/trader_replication/martin_strong.py', 'studies/trader_replication/martin_strong_scan.py',
            'studies/trader_replication/system.py', 'studies/martin_luk/replicate.py')
    out = {'dataset_digest': pin, 'window': list(panels.WINDOW), 'candidates': counts, 'kinds': kinds,
           'last_day_candidates_unobservable': len(reg[-1]), 'results': results,
           'reference_sha256': hashlib.sha256(reference_path.read_bytes()).hexdigest(),
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in code}}
    target = reports / 'strong_continue_ez.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False, default=json_default) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
