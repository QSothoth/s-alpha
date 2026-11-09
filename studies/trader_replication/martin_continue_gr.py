"""GR: recent positive fast-move frequency in original turnover strata."""
from collections import Counter, defaultdict
from itertools import groupby
import bisect
import json
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trader_replication import panels
from studies.trader_replication import martin_continue_ee as ee
from studies.trader_replication import martin_continue_fj as fj
from studies.trader_replication import martin_continue_fz as fz
from studies.trader_replication import martin_continue_gc as gc
from studies.trader_replication.martin_continue_du import REPORTS
from studies.trader_replication.martin_continue_dq import sha
from studies.trend_breakout.panel import factors

SEED, WINDOW, THRESHOLD, TOL = 20261109, 21, .05, 1e-10
CUTS = fz.CUTS


def fast_counts(days, indices, records, actions, signals):
    dates = [r[0] for r in records]
    closes = np.array([r[1][3] for r in records], dtype=float)
    stock_idx = np.array([indices[d] for d in dates], dtype=int)
    where = {d: i for i, d in enumerate(dates)}
    steps = np.ones(len(dates), dtype=float)
    for day, a, b in actions:
        i = bisect.bisect_left(dates, day)
        if 0 < i < len(dates):
            previous = closes[i - 1]
            factor = (a * previous + b) / previous if np.isfinite(previous) and previous > 0 else np.nan
            steps[i] *= factor if np.isfinite(factor) and factor > 0 else np.nan
    invalid = np.ones(len(dates), dtype=bool)
    hit = np.zeros(len(dates), dtype=bool)
    if len(dates) > 1:
        base = closes[:-1] * steps[1:]
        valid = ((np.diff(stock_idx) == 1) & np.isfinite(closes[1:]) & (closes[1:] > 0) &
                 np.isfinite(base) & (base > 0))
        with np.errstate(divide='ignore', invalid='ignore'):
            change = closes[1:] / base - 1
        valid &= np.isfinite(change) & (np.abs(change - THRESHOLD) > TOL)
        invalid[1:] = ~valid
        hit[1:] = valid & (change > THRESHOLD)
    ps = np.r_[0, np.cumsum(hit)]
    bad = np.r_[0, np.cumsum(invalid)]
    result = {}
    for day in signals:
        i = where.get(day)
        result[day] = (int(ps[i + 1] - ps[i + 1 - WINDOW])
                       if i is not None and i >= WINDOW and bad[i + 1] == bad[i + 1 - WINDOW] else None)
    return result


def truncated_count(days, indices, records, actions, day):
    rows = [(date, values) for date, values in records if date <= day]
    dates = [date for date, _ in rows]
    if day not in dates or indices[day] < WINDOW:
        return None
    i = dates.index(day)
    if i < WINDOW or [indices[x] for x in dates[i - WINDOW:i + 1]] != list(range(indices[day] - WINDOW, indices[day] + 1)):
        return None
    closes = np.array([r[3] for _, r in rows], dtype=float)
    with np.errstate(invalid='ignore', divide='ignore'):
        adjusted = closes * factors(closes, np.array(dates), [a for a in actions if a[0] <= day])
        window = adjusted[i - WINDOW:i + 1]
        change = window[1:] / window[:-1] - 1
    if not (np.all(np.isfinite(window)) and np.all(window > 0) and np.all(np.isfinite(change)) and
            np.all(np.abs(change - THRESHOLD) > TOL)):
        return None
    return int(np.count_nonzero(change > THRESHOLD))


