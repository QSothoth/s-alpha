"""W14 fixed HSI extreme-day stress test for the frozen W13 P2 score."""
import argparse
import csv
import gzip
import json
import math
import resource
import time
from pathlib import Path

import w13_score as w13

ROOT = Path(__file__).resolve().parents[3]


def hsi_returns(path, eligible):
    returns = {}
    with gzip.open(path, 'rt', newline='') as fh:
        for row in csv.DictReader(fh):
            day = row['time_key'][:10]
            if row['code'] != 'HK.800000' or day not in eligible:
                continue
            close, previous = float(row['close']), float(row['last_close'])
            if not all(math.isfinite(x) and x > 0 for x in (close, previous)):
                raise ValueError('invalid HSI daily price: ' + day)
            if day in returns:
                raise ValueError('duplicate HSI daily row: ' + day)
            returns[day] = close / previous - 1
    missing = eligible - set(returns)
    if missing:
        raise ValueError('missing HSI days: ' + ','.join(sorted(missing)))
    return returns


def regime_summary(rows):
    n = sum(row['n'] for row in rows)
    wins = sum(row['wins'] for row in rows)
    predicted = sum(row['p'] * row['n'] for row in rows) / n
    loss = sum(row['wins'] * (1 - row['p']) ** 2 + (row['n'] - row['wins']) * row['p'] ** 2
               for row in rows) / n
    base_loss = sum(row['wins'] * (1 - row['base']) ** 2 + (row['n'] - row['wins']) * row['base'] ** 2
                    for row in rows) / n
    hit = w13.regression(rows, 'win')
    ret = w13.regression(rows, 'ret')
    side_hit = {side: w13.regression([row for row in rows if row['side'] == side], 'win')
                for side in ('BUY', 'SELL')}
    counts = {side: sum(row['n'] for row in rows if row['side'] == side) for side in ('BUY', 'SELL')}
    return dict(days=len({row['day'] for row in rows}), n=n, counts=counts,
                actual_pct=wins / n * 100, predicted_pct=predicted * 100,
                calibration_error_points=(wins / n - predicted) * 100,
                brier=loss, baseline_brier=base_loss,
                hit_regression=hit, return_bp_regression=ret, side_hit_regression=side_hit)


def check_primitives():
    rows = [dict(day='a', side='BUY', p=.6, base=.5, n=10, wins=6, nret=10, ret=.01),
            dict(day='b', side='SELL', p=.4, base=.5, n=10, wins=4, nret=10, ret=-.01)]
    summary = regime_summary(rows)
    assert summary['n'] == 20 and summary['counts'] == {'BUY': 10, 'SELL': 10}
    assert abs(summary['actual_pct'] - 50) < 1e-12


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bars', type=Path, default=ROOT / 'data/watch-hk1m-train-v1/bars_1m.csv.gz')
    parser.add_argument('--daily', type=Path, default=ROOT / 'studies/watch_signal/data/day_2024-06_2026-09.csv.gz')
    args = parser.parse_args()
    check_primitives()
    started = time.monotonic()
    grouped, processed = w13.collect(args.bars, args.daily)
    rows = [row for row in w13.predictions(grouped) if row['candidate'] == 'P2']
    eligible = {row['day'] for row in rows}
    market = hsi_returns(args.daily, eligible)
    ordered = sorted(market, key=lambda day: (market[day], day))
    days = {'DOWN': ordered[:10], 'UP': list(reversed(ordered[-10:]))}
    summaries = {name: regime_summary([row for row in rows if row['day'] in selected])
                 for name, selected in days.items()}
    combined = regime_summary([row for row in rows if row['day'] in set(days['UP'] + days['DOWN'])])
    up, down = summaries['UP'], summaries['DOWN']
    gates = dict(
        sample=all(s['n'] >= 5000 and min(s['counts'].values()) >= 1000 for s in (up, down)),
        hit_slopes=all(s['hit_regression']['slope'] is not None and s['hit_regression']['slope'] > 0
                       for s in (up, down)),
        return_slopes=all(s['return_bp_regression']['slope'] is not None and s['return_bp_regression']['slope'] > 0
                          for s in (up, down)),
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
    output = dict(definition='top/bottom 10 HSI close-to-last-close returns',
                  stock_days=processed, elapsed_seconds=time.monotonic() - started,
                  max_rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                  dates={name: [dict(day=day, hsi_return_pct=market[day] * 100) for day in selected]
                         for name, selected in days.items()},
                  summaries=summaries, combined=combined, gates=gates,
                  stress_pass=all(gates.values()), deployment_allowed=False)
    print(json.dumps(w13.w12.clean(output), ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
