"""W15 causal HSI-state score candidates and fixed extreme-day stress test."""
import argparse
import csv
import gzip
import json
import math
import resource
import sqlite3
import tempfile
import time
from collections import defaultdict
from pathlib import Path

import w13_score as w13
import w14_extreme as w14

ROOT = Path(__file__).resolve().parents[3]
CANDIDATES = ('P1', 'P2', 'M1', 'M2')
EVALUATED = ('M1', 'M2')


def load_hsi(path):
    raw = defaultdict(dict)
    references = {}
    with gzip.open(path, 'rt', newline='') as fh:
        for row in csv.DictReader(fh):
            if row['code'] != 'HK.800000':
                continue
            day, minute = row['time_key'][:10], row['time_key'][11:16]
            close, last = float(row['close']), float(row['last_close'])
            if not all(math.isfinite(x) and x > 0 for x in (close, last)):
                raise ValueError('invalid HSI minute: ' + row['time_key'])
            if minute in raw[day]:
                raise ValueError('duplicate HSI minute: ' + row['time_key'])
            raw[day][minute] = close
            if day not in references:
                if minute != '09:30':
                    raise ValueError('HSI day does not start at 09:30: ' + day)
                references[day] = last
    return raw, references


def market_cells(mark, market_return):
    p1, p2 = w13.cells(mark)
    sign = 1 if mark['side'] == 'BUY' else -1
    alignment = 'aligned' if sign * market_return >= 0 else 'opposed'
    magnitude = 'strong' if abs(market_return) >= 0.005 else 'weak'
    return p1, p2, p2 + (alignment,), p2 + (alignment, magnitude)


def collect(bars_path, daily_path, index_path):
    hsi, references = load_hsi(index_path)
    grouped = defaultdict(w13.Count)
    processed = 0
    with tempfile.TemporaryDirectory(prefix='w15-score-') as tmp:
        db = sqlite3.connect(str(Path(tmp) / 'daily.sqlite'))
        w13.w12.daily_db(daily_path, db)
        for (code, day), bars in w13.w12.sessions(bars_path):
            if day not in hsi:
                raise ValueError('missing HSI day: ' + day)
            context = w13.w12.daily_context(db, code, day)
            f = w13.w12.corrected_features(bars)
            for mark in w13.w12.replica(bars, f, context, 'B0'):
                i = mark['i']
                if i + 31 >= len(bars):
                    continue
                if mark['t'] not in hsi[day]:
                    raise ValueError('missing causal HSI minute: %s %s' % (day, mark['t']))
                sign = 1 if mark['side'] == 'BUY' else -1
                ret = sign * (bars[i + 31][4] / bars[i + 1][4] - 1)
                market_return = hsi[day][mark['t']] / references[day] - 1
                for candidate, cell in zip(CANDIDATES, market_cells(mark, market_return)):
                    grouped[(day, mark['side'], candidate, cell)].add(ret)
            processed += 1
        db.close()
    return grouped, processed


def fit_before(grouped, month):
    global_count = w13.Count()
    fitted = {candidate: defaultdict(w13.Count) for candidate in CANDIDATES}
    for (day, _side, candidate, cell), count in grouped.items():
        if day[:7] >= month:
            continue
        fitted[candidate][cell].merge(count)
        if candidate == 'P1':
            global_count.merge(count)
    return global_count, fitted


def estimate(candidate, cell, fitted, base):
    count = fitted[candidate][cell]
    if count.n >= w13.MIN_CELL:
        return w13.probability(count)
    if candidate == 'M2':
        return estimate('M1', cell[:-1], fitted, base)
    if candidate == 'M1':
        return estimate('P2', cell[:-1], fitted, base)
    if candidate == 'P2':
        return estimate('P1', cell[:2], fitted, base)
    return w13.probability(count) if count.n >= w13.MIN_CELL else base


def predictions(grouped):
    rows = []
    months = sorted({day[:7] for day, *_ in grouped if day[:7] >= w13.FIRST_PREDICT_MONTH})
    for month in months:
        global_count, fitted = fit_before(grouped, month)
        base = w13.probability(global_count)
        for (day, side, candidate, cell), count in grouped.items():
            if day[:7] == month and candidate in EVALUATED:
                rows.append(dict(day=day, side=side, candidate=candidate,
                                 p=estimate(candidate, cell, fitted, base), base=base,
                                 n=count.n, wins=count.wins, nret=count.nret, ret=count.ret))
    return rows


