"""GC: compare fixed-price opportunity with risk-multiple opportunity."""
from collections import Counter, defaultdict
from itertools import groupby
import json
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trader_replication import panels
from studies.trader_replication import martin_continue_fj as fj
from studies.trader_replication import martin_continue_fy as fy
from studies.trader_replication import martin_continue_ga as ga
from studies.trader_replication.martin_continue_du import REPORTS
from studies.trader_replication.martin_continue_dq import sha
from studies.trend_breakout.panel import factors

SEED, RETURN = 20261106, .30


def price_opportunity(opening, high, low, close, entry, stop):
    """Fixed net-price target before stop; intraday ordering stays unknown."""
    op = float(opening[entry])
    if not np.isfinite(op) or op <= 0 or not np.isfinite(stop) or stop <= 0:
        return 'unknown', 'missing_open_or_stop', None
    if np.float32(op) == np.float32(stop):
        return 'unknown', 'opening_precision', None
    if op < stop:
        return 'cancel', 'open_below_stop', False
    target = op * (1 + fj.COST) * (1 + RETURN) / (1 - fj.COST)
    end = min(entry + fj.HORIZON, len(opening))
    for i in range(entry, end):
        o, h, l, c = map(float, (opening[i], high[i], low[i], close[i]))
        if not (all(np.isfinite(v) and v > 0 for v in (o, h, l, c)) and
                l <= min(o, c) and h >= max(o, c)):
            return 'filled', 'invalid_bar', None
        if np.float32(o) == np.float32(stop):
            return 'filled', 'opening_stop_precision', None
        if o < stop:
            return 'filled', 'gap_stop', False
        if np.float32(o) == np.float32(target):
            return 'filled', 'opening_target_precision', None
        if o > target:
            return 'filled', 'gap_target', True
        if np.float32(l) == np.float32(stop) or np.float32(h) == np.float32(target):
            return 'filled', 'intraday_precision', None
        stopped, reached = l < stop, h > target
        if stopped and reached:
            return 'filled', 'same_day_both', None
        if stopped:
            return 'filled', 'stop', False
        if reached:
            return 'filled', 'target', True
    if end - entry == fj.HORIZON:
        return 'filled', 'horizon', False
    return 'filled', 'end_unmatured', None


def adjusted_arrays(calendar_index, days, records, actions):
    """Rebuild one stock with the trader_data panel's float32 and bar rules."""
    dates = np.array([day for day, _ in records])
    rows = np.array([v for _, v in records], dtype=float)
    adjust = factors(rows[:, 3], dates, actions)
    arrays = [np.full(len(days), np.nan, dtype=np.float32) for _ in range(4)]
    index = [calendar_index[str(day)] for day in dates]
    for n in range(4):
        arrays[n][index] = rows[:, n] * adjust
    o, h, l, c = arrays
    arrays[1] = np.fmax(h, np.fmax(o, c))
    arrays[2] = np.fmin(l, np.fmin(o, c))
    return arrays


