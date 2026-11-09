"""GO: as-of one-month leader strength against frozen opportunity paths."""
from collections import Counter, defaultdict
from itertools import groupby
import bisect
import json
import math
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trader_replication import panels
from studies.trader_replication import martin_continue_fj as fj
from studies.trader_replication import martin_continue_fz as fz
from studies.trader_replication import martin_continue_gc as gc
from studies.trader_replication.martin_continue_du import REPORTS
from studies.trader_replication.martin_continue_dq import sha

SEED = 20261107
CUTS = fz.CUTS


def momentum21(days, day_index, stock_rows, actions, signals):
    dates = [r[0] for r in stock_rows]
    closes = [r[1][3] for r in stock_rows]
    indices = {day: i for i, day in enumerate(dates)}
    steps = np.ones(len(dates), dtype=np.float64)
    for day, a, b in actions:
        i = bisect.bisect_left(dates, day)
        if 0 < i < len(dates):
            prior = closes[i - 1]
            factor = (a * prior + b) / prior if np.isfinite(prior) and prior > 0 else float('nan')
            steps[i] *= factor if np.isfinite(factor) and factor > 0 else float('nan')
    prefix = np.cumprod(steps)
    result = {}
    for day in signals:
        index = day_index.get(day, -1)
        old_day = days[index - 21] if index >= 21 else None
        i, j = indices.get(day), indices.get(old_day)
        value = None
        if i is not None and j is not None and j < i:
            close, old, p, q = closes[i], closes[j], prefix[i], prefix[j]
            if all(np.isfinite(x) and x > 0 for x in (close, old, p, q)):
                value = float(close / (old * p / q) - 1)
                if not np.isfinite(value):
                    value = None
        result[day] = value
    return result


def label_group(rows, feature='momentum21', field='leader'):
    known = sorted((r for r in rows if r[feature] is not None), key=lambda r: (-r[feature], r['code']))
    for row in rows:
        row[field] = None
    top = math.ceil(len(known) / 3)
    for i, row in enumerate(known):
        row[field] = i < top
    return len(known), top