def label_group(rows, feature='count', output='fast'):
    known = sorted(r[feature] for r in rows if r[feature] is not None)
    boundary = known[(2 * (len(known) - 1)) // 3] if known else None
    for row in rows:
        row[output] = None if row[feature] is None else row[feature] > boundary
    return boundary


def outcome_summary(rows, conditional):
    eligible = [r for r in rows if not conditional or r['status'] == 'filled']
    result = {'orders': len(rows), 'status': dict(Counter(r['status'] for r in rows))}
    for metric in ('hit3', 'hit5', 'hit30'):
        valid = [r[metric] for r in eligible if r[metric] is not None]
        result[metric] = {'known': len(valid), 'unknown': len(eligible) - len(valid), 'hits': sum(valid),
                          'rate': sum(valid) / len(valid) if valid else None}
    return result


def main():
    fp, cp = REPORTS / 'strong_continue_fj.json', REPORTS / 'strong_continue_gc.json'
    a, b = json.loads(fp.read_text()), json.loads(cp.read_text())
    if (a['script_sha256'] != sha(Path(fj.__file__)) or b['script_sha256'] != sha(Path(gc.__file__)) or
            b['fj_sha256'] != sha(fp)):
        raise ValueError('reference source differs')
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    dataset_digest = ds.digest()
    if any(x['dataset_digest'] != dataset_digest for x in (a, b)):
        raise ValueError('dataset differs')
    rows, price = a['rows'], b['rows']
    del a, b
    if len(rows) != 57269 or len(price) != len(rows):
        raise ValueError('candidate count differs')
    for row, extra in zip(rows, price):
        if (row['signal_day'], row['code']) != (extra['signal_day'], extra['code']):
            raise ValueError('candidate identity differs')
        row['hit30'] = extra['hit30']
    del price
    stocks = {s['code'] for s in ds.stocks()}
    calendar = sorted({day for code, day, _ in ds.rows() if code in stocks and day <= panels.WINDOW[1]})
    index = {day: i for i, day in enumerate(calendar)}
    signals = defaultdict(set)
    for row in rows:
        if index.get(row['signal_day']) != row['day_index']:
            raise ValueError('calendar differs')
        signals[row['code']].add(row['signal_day'])
    actions, features, truncated, seen = ds.actions(), {}, {}, set()
    for code, group in groupby(ds.rows(), key=lambda r: r[0]):
        if code not in signals:
            continue
        seen.add(code)
        records = [(day, values) for _, day, values in group if day <= panels.WINDOW[1]]
        features.update(((code, day), value) for day, value in
                        fast_counts(calendar, index, records, actions.get(code, []), signals[code]).items())
        for day in signals[code].intersection(CUTS):
            truncated[(code, day)] = truncated_count(calendar, index, records, actions.get(code, []), day)
    if seen != set(signals):
        raise ValueError('missing candidate symbol')
    by_day = defaultdict(list)
    for row in rows:
        row['count'] = features[(row['code'], row['signal_day'])]
        by_day[row['signal_day']].append(row)
    for group in by_day.values():
        label_group(group)
    cuts = {}
    for day in CUTS:
        sample = by_day[day]
        independent = [{'code': r['code'], 'count': truncated[(r['code'], day)]} for r in sample]
        label_group(independent)
        by_code = {r['code']: r for r in independent}
        values = sum(r['count'] != by_code[r['code']]['count'] for r in sample)
        ranks = sum(r['fast'] != by_code[r['code']]['fast'] for r in sample)
        cuts[day] = {'candidates': len(sample), 'known': sum(r['count'] is not None for r in sample),
                     'count_mismatch': values, 'group_mismatch': ranks,
                     'passed': bool(sample) and values == ranks == 0}
    output, rng = {}, np.random.default_rng(SEED)
    for year in ('2024', '2025', '2026'):
        year_days = [i for i in range(len(calendar) - 1) if panels.WINDOW[0] <= calendar[i + 1] <= panels.WINDOW[1]
                     and calendar[i + 1].startswith(year)]
        annual = [r for r in rows if r['year'] == year]
        result = {'candidates': len(annual), 'feature_unknown': sum(r['count'] is None for r in annual), 'strata': {}}
        for stratum, selected in (('original_top4', True), ('others', False)):
            base = [r for r in annual if r['selected'] == selected and r['fast'] is not None]
            result['strata'][stratum] = {}
            for sample in ('all', 'spaced'):
                subset = [{**r, 'selected': r['fast']} for r in base if sample == 'all' or r['spaced']]
                result['strata'][stratum][sample] = {}
                for mode, conditional in (('per_preselected', False), ('per_filled', True)):
                    matches = {m: fj.matched(subset, year_days, m, conditional, rng)
                               for m in ('hit3', 'hit5', 'hit30')}
                    result['strata'][stratum][sample][mode] = {
                        'fast': outcome_summary([r for r in subset if r['fast']], conditional),
                        'other': outcome_summary([r for r in subset if not r['fast']], conditional),
                        'matched': matches}
        output[year] = result
    result = {'dataset_digest': dataset_digest, 'fj_sha256': sha(fp), 'gc_sha256': sha(cp),
              'ee_sha256': sha(Path(ee.__file__)), 'script_sha256': sha(Path(__file__)),
              'seed': SEED, 'cuts': cuts, 'results': output,
              'rows': [{'signal_day': r['signal_day'], 'code': r['code'], 'count': r['count'],
                        'fast': r['fast']} for r in rows]}
    target = REPORTS / 'strong_continue_gr.json'
    target.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