def main():
    fj_path, fy_path, ga_path = (REPORTS / 'strong_continue_fj.json', REPORTS / 'strong_continue_fy.json',
                                 REPORTS / 'strong_continue_ga.json')
    refs = [json.loads(p.read_text()) for p in (fj_path, fy_path, ga_path)]
    for ref, module in zip(refs, (fj, fy, ga)):
        if ref['script_sha256'] != sha(Path(module.__file__)):
            raise ValueError('reference source differs')
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    digest = ds.digest()
    if any(r['dataset_digest'] != digest for r in refs):
        raise ValueError('dataset differs')
    rows, strength_rows, narrow_rows = [r['rows'] for r in refs]
    del refs
    if not len(rows) == len(strength_rows) == len(narrow_rows) == 57269:
        raise ValueError('candidate counts differ')
    by_code = defaultdict(list)
    for row, strength, narrow in zip(rows, strength_rows, narrow_rows):
        key = row['signal_day'], row['code']
        if key != (strength['signal_day'], strength['code']) or key != (narrow['signal_day'], narrow['code']):
            raise ValueError('candidate identity / order differs')
        row['strength_high'] = strength['strength_high']
        row['narrow'] = narrow['narrow']
        by_code[row['code']].append(row)
    stocks = {s['code'] for s in ds.stocks()}
    calendar = sorted({day for code, day, _ in ds.rows() if code in stocks})
    index = {day: i for i, day in enumerate(calendar)}
    actions, seen = ds.actions(), set()
    for code, group in groupby(ds.rows(), key=lambda r: r[0]):
        if code not in by_code:
            continue
        seen.add(code)
        records = [(day, values) for _, day, values in group]
        arrays = adjusted_arrays(index, calendar, records, actions.get(code, []))
        for row in by_code[code]:
            i = index[row['entry_day']]
            if index[row['signal_day']] != row['day_index'] or i != row['day_index'] + 1:
                raise ValueError('market calendar differs')
            old = fj.first_passage(*arrays, i, row['stop'])
            if old != (row['status'], row['terminal'], (row['hit3'], row['hit5'])):
                raise ValueError('FJ outcome differs for ' + row['entry_day'] + ' ' + code)
            status, reason, hit = price_opportunity(*arrays, i, row['stop'])
            if status != row['status']:
                raise ValueError('opening status differs')
            row['hit30'], row['reason30'] = hit, reason
            if status == 'filled':
                op = float(arrays[0][i])
                row['width'] = (op - row['stop']) / op
                netrisk = op * (1 + fj.COST) - row['stop'] * (1 - fj.COST)
                row['net5r'] = 5 * netrisk / (op * (1 + fj.COST))
            else:
                row['width'], row['net5r'] = None, None
    if seen != set(by_code):
        raise ValueError('missing candidate symbol')
    output, rng = {}, np.random.default_rng(SEED)
    for factor in ('strength_high', 'narrow'):
        output[factor] = {}
        transformed = []
        for row in rows:
            if row[factor] is None:
                continue
            item = row.copy()
            original = item['selected']
            item['selected'] = item[factor]
            if item['adr_bin'] is not None:
                item['adr_bin'] += 3 * int(original)
            transformed.append(item)
        for year in ('2024', '2025', '2026'):
            year_days = [i for i in range(len(calendar) - 1)
                         if panels.WINDOW[0] <= calendar[i + 1] <= panels.WINDOW[1]
                         and calendar[i + 1].startswith(year)]
            annual = [r for r in transformed if r['year'] == year]
            result = {}
            for sample in ('all', 'spaced'):
                subset = [r for r in annual if sample == 'all' or r['spaced']]
                result[sample] = {}
                for mode, conditional in (('per_preselected', False), ('per_filled', True)):
                    groups = {}
                    for name, flag in (('factor', True), ('other', False)):
                        selected = [r for r in subset if r['selected'] == flag]
                        eligible = [r for r in selected if not conditional or r['status'] == 'filled']
                        filled = [r for r in selected if r['status'] == 'filled']
                        stats = {'orders': len(selected), 'status': dict(Counter(r['status'] for r in selected)),
                                 'reasons30': dict(Counter(r['reason30'] for r in eligible))}
                        for metric in ('hit30', 'hit5'):
                            valid = [r[metric] for r in eligible if r[metric] is not None]
                            stats[metric] = {'known': len(valid), 'unknown': len(eligible) - len(valid),
                                             'hits': sum(valid), 'rate': sum(valid) / len(valid) if valid else None}
                        for metric in ('width', 'net5r'):
                            values = [r[metric] for r in filled if r[metric] is not None]
                            stats['median_' + metric] = float(np.median(values)) if values else None
                        groups[name] = stats
                    matches = {metric: fj.matched(subset, year_days, metric, conditional, rng)
                               for metric in ('hit30', 'hit5')}
                    for match in matches.values():
                        match['factor_weight'] = match.pop('top4_weight')
                    result[sample][mode] = {'groups': groups, 'matched': matches}
            output[factor][year] = result
    result = {'dataset_digest': digest, 'fj_sha256': sha(fj_path), 'fy_sha256': sha(fy_path),
              'ga_sha256': sha(ga_path), 'script_sha256': sha(Path(__file__)), 'seed': SEED,
              'outcome_replayed': len(rows), 'results': output,
              'rows': [{'signal_day': r['signal_day'], 'code': r['code'], 'hit30': r['hit30'],
                        'reason30': r['reason30'], 'width': r['width'], 'net5r': r['net5r']} for r in rows]}
    target = REPORTS / 'strong_continue_gc.json'
    target.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    print('wrote', target, 'rows', len(rows), flush=True)


if __name__ == '__main__':
    main()
