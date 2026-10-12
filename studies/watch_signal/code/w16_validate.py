"""W16 train M3/M4 on the old selection data, validate once on unseen 2024H2."""
import argparse
import csv
import gzip
import hashlib
import itertools
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
import w15_market_score as w15

ROOT = Path(__file__).resolve().parents[3]
START, END = '2024-06-03', '2024-11-29'
CANDIDATES = ('P1', 'P2', 'M1', 'M2', 'M3', 'M4')
EVALUATED = ('M3', 'M4')


def quality_scan(path):
    bad = defaultdict(lambda: [0, set()])
    with gzip.open(path, 'rt', newline='') as fh:
        for row in csv.DictReader(fh):
            try:
                values = [float(row[key] or 0) for key in ('open', 'high', 'low', 'close', 'volume')]
            except ValueError:
                values = [math.nan]
            if (len(values) != 5 or any(not math.isfinite(value) for value in values)
                    or any(value <= 0 for value in values[:4]) or values[4] < 0):
                bad[row['code']][0] += 1
                bad[row['code']][1].add(row['time_key'][:10])
    if 'HK.800000' in bad:
        raise ValueError('invalid HSI validation data')
    return {code: dict(bad_rows=count, bad_days=len(days)) for code, (count, days) in bad.items()}


def sessions(path, excluded):
    seen = set()
    with gzip.open(path, 'rt', newline='') as fh:
        for key, rows in itertools.groupby(csv.DictReader(fh), lambda row: (row['code'], row['time_key'][:10])):
            if key in seen:
                raise ValueError('non-contiguous stock-day: %r' % (key,))
            seen.add(key)
            if not START <= key[1] <= END:
                raise ValueError('outside W16 window: %r' % (key,))
            if key[0] == 'HK.800000' or key[0] in excluded:
                continue
            bars = [(row['time_key'], *w13.w12.checked_values(
                row, ('open', 'high', 'low', 'close', 'volume')))
                    for row in rows if row['time_key'][11:16] < '16:00']
            bars.sort()
            if len({bar[0] for bar in bars}) != len(bars):
                raise ValueError('duplicate minute: %r' % (key,))
            if len(bars) >= 200:
                yield key, bars


def training_counts(grouped):
    fitted = {candidate: defaultdict(w13.Count) for candidate in CANDIDATES}
    global_count = w13.Count()
    for (day, side, candidate, cell), count in grouped.items():
        fitted[candidate][cell].merge(count)
        if candidate == 'P1':
            global_count.merge(count)
        if candidate == 'M2':
            fitted['M3'][cell + (side,)].merge(count)
            fitted['M4'][cell[:2] + (side,) + cell[-2:]].merge(count)
    return global_count, fitted


def estimate(candidate, cell, fitted, base):
    count = fitted[candidate][cell]
    if count.n >= w13.MIN_CELL:
        return w13.probability(count)
    if candidate == 'M3':
        return estimate('M2', cell[:-1], fitted, base)
    if candidate == 'M4':
        return estimate('P1', cell[:2], fitted, base)
    return w15.estimate(candidate, cell, fitted, base)


def event_cells(mark, market_return):
    p1, p2, m1, m2 = w15.market_cells(mark, market_return)
    side = mark['side']
    return dict(P1=p1, P2=p2, M1=m1, M2=m2,
                M3=m2 + (side,), M4=p1 + (side,) + m2[-2:])


def validate(path, daily_path, fitted, base, excluded):
    hsi, references = w15.load_hsi(path)
    grouped = defaultdict(w13.Count)
    codes, days, processed = set(), set(), 0
    with tempfile.TemporaryDirectory(prefix='w16-validate-') as tmp:
        db = sqlite3.connect(str(Path(tmp) / 'daily.sqlite'))
        # W12's loader deliberately truncates at its later selection END, which
        # still includes every daily row needed for this older validation.
        w13.w12.daily_db(daily_path, db)
        for (code, day), bars in sessions(path, excluded):
            if day not in hsi:
                raise ValueError('missing validation HSI day: ' + day)
            context = w13.w12.daily_context(db, code, day)
            features = w13.w12.corrected_features(bars)
            for mark in w13.w12.replica(bars, features, context, 'B0'):
                i = mark['i']
                if i + 31 >= len(bars):
                    continue
                if mark['t'] not in hsi[day]:
                    raise ValueError('missing validation HSI minute: %s %s' % (day, mark['t']))
                sign = 1 if mark['side'] == 'BUY' else -1
                ret = sign * (bars[i + 31][4] / bars[i + 1][4] - 1)
                market_return = hsi[day][mark['t']] / references[day] - 1
                cells = event_cells(mark, market_return)
                for candidate in ('P2',) + EVALUATED:
                    p = estimate(candidate, cells[candidate], fitted, base)
                    grouped[(day, mark['side'], candidate, p)].add(ret)
            codes.add(code); days.add(day); processed += 1
        db.close()
    rows = [dict(day=day, side=side, candidate=candidate, p=p, base=base,
                 n=count.n, wins=count.wins, nret=count.nret, ret=count.ret)
            for (day, side, candidate, p), count in grouped.items()]
    return rows, dict(stock_days=processed, codes=len(codes), days=len(days),
                      first_day=min(days), last_day=max(days))


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def overall_summary(rows, candidate, p2_brier):
    summary = w13.summarize(rows, candidate)
    counts = summary['counts']
    gates = dict(
        sample=summary['days'] >= 100 and min(counts.values()) >= 50000,
        brier=summary['brier'] < summary['baseline_brier'] and summary['brier'] <= p2_brier,
        hit_slope=summary['hit_regression']['slope'] > 0 and summary['hit_regression']['t'] >= 2,
        return_slope=summary['return_bp_regression']['slope'] > 0
                     and summary['return_bp_regression']['t'] >= 2,
        both_sides=all(summary['side_hit_regression'][side]['slope'] > 0 for side in ('BUY', 'SELL')),
        calibrated=abs(summary['calibration_error_points']) <= 2 and summary['score_std'] >= .5)
    summary['w16_gates'] = gates
    summary['w16_pass'] = all(gates.values())
    return summary


