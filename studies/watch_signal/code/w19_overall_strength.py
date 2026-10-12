"""W19 select one parameter-free stock-and-market directional strength score."""
import argparse
import csv
import gzip
import itertools
import json
import math
import resource
import time
from collections import defaultdict
from pathlib import Path

import w13_score as w13
import w15_market_score as w15
import w16_validate as w16
import w17_market_support as w17
import w18_market_support as w18

ROOT = Path(__file__).resolve().parents[3]
CANDIDATES = ('C1', 'C2', 'C3')


def events(path, hsi, hsi_references, start, end, excluded=frozenset()):
    seen = set()
    with gzip.open(path, 'rt', newline='') as fh:
        groups = itertools.groupby(csv.DictReader(fh), lambda row: (row['code'], row['time_key'][:10]))
        for key, group in groups:
            if key in seen:
                raise ValueError('non-contiguous stock-day: %r' % (key,))
            seen.add(key)
            code, day = key
            rows = list(group)
            if not start <= day <= end:
                raise ValueError('outside W19 window: %r' % (key,))
            if code == 'HK.800000' or code in excluded:
                continue
            if not rows or rows[0]['time_key'][11:16] != '09:30':
                raise ValueError('stock day does not start at 09:30: %r' % (key,))
            reference = float(rows[0]['last_close'])
            if not math.isfinite(reference) or reference <= 0:
                raise ValueError('invalid stock previous close: %r' % (key,))
            bars = [(row['time_key'], *w13.w12.checked_values(
                row, ('open', 'high', 'low', 'close', 'volume')))
                    for row in rows if row['time_key'][11:16] < '16:00']
            bars.sort()
            if len(bars) < 200:
                continue
            if len({bar[0] for bar in bars}) != len(bars):
                raise ValueError('duplicate minute: %r' % (key,))
            if day not in hsi:
                raise ValueError('missing HSI day: ' + day)
            features = w13.w12.corrected_features(bars)
            for mark in w13.w12.replica(bars, features, None, 'B0'):
                minute = mark['t']
                if minute not in hsi[day]:
                    raise ValueError('missing HSI minute: %s %s' % (day, minute))
                sign = 1 if mark['side'] == 'BUY' else -1
                yield (day, mark['side'], w18.bucket(minute),
                       sign * (mark['close'] / reference - 1),
                       sign * (hsi[day][minute] / hsi_references[day] - 1))


def combine(candidate, stock, market):
    if candidate == 'C1':
        return min(stock, market)
    if candidate == 'C2':
        return math.sqrt(stock * market)
    return (stock + market) / 2


def fit(train_events):
    stock, market = defaultdict(list), defaultdict(list)
    for _day, _side, group, stock_value, market_value in train_events:
        stock[group].append(stock_value)
        market[group].append(market_value)
    for values in list(stock.values()) + list(market.values()):
        values.sort()
    combined = {candidate: defaultdict(list) for candidate in CANDIDATES}
    for _day, _side, group, stock_value, market_value in train_events:
        stock_score = w17.percentile(stock[group], stock_value)
        market_score = w17.percentile(market[group], market_value)
        for candidate in CANDIDATES:
            combined[candidate][group].append(combine(candidate, stock_score, market_score))
    for candidate in CANDIDATES:
        for values in combined[candidate].values():
            values.sort()
    return stock, market, combined


def score(events_, fitted):
    stock, market, combined = fitted
    out = {candidate: [] for candidate in CANDIDATES}
    for day, side, group, stock_value, market_value in events_:
        stock_score = w17.percentile(stock[group], stock_value)
        market_score = w17.percentile(market[group], market_value)
        for candidate in CANDIDATES:
            raw = combine(candidate, stock_score, market_score)
            out[candidate].append((day, side, w17.percentile(combined[candidate][group], raw)))
    return out


def mean(rows):
    return sum(row[2] for row in rows) / len(rows)


