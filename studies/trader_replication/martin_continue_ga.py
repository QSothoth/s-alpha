"""GA: compare prior three-session price compression within daily candidates."""
from collections import defaultdict
from itertools import groupby
import bisect
import json
import math
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trader_replication import panels
from studies.trader_replication import martin_continue_fj as fj
from studies.trader_replication.martin_continue_du import REPORTS
from studies.trader_replication.martin_continue_dq import sha

SEED = 20261105


def compression(market_days, day_index, stock_rows, actions, signal_days):
    """Range of the three market sessions before the signal, as of their final close."""
    dates = [r[0] for r in stock_rows]
    by_day = {day: i for i, day in enumerate(dates)}
    steps = np.ones(len(dates), dtype=np.float64)
    for day, a, b in actions:
        i = bisect.bisect_left(dates, day)
        if 0 < i < len(dates):
            prev = stock_rows[i - 1][1][3]
            factor = (a * prev + b) / prev if np.isfinite(prev) and prev > 0 else float('nan')
            steps[i] *= factor if np.isfinite(factor) and factor > 0 else float('nan')
    prefix = np.cumprod(steps)
    result = {}
    for day in signal_days:
        index = day_index.get(day, -1)
        relevant = market_days[index - 3:index] if index >= 3 else []
        ids = [by_day.get(date) for date in relevant]
        value = None
        if len(ids) == 3 and all(i is not None for i in ids):
            end = ids[-1]
            scale_base = prefix[end]
            highs, lows = [], []
            for i in ids:
                o, h, l, c = stock_rows[i][1][:4]
                if not all(np.isfinite(x) and x > 0 for x in (o, h, l, c, prefix[i], scale_base)):
                    break
                scale = scale_base / prefix[i]
                highs.append(max(o, h, c) * scale)
                lows.append(min(o, l, c) * scale)
            if len(highs) == 3:
                value = float((max(highs) - min(lows)) / stock_rows[end][1][3])
                if not np.isfinite(value) or value < 0:
                    value = None
        result[day] = value
    return result


def label_narrow(rows):
    known = sorted((r for r in rows if r['compression3'] is not None),
                   key=lambda r: (r['compression3'], r['code']))
    for i, row in enumerate(known):
        row['narrow'] = i < math.ceil(len(known) / 3)
    return len(known)


def main():
    ref_path = REPORTS / 'strong_continue_fj.json'
    ref = json.loads(ref_path.read_text())
    if ref['script_sha256'] != sha(Path(fj.__file__)):
        raise ValueError('FJ source differs')
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if ds.digest() != ref['dataset_digest']:
        raise ValueError('dataset differs')
    rows = ref['rows']
    del ref
    if len(rows) != 57269:
        raise ValueError('candidate count differs')
    stocks = {s['code'] for s in ds.stocks()}
    market_days = sorted({day for code, day, _ in ds.rows() if code in stocks and day <= panels.WINDOW[1]})
    index = {day: i for i, day in enumerate(market_days)}
    signals = defaultdict(set)
    for row in rows:
        if index.get(row['signal_day']) != row['day_index']:
            raise ValueError('FJ calendar differs')
        signals[row['code']].add(row['signal_day'])
    actions, features, seen = ds.actions(), {}, set()
    for code, group in groupby(ds.rows(), key=lambda r: r[0]):
        if code not in signals:
            continue
        seen.add(code)
        stock_rows = [(day, values) for _, day, values in group if day <= panels.WINDOW[1]]
        for day, value in compression(market_days, index, stock_rows, actions.get(code, []), signals[code]).items():
            features[(code, day)] = value
    if seen != set(signals):
        raise ValueError('missing candidate symbol')
    daily = defaultdict(list)
    for row in rows:
        row['compression3'] = features[(row['code'], row['signal_day'])]
        row['narrow'] = None
        daily[row['signal_day']].append(row)
    if sum(label_narrow(group) for group in daily.values()) != sum(r['compression3'] is not None for r in rows):
        raise AssertionError('ranking population differs')
    for row in rows:
        original = row['selected']
        row['selected'] = row['narrow']
        if row['adr_bin'] is not None:
            row['adr_bin'] += 3 * int(original)
        row['turnover_top4'] = original
    rng, output = np.random.default_rng(SEED), {}
    for year in ('2024', '2025', '2026'):
        year_days = [i for i in range(len(market_days) - 1)
                     if panels.WINDOW[0] <= market_days[i + 1] <= panels.WINDOW[1]
                     and market_days[i + 1].startswith(year)]
        annual = [r for r in rows if r['year'] == year]
        known = [r for r in annual if r['narrow'] is not None]
        result = {'candidates': len(annual), 'feature_unknown': len(annual) - len(known), 'samples': {}}
        for sample in ('all', 'spaced'):
            subset = [r for r in known if sample == 'all' or r['spaced']]
            result['samples'][sample] = {}
            for mode, conditional in (('per_preselected', False), ('per_filled', True)):
                groups = fj.group_summary(subset, conditional)
                matches = {metric: fj.matched(subset, year_days, metric, conditional, rng)
                           for metric in ('hit3', 'hit5')}
                for match in matches.values():
                    match['narrow_weight'] = match.pop('top4_weight')
                result['samples'][sample][mode] = {
                    'groups': {'narrow': groups['top4'], 'other': groups['other']}, 'matched': matches}
        output[year] = result
    result = {'dataset_digest': ds.digest(), 'fj_sha256': sha(ref_path),
              'script_sha256': sha(Path(__file__)), 'seed': SEED, 'results': output,
              'rows': [{'signal_day': r['signal_day'], 'code': r['code'], 'compression3': r['compression3'],
                        'narrow': r['narrow']} for r in rows]}
    target = REPORTS / 'strong_continue_ga.json'
    target.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    print('wrote', target, 'rows', len(rows), flush=True)


if __name__ == '__main__':
    main()