def main():
    fj_path, gc_path = REPORTS / 'strong_continue_fj.json', REPORTS / 'strong_continue_gc.json'
    a, b = json.loads(fj_path.read_text()), json.loads(gc_path.read_text())
    if (a['script_sha256'] != sha(Path(fj.__file__)) or b['script_sha256'] != sha(Path(gc.__file__)) or
            b['fj_sha256'] != sha(fj_path)):
        raise ValueError('FJ / GC source differs')
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    dataset_digest = ds.digest()
    if a['dataset_digest'] != dataset_digest or b['dataset_digest'] != dataset_digest:
        raise ValueError('dataset differs')
    rows, price = a['rows'], b['rows']
    del a, b
    if len(rows) != 57269 or len(rows) != len(price):
        raise ValueError('candidate count differs')
    for row, opportunity in zip(rows, price):
        if (row['signal_day'], row['code']) != (opportunity['signal_day'], opportunity['code']):
            raise ValueError('candidate identity differs')
        row['hit30'], row['reason30'] = opportunity['hit30'], opportunity['reason30']
    del price
    stocks = {s['code'] for s in ds.stocks()}
    calendar = sorted({day for code, day, _ in ds.rows() if code in stocks and day <= panels.WINDOW[1]})
    idx = {day: i for i, day in enumerate(calendar)}
    signals = defaultdict(set)
    for row in rows:
        if idx.get(row['signal_day']) != row['day_index']:
            raise ValueError('calendar differs')
        signals[row['code']].add(row['signal_day'])
    actions, seen, features, truncated = ds.actions(), set(), {}, {}
    for code, group in groupby(ds.rows(), key=lambda r: r[0]):
        if code not in signals:
            continue
        seen.add(code)
        records = [(day, values) for _, day, values in group if day <= panels.WINDOW[1]]
        values = momentum21(calendar, idx, records, actions.get(code, []), signals[code])
        features.update(((code, day), value) for day, value in values.items())
        for day in signals[code].intersection(CUTS):
            old = calendar[idx[day] - 21] if idx[day] >= 21 else None
            truncated[(code, day)] = fz.truncated_return(records, actions.get(code, []), day, old)
    if seen != set(signals):
        raise ValueError('missing candidate symbol')
    by_day = defaultdict(list)
    for row in rows:
        row['momentum21'] = features[(row['code'], row['signal_day'])]
        by_day[row['signal_day']].append(row)
    for day_rows in by_day.values():
        label_group(day_rows)
    cuts = {}
    for day in CUTS:
        sample = by_day[day]
        independent = [{'code': r['code'], 'value': truncated[(r['code'], day)]} for r in sample]
        label_group(independent, 'value', 'leader')
        ranking = {r['code']: r['leader'] for r in independent}
        mismatches = state_mismatches = rank_mismatches = 0
        maximum = 0.
        for row in sample:
            observed, expected = row['momentum21'], truncated[(row['code'], day)]
            if (observed is None) != (expected is None):
                state_mismatches += 1
            elif observed is not None:
                error = abs(observed - expected)
                maximum = max(maximum, error)
                mismatches += error > 1e-10
            rank_mismatches += row['leader'] != ranking[row['code']]
        cuts[day] = {'candidates': len(sample), 'known': sum(r['leader'] is not None for r in sample),
                     'state_mismatch': state_mismatches, 'value_mismatch': mismatches,
                     'rank_mismatch': rank_mismatches, 'max_absolute_error': maximum,
                     'passed': bool(sample) and state_mismatches == mismatches == rank_mismatches == 0}
    transformed = []
    for row in rows:
        if row['leader'] is None:
            continue
        item = row.copy()
        original = item['selected']
        item['selected'] = item['leader']
        if item['adr_bin'] is not None:
            item['adr_bin'] += 3 * int(original)
        transformed.append(item)
    output, rng = {}, np.random.default_rng(SEED)
    for year in ('2024', '2025', '2026'):
        year_days = [i for i in range(len(calendar) - 1) if panels.WINDOW[0] <= calendar[i + 1] <= panels.WINDOW[1]
                     and calendar[i + 1].startswith(year)]
        annual = [r for r in rows if r['year'] == year]
        known = [r for r in transformed if r['year'] == year]
        out = {'candidates': len(annual), 'feature_unknown': len(annual) - len(known), 'samples': {}}
        for sample in ('all', 'spaced'):
            subset = [r for r in known if sample == 'all' or r['spaced']]
            out['samples'][sample] = {}
            for mode, conditional in (('per_preselected', False), ('per_filled', True)):
                groups = {}
                for name, flag in (('leader', True), ('other', False)):
                    selected = [r for r in subset if r['selected'] == flag]
                    eligible = [r for r in selected if not conditional or r['status'] == 'filled']
                    stats = {'orders': len(selected), 'status': dict(Counter(r['status'] for r in selected)),
                             'reasons30': dict(Counter(r['reason30'] for r in eligible))}
                    for metric in ('hit3', 'hit5', 'hit30'):
                        valid = [r[metric] for r in eligible if r[metric] is not None]
                        stats[metric] = {'known': len(valid), 'unknown': len(eligible) - len(valid),
                                         'hits': sum(valid), 'rate': sum(valid) / len(valid) if valid else None}
                    groups[name] = stats
                matches = {metric: fj.matched(subset, year_days, metric, conditional, rng)
                           for metric in ('hit3', 'hit5', 'hit30')}
                for match in matches.values():
                    match['leader_weight'] = match.pop('top4_weight')
                out['samples'][sample][mode] = {'groups': groups, 'matched': matches}
        output[year] = out
    result = {'dataset_digest': dataset_digest, 'fj_sha256': sha(fj_path), 'gc_sha256': sha(gc_path),
              'script_sha256': sha(Path(__file__)), 'seed': SEED, 'cuts': cuts, 'results': output,
              'rows': [{'signal_day': r['signal_day'], 'code': r['code'], 'momentum21': r['momentum21'],
                        'leader': r['leader']} for r in rows]}
    target = REPORTS / 'strong_continue_go.json'
    target.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
