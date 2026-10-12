"""W18 market-support percentile with the 12:00 close merged into 11:30."""
import argparse
import csv
import gzip
import itertools
import json
import resource
import time
from pathlib import Path

import w13_score as w13
import w14_extreme as w14
import w15_market_score as w15
import w16_validate as w16
import w17_market_support as w17

ROOT = Path(__file__).resolve().parents[3]
START, END = '2024-12-02', '2025-05-30'


def bucket(minute):
    return 23 if minute == '12:00' else w17.bucket(minute)


def sessions(path, excluded):
    seen = set()
    with gzip.open(path, 'rt', newline='') as fh:
        for key, rows in itertools.groupby(csv.DictReader(fh), lambda row: (row['code'], row['time_key'][:10])):
            if key in seen:
                raise ValueError('non-contiguous stock-day: %r' % (key,))
            seen.add(key)
            if not START <= key[1] <= END:
                raise ValueError('outside W18 window: %r' % (key,))
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


def mean(rows):
    return sum(row[2] for row in rows) / len(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--train-bars', type=Path, default=ROOT / 'data/watch-hk1m-train-v1/bars_1m.csv.gz')
    parser.add_argument('--train-index', type=Path, default=ROOT / 'data/watch-hk-index1m-v1/index_1m.csv.gz')
    parser.add_argument('--validation-bars', type=Path,
                        default=ROOT / 'studies/watch_signal/data/w18_2024-12_2025-05_1m.csv.gz')
    parser.add_argument('--daily', type=Path,
                        default=ROOT / 'studies/watch_signal/data/day_2024-06_2026-09.csv.gz')
    args = parser.parse_args()
    assert bucket('11:59') == bucket('12:00') == 23 and bucket('13:00') == 26
    started = time.monotonic()
    train_hsi, train_refs = w15.load_hsi(args.train_index)
    distributions = {}
    values = {}
    from collections import defaultdict
    values = defaultdict(list)
    for _day, _side, group, support in w17.events(
            w13.w12.sessions(args.train_bars), train_hsi, train_refs, bucket_fn=bucket):
        values[group].append(support)
    for group, items in values.items():
        distributions[group] = sorted(items)

    quality = w16.quality_scan(args.validation_bars)
    hsi, references = w15.load_hsi(args.validation_bars)
    scored = []
    for day, side, group, support in w17.events(
            sessions(args.validation_bars, set(quality)), hsi, references, bucket_fn=bucket):
        scored.append((day, side, w17.percentile(distributions[group], support)))
    market = w14.hsi_returns(args.daily, {row[0] for row in scored})
    ordered = sorted(market, key=lambda day: (market[day], day))
    extreme_days = {'DOWN': ordered[:10], 'UP': list(reversed(ordered[-10:]))}
    summaries, daily_checks = {}, []
    for regime, days in extreme_days.items():
        rows = [row for row in scored if row[0] in days]
        aligned_side = 'BUY' if regime == 'UP' else 'SELL'
        aligned = [row for row in rows if row[1] == aligned_side]
        opposed = [row for row in rows if row[1] != aligned_side]
        summaries[regime] = dict(n=len(rows), aligned_side=aligned_side,
                                 aligned_n=len(aligned), opposed_n=len(opposed),
                                 aligned_mean=mean(aligned), opposed_mean=mean(opposed),
                                 all_mean=mean(rows), separation=mean(aligned) - mean(opposed))
        for day in days:
            day_rows = [row for row in rows if row[0] == day]
            aligned_day = [row for row in day_rows if row[1] == aligned_side]
            opposed_day = [row for row in day_rows if row[1] != aligned_side]
            daily_checks.append(dict(day=day, regime=regime, hsi_return_pct=market[day] * 100,
                                     aligned_mean=mean(aligned_day), opposed_mean=mean(opposed_day),
                                     pass_day=(mean(aligned_day) >= 60
                                               and mean(aligned_day) - mean(opposed_day) >= 20)))
    extreme_set = set(extreme_days['UP'] + extreme_days['DOWN'])
    extreme_all = [row for row in scored if row[0] in extreme_set]
    counts = {side: sum(row[1] == side for row in scored) for side in ('BUY', 'SELL')}
    bucket_counts = {str(group): len(items) for group, items in sorted(distributions.items())}
    up, down = summaries['UP'], summaries['DOWN']
    gates = dict(
        sample=min(bucket_counts.values()) >= 2000 and min(counts.values()) >= 50000,
        centered=47 <= mean(scored) <= 53,
        regime_levels=(up['aligned_mean'] >= 60 and up['opposed_mean'] <= 40
                       and down['aligned_mean'] >= 60 and down['opposed_mean'] <= 40),
        separation=min(up['separation'], down['separation']) >= 30,
        extreme_overall=mean(extreme_all) >= 55,
        daily=sum(row['pass_day'] for row in daily_checks) >= 16)
    output = dict(definition='W17 percentile; 12:00 merged into 11:30 bucket',
                  validation_window=[START, END], validation_days=len({row[0] for row in scored}),
                  n=len(scored), counts=counts, overall_mean=mean(scored),
                  training_bucket_counts=bucket_counts, excluded_invalid_codes=quality,
                  extreme=summaries, extreme_all_mean=mean(extreme_all), daily_checks=daily_checks,
                  gates=gates, pass_all=all(gates.values()), predictive_claim_allowed=False,
                  elapsed_seconds=time.monotonic() - started,
                  max_rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
    print(json.dumps(w13.w12.clean(output), ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
