"""W17 causal market-support percentile; deliberately not a return predictor."""
import argparse
import bisect
import json
import math
import resource
import time
from collections import defaultdict
from pathlib import Path

import w13_score as w13
import w14_extreme as w14
import w15_market_score as w15
import w16_validate as w16

ROOT = Path(__file__).resolve().parents[3]


def bucket(minute):
    hour, minute = map(int, minute.split(':'))
    return (hour * 60 + minute) // 30


def events(sessions, hsi, references, excluded=frozenset(), bucket_fn=bucket):
    for (code, day), bars in sessions:
        if code in excluded:
            continue
        if day not in hsi:
            raise ValueError('missing HSI day: ' + day)
        features = w13.w12.corrected_features(bars)
        for mark in w13.w12.replica(bars, features, None, 'B0'):
            minute = mark['t']
            if minute not in hsi[day]:
                raise ValueError('missing HSI minute: %s %s' % (day, minute))
            sign = 1 if mark['side'] == 'BUY' else -1
            support = sign * (hsi[day][minute] / references[day] - 1)
            yield day, mark['side'], bucket_fn(minute), support


def percentile(sorted_values, value):
    left = bisect.bisect_left(sorted_values, value)
    right = bisect.bisect_right(sorted_values, value)
    return 100 * (left + right) / (2 * len(sorted_values))


def mean(rows):
    return sum(score for _day, _side, score in rows) / len(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--train-bars', type=Path, default=ROOT / 'data/watch-hk1m-train-v1/bars_1m.csv.gz')
    parser.add_argument('--train-index', type=Path, default=ROOT / 'data/watch-hk-index1m-v1/index_1m.csv.gz')
    parser.add_argument('--validation-bars', type=Path,
                        default=ROOT / 'studies/watch_signal/data/w16_2024h2_1m.csv.gz')
    parser.add_argument('--daily', type=Path,
                        default=ROOT / 'studies/watch_signal/data/day_2024-06_2026-09.csv.gz')
    args = parser.parse_args()
    assert bucket('09:30') == 19 and bucket('10:00') == 20
    assert percentile([0, 1, 1, 2], 1) == 50
    started = time.monotonic()

    train_hsi, train_refs = w15.load_hsi(args.train_index)
    distributions = defaultdict(list)
    for _day, _side, group, support in events(w13.w12.sessions(args.train_bars), train_hsi, train_refs):
        distributions[group].append(support)
    for values in distributions.values():
        values.sort()

    quality = w16.quality_scan(args.validation_bars)
    validation_hsi, validation_refs = w15.load_hsi(args.validation_bars)
    scored = []
    for day, side, group, support in events(
            w16.sessions(args.validation_bars, set(quality)), validation_hsi, validation_refs):
        if group not in distributions:
            raise ValueError('unseen time bucket: %s' % group)
        scored.append((day, side, percentile(distributions[group], support)))

    market = w14.hsi_returns(args.daily, {day for day, _side, _score in scored})
    ordered = sorted(market, key=lambda day: (market[day], day))
    extreme_days = {'DOWN': ordered[:10], 'UP': list(reversed(ordered[-10:]))}
    summaries = {}
    daily_checks = []
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
            a = [row for row in day_rows if row[1] == aligned_side]
            o = [row for row in day_rows if row[1] != aligned_side]
            daily_checks.append(dict(day=day, regime=regime, hsi_return_pct=market[day] * 100,
                                     aligned_mean=mean(a), opposed_mean=mean(o),
                                     pass_day=mean(a) >= 60 and mean(a) - mean(o) >= 20))
    extreme_set = set(extreme_days['UP'] + extreme_days['DOWN'])
    extreme_all = [row for row in scored if row[0] in extreme_set]
    counts = {side: sum(row[1] == side for row in scored) for side in ('BUY', 'SELL')}
    bucket_counts = {str(group): len(values) for group, values in sorted(distributions.items())}
    up, down = summaries['UP'], summaries['DOWN']
    gates = dict(
        sample=min(bucket_counts.values()) >= 2000 and min(counts.values()) >= 50000,
        centered=47 <= mean(scored) <= 53,
        regime_levels=(up['aligned_mean'] >= 60 and up['opposed_mean'] <= 40
                       and down['aligned_mean'] >= 60 and down['opposed_mean'] <= 40),
        separation=min(up['separation'], down['separation']) >= 30,
        extreme_overall=mean(extreme_all) >= 55,
        daily=sum(row['pass_day'] for row in daily_checks) >= 16)
    output = dict(definition='same-30-minute-bucket percentile of side * causal HSI return',
                  validation_days=len({row[0] for row in scored}), n=len(scored), counts=counts,
                  overall_mean=mean(scored), training_bucket_counts=bucket_counts,
                  excluded_invalid_codes=quality, extreme=summaries,
                  extreme_all_mean=mean(extreme_all), daily_checks=daily_checks,
                  gates=gates, pass_all=all(gates.values()), predictive_claim_allowed=False,
                  elapsed_seconds=time.monotonic() - started,
                  max_rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
    print(json.dumps(w13.w12.clean(output), ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