def evaluate(rows, hsi, references):
    days = {row[0] for row in rows}
    market = {day: hsi[day][max(hsi[day])] / references[day] - 1 for day in days}
    ordered = sorted(days, key=lambda day: (market[day], day))
    extreme_days = {'DOWN': ordered[:10], 'UP': list(reversed(ordered[-10:]))}
    summaries, daily_checks = {}, []
    for regime, regime_days in extreme_days.items():
        selected = [row for row in rows if row[0] in regime_days]
        aligned_side = 'BUY' if regime == 'UP' else 'SELL'
        aligned = [row for row in selected if row[1] == aligned_side]
        opposed = [row for row in selected if row[1] != aligned_side]
        summaries[regime] = dict(
            days=regime_days, n=len(selected), aligned_side=aligned_side,
            aligned_mean=mean(aligned), opposed_mean=mean(opposed),
            all_mean=mean(selected), separation=mean(aligned) - mean(opposed))
        for day in regime_days:
            day_rows = [row for row in selected if row[0] == day]
            aligned_day = [row for row in day_rows if row[1] == aligned_side]
            opposed_day = [row for row in day_rows if row[1] != aligned_side]
            daily_checks.append(dict(
                day=day, regime=regime, hsi_return_pct=market[day] * 100,
                aligned_mean=mean(aligned_day), opposed_mean=mean(opposed_day),
                pass_day=mean(aligned_day) >= 65 and mean(aligned_day) - mean(opposed_day) >= 30))
    extreme_set = set(extreme_days['UP'] + extreme_days['DOWN'])
    extreme = [row for row in rows if row[0] in extreme_set]
    counts = {side: sum(row[1] == side for row in rows) for side in ('BUY', 'SELL')}
    up, down = summaries['UP'], summaries['DOWN']
    gates = dict(
        sample=min(counts.values()) >= 50000,
        centered=45 <= mean(rows) <= 55,
        regime_levels=(up['aligned_mean'] >= 70 and up['opposed_mean'] <= 40
                       and down['aligned_mean'] >= 70 and down['opposed_mean'] <= 40),
        separation=min(up['separation'], down['separation']) >= 40,
        extreme_overall=mean(extreme) >= 55,
        daily=sum(row['pass_day'] for row in daily_checks) >= 16)
    return dict(n=len(rows), counts=counts, overall_mean=mean(rows), extreme=summaries,
                extreme_all_mean=mean(extreme), daily_pass=sum(row['pass_day'] for row in daily_checks),
                daily_checks=daily_checks, gates=gates, pass_all=all(gates.values()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--train-bars', type=Path, default=ROOT / 'data/watch-hk1m-train-v1/bars_1m.csv.gz')
    parser.add_argument('--train-index', type=Path, default=ROOT / 'data/watch-hk-index1m-v1/index_1m.csv.gz')
    parser.add_argument('--selection-bars', type=Path,
                        default=ROOT / 'studies/watch_signal/data/w16_2024h2_1m.csv.gz')
    args = parser.parse_args()
    started = time.monotonic()
    train_hsi, train_refs = w15.load_hsi(args.train_index)
    train = list(events(args.train_bars, train_hsi, train_refs, '2025-12-01', '2026-08-14'))
    fitted = fit(train)
    bucket_counts = {str(group): len(values) for group, values in sorted(fitted[0].items())}
    quality = w16.quality_scan(args.selection_bars)
    hsi, refs = w15.load_hsi(args.selection_bars)
    selection = list(events(args.selection_bars, hsi, refs, '2024-06-03', '2024-11-29', set(quality)))
    scored = score(selection, fitted)
    results = {candidate: evaluate(scored[candidate], hsi, refs) for candidate in CANDIDATES}
    selected = next((candidate for candidate in CANDIDATES if results[candidate]['pass_all']), None)
    sample_gate = min(bucket_counts.values()) >= 2000
    if not sample_gate:
        selected = None
    print(json.dumps(w13.w12.clean(dict(
        definition='time-bucket percentile of joint stock and HSI directional support',
        candidates=dict(C1='weakest', C2='geometric', C3='mean'),
        training_n=len(train), training_bucket_counts=bucket_counts,
        training_sample_gate=sample_gate, selection_days=len({row[0] for row in selection}),
        excluded_invalid_codes=quality, results=results, selected=selected,
        elapsed_seconds=time.monotonic() - started,
        max_rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)),
        ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