def extreme_gates(up, down, combined):
    return dict(
        sample=all(s['n'] >= 5000 and min(s['counts'].values()) >= 1000 for s in (up, down)),
        hit_slopes=all(s['hit_regression']['slope'] is not None and s['hit_regression']['slope'] > 0
                       for s in (up, down)),
        return_slopes=all(s['return_bp_regression']['slope'] is not None
                          and s['return_bp_regression']['slope'] > 0 for s in (up, down)),
        side_slopes=all(s['side_hit_regression'][side]['slope'] is not None
                        and s['side_hit_regression'][side]['slope'] > 0
                        for s in (up, down) for side in ('BUY', 'SELL')),
        brier=all(s['brier'] <= s['baseline_brier'] for s in (up, down)),
        combined_slopes=(combined['hit_regression']['slope'] is not None
                         and combined['hit_regression']['slope'] > 0
                         and combined['hit_regression']['t'] is not None
                         and combined['hit_regression']['t'] >= 2
                         and combined['return_bp_regression']['slope'] is not None
                         and combined['return_bp_regression']['slope'] > 0
                         and combined['return_bp_regression']['t'] is not None
                         and combined['return_bp_regression']['t'] >= 2),
        calibrated=abs(combined['calibration_error_points']) <= 2)


def check_primitives():
    mark = {'tpb': 3, 'daily': True, 'trigger': 'BOS', 'side': 'BUY'}
    cells = market_cells(mark, -0.006)
    assert cells[-2][-1] == 'opposed' and cells[-1][-2:] == ('opposed', 'strong')
    mark['side'] = 'SELL'
    assert market_cells(mark, -0.001)[-1][-2:] == ('aligned', 'weak')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bars', type=Path, default=ROOT / 'data/watch-hk1m-train-v1/bars_1m.csv.gz')
    parser.add_argument('--daily', type=Path, default=ROOT / 'studies/watch_signal/data/day_2024-06_2026-09.csv.gz')
    parser.add_argument('--index', type=Path, default=ROOT / 'data/watch-hk-index1m-v1/index_1m.csv.gz')
    args = parser.parse_args()
    check_primitives()
    started = time.monotonic()
    grouped, processed = collect(args.bars, args.daily, args.index)
    rows = predictions(grouped)
    eligible = {row['day'] for row in rows}
    market = w14.hsi_returns(args.daily, eligible)
    ordered = sorted(market, key=lambda day: (market[day], day))
    extreme_days = {'DOWN': ordered[:10], 'UP': list(reversed(ordered[-10:]))}
    results = []
    for candidate in EVALUATED:
        candidate_rows = [row for row in rows if row['candidate'] == candidate]
        overall = w13.summarize(rows, candidate)
        regimes = {name: w14.regime_summary([row for row in candidate_rows if row['day'] in days])
                   for name, days in extreme_days.items()}
        selected_days = set(extreme_days['UP'] + extreme_days['DOWN'])
        combined = w14.regime_summary([row for row in candidate_rows if row['day'] in selected_days])
        stress = extreme_gates(regimes['UP'], regimes['DOWN'], combined)
        results.append(dict(candidate=candidate, overall=overall, extreme=regimes,
                            extreme_combined=combined, extreme_gates=stress,
                            pass_all=overall['selection_pass'] and all(stress.values())))
    # Frozen P2 reference values from W13/W14 reports.
    for result in results:
        result['not_worse_than_p2'] = dict(
            overall_brier=result['overall']['brier'] <= 0.24879281555603347,
            extreme_brier=result['extreme_combined']['brier'] <= 0.24957187354904875)
        result['pass_all'] = result['pass_all'] and all(result['not_worse_than_p2'].values())
    passing = [r for r in results if r['pass_all']]
    picked = min(passing, key=lambda r: (r['extreme_combined']['brier'], EVALUATED.index(r['candidate'])))['candidate'] if passing else None
    output = dict(stock_days=processed, elapsed_seconds=time.monotonic() - started,
                  max_rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                  extreme_dates={name: [dict(day=day, hsi_return_pct=market[day] * 100) for day in days]
                                 for name, days in extreme_days.items()},
                  results=results, selected_for_future_validation=picked,
                  deployment_allowed=False)
    print(json.dumps(w13.w12.clean(output), ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