def check_primitives():
    grouped = defaultdict(w13.Count)
    cell = ('2<=tpb<5', 'D+', 'BOS', 'aligned', 'strong')
    grouped[('2026-01-02', 'BUY', 'M2', cell)].add(.01)
    _, fitted = training_counts(grouped)
    assert fitted['M3'][cell + ('BUY',)].wins == 1
    assert fitted['M4'][('2<=tpb<5', 'D+', 'BUY', 'aligned', 'strong')].wins == 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--train-bars', type=Path, default=ROOT / 'data/watch-hk1m-train-v1/bars_1m.csv.gz')
    parser.add_argument('--train-index', type=Path, default=ROOT / 'data/watch-hk-index1m-v1/index_1m.csv.gz')
    parser.add_argument('--validation-bars', type=Path,
                        default=ROOT / 'studies/watch_signal/data/w16_2024h2_1m.csv.gz')
    parser.add_argument('--daily', type=Path,
                        default=ROOT / 'studies/watch_signal/data/day_2024-06_2026-09.csv.gz')
    args = parser.parse_args()
    check_primitives()
    started = time.monotonic()
    quality = quality_scan(args.validation_bars)
    train, train_days = w15.collect(args.train_bars, args.daily, args.train_index)
    global_count, fitted = training_counts(train)
    base = w13.probability(global_count)
    rows, coverage = validate(args.validation_bars, args.daily, fitted, base, set(quality))
    market = w14.hsi_returns(args.daily, {row['day'] for row in rows})
    ordered = sorted(market, key=lambda day: (market[day], day))
    extremes = {'DOWN': ordered[:10], 'UP': list(reversed(ordered[-10:]))}
    p2 = w13.summarize(rows, 'P2')
    extreme_p2 = w14.regime_summary([row for row in rows if row['candidate'] == 'P2'
                                     and row['day'] in set(extremes['UP'] + extremes['DOWN'])])
    results = []
    for candidate in EVALUATED:
        selected = [row for row in rows if row['candidate'] == candidate]
        overall = overall_summary(rows, candidate, p2['brier'])
        regimes = {name: w14.regime_summary([row for row in selected if row['day'] in days])
                   for name, days in extremes.items()}
        combined = w14.regime_summary([row for row in selected
                                       if row['day'] in set(extremes['UP'] + extremes['DOWN'])])
        stress = w15.extreme_gates(regimes['UP'], regimes['DOWN'], combined)
        extra = dict(extreme_brier=combined['brier'] <= extreme_p2['brier'],
                     regime_calibration=all(abs(regimes[name]['calibration_error_points']) <= 3
                                            for name in ('UP', 'DOWN')))
        results.append(dict(candidate=candidate, overall=overall, extreme=regimes,
                            extreme_combined=combined, extreme_gates=stress,
                            extra_gates=extra,
                            pass_all=overall['w16_pass'] and all(stress.values()) and all(extra.values())))
    passing = [result for result in results if result['pass_all']]
    picked = min(passing, key=lambda result: (result['overall']['brier'],
                                              0 if result['candidate'] == 'M4' else 1))['candidate'] if passing else None
    output = dict(train_stock_days=train_days, validation=coverage, excluded_invalid_codes=quality,
                  validation_file=str(args.validation_bars), validation_sha256=sha256(args.validation_bars),
                  elapsed_seconds=time.monotonic() - started,
                  max_rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                  extreme_dates={name: [dict(day=day, hsi_return_pct=market[day] * 100) for day in days]
                                 for name, days in extremes.items()},
                  baselines=dict(global_score=base * 100, p2=p2, extreme_p2=extreme_p2),
                  results=results, selected_for_future_validation=picked,
                  deployment_allowed=False)
    print(json.dumps(w13.w12.clean(output), ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
