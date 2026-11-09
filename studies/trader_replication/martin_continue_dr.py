"""DR: compare cached daily histories against the existing frozen Dataset."""
from collections import Counter
import csv
from itertools import groupby
import json
import math
import os
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trend_breakout.panel import factors
from studies.trader_replication.martin_continue_dq import ROOT, NAMES, sha, verify_files

FIELDS = ('open', 'high', 'low', 'close', 'volume', 'turnover')


def read_rows(path):
    rows = {}
    with path.open(newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            day = row['date'][:10]
            if day in rows:
                raise ValueError(f'duplicate day {path} {day}')
            try:
                rows[day] = [float(row[k]) for k in FIELDS]
            except (TypeError, ValueError):
                rows[day] = [float('nan')] * len(FIELDS)
    return rows


def positive(x):
    return math.isfinite(x) and x > 0


def record(stats, field, left, right, tolerance):
    stats[field + '_total'] += 1
    if left == 0:
        stats[field + '_left_zero'] += 1
    if right == 0:
        stats[field + '_right_zero'] += 1
    if left == 0 and right == 0:
        stats[field + '_both_zero'] += 1
    if not positive(left) or not positive(right):
        stats[field + '_invalid'] += 1
        stats[field + '_bad'] += 1
    elif abs(left / right - 1) > tolerance:
        stats[field + '_bad'] += 1


def raw_compare(source, frozen):
    source = {d: v for d, v in source.items() if '2023-01-01' <= d <= '2024-12-31'}
    frozen = {d: v for d, v in frozen.items() if '2023-01-01' <= d <= '2024-12-31'}
    stats = Counter(source_only=len(source.keys() - frozen.keys()), frozen_only=len(frozen.keys() - source.keys()),
                    common=len(source.keys() & frozen.keys()))
    for day in sorted(source.keys() & frozen.keys()):
        for k, field in enumerate(FIELDS):
            record(stats, field, source[day][k], frozen[day][k], .001)
    return stats


def adjusted_compare(raw, qfq, actions):
    raw = {d: v for d, v in raw.items() if '2022-09-29' <= d <= '2024-12-31'}
    qfq = {d: v for d, v in qfq.items() if '2022-09-29' <= d <= '2024-12-31'}
    days = sorted(raw)
    stats = Counter(raw_only=len(raw.keys() - qfq.keys()), qfq_only=len(qfq.keys() - raw.keys()))
    if not days:
        stats['no_anchor'] += 1
        return stats
    # Invalid raw closes cannot safely feed the panel factor calculation.
    if any(not positive(raw[d][3]) for d in days):
        stats['invalid_raw_close'] += 1
        return stats
    f = factors([raw[d][3] for d in days], np.array(days), actions)
    rebuilt = {d: [raw[d][k] * f[i] for k in range(4)] + [raw[d][4] / f[i]] for i, d in enumerate(days)}
    common = sorted(raw.keys() & qfq.keys())
    anchor = next((d for d in reversed(common) if all(positive(qfq[d][k]) and positive(rebuilt[d][k]) for k in range(5))), None)
    if anchor is None:
        stats['no_anchor'] += 1
        return stats
    for day in common:
        for k, field in enumerate(FIELDS[:5]):
            a, b, qa, ba = qfq[day][k], rebuilt[day][k], qfq[anchor][k], rebuilt[anchor][k]
            record(stats, day[:4] + '_' + field, a / qa, b / ba, .005)
    stats['common'] = len(common)
    return stats


def main():
    if os.environ.get('TRADER_DATA_MODE') != 'frozen' or os.environ.get('TRADER_DATA_TAG') != 'trader-data-v1':
        raise ValueError('explicitly select frozen v1')
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    available = {s['code'] for s in ds.stocks()}
    paths = {}
    inputs = {}
    for name in NAMES[:2]:
        folder = ROOT / 'data' / name
        verify_files(folder)
        inputs[name] = sha(folder / 'CHECKSUMS.sha256')
        for path in (folder / 'daily').glob('*.csv'):
            code = 'US.' + path.stem
            if code in paths:
                raise ValueError('duplicate source code ' + code)
            if code in available:
                paths[code] = folder
    actions = ds.actions()
    results = {}
    for code, rows in groupby(ds.rows(), key=lambda r: r[0]):
        if code not in paths:
            continue
        frozen = {}
        for _, day, values in rows:
            if day in frozen:
                raise ValueError('duplicate frozen day ' + code)
            frozen[day] = values
        name = code.removeprefix('US.') + '.csv'
        raw = read_rows(paths[code] / 'daily_none' / name)
        qfq = read_rows(paths[code] / 'daily' / name)
        results[code] = {'raw': dict(raw_compare(raw, frozen)),
                         'adjusted': dict(adjusted_compare(raw, qfq, actions.get(code, []))),
                         'actions_2022_2024': sum('2022-09-29' <= a[0] <= '2024-12-31' for a in actions.get(code, []))}
    missing = sorted(paths.keys() - results.keys())
    total_raw, total_adjusted = Counter(), Counter()
    for r in results.values():
        total_raw.update(r['raw'])
        total_adjusted.update(r['adjusted'])
    out = {'inputs': inputs, 'v1_digest': ds.digest(), 'script_sha256': sha(Path(__file__)),
           'expected_symbols': len(paths), 'symbols_read': len(results), 'missing_symbols': missing,
           'raw_totals': dict(total_raw), 'adjusted_totals': dict(total_adjusted), 'by_symbol': results}
    target = ROOT / 'studies/trader_replication/reports/gap_review/strong_continue_dr.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print('wrote', target, 'symbols', len(results), 'missing', len(missing), flush=True)


if __name__ == '__main__':
    main()
