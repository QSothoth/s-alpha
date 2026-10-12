"""Freeze compact W19 C1 thresholds and verify the live integer replica."""
import argparse
import bisect
import importlib.util
import math
import pprint
from pathlib import Path

import w15_market_score as w15
import w16_validate as w16
import w17_market_support as w17
import w19_overall_strength as w19

ROOT = Path(__file__).resolve().parents[3]


def boundary(values, target, scale=1):
    unique = list(dict.fromkeys(values))
    lo, hi = 0, len(unique)
    while lo < hi:
        mid = (lo + hi) // 2
        after = scale * bisect.bisect_right(values, unique[mid]) / len(values)
        if after >= target:
            hi = mid
        else:
            lo = mid + 1
    value = unique[lo]
    left = bisect.bisect_left(values, value)
    right = bisect.bisect_right(values, value)
    equal = scale * (left + right) / (2 * len(values))
    return value, equal >= target


def final_boundaries(values):
    unique = list(dict.fromkeys(values))
    result = []
    for target in range(1, 101):
        lo, hi = 0, len(unique)
        while lo < hi:
            mid = (lo + hi) // 2
            after = round(100 * bisect.bisect_right(values, unique[mid]) / len(values))
            if after >= target:
                hi = mid
            else:
                lo = mid + 1
        value = unique[lo]
        equal = round(w17.percentile(values, value))
        result.append((value, equal >= target))
    return result


def raw_cut(values, percentile, inclusive):
    # z >= p maps to component percentile >= p; z > p maps to > p.
    target = percentile if inclusive else math.nextafter(percentile, math.inf)
    return boundary(values, target, 100)


def thresholds(fitted):
    stock, market, combined = fitted
    return {group: tuple((*raw_cut(stock[group], percentile, inclusive),
                          *raw_cut(market[group], percentile, inclusive))
                         for percentile, inclusive in final_boundaries(combined['C1'][group]))
            for group in sorted(stock)}


def module_text(cuts):
    literal = pprint.pformat(cuts, width=110, sort_dicts=True)
    return '''"""Frozen W19 overall signal-strength calibration; generated, do not hand edit."""
from math import isfinite

CUTS = %s


def time_bucket(minute):
    if minute == '12:00':
        return 23
    hour, minute = map(int, minute.split(':'))
    return (hour * 60 + minute) // 30


def score(side, minute, stock_close, stock_previous, hsi_close, hsi_previous):
    """0-100 joint directional strength, or None when an input is unavailable."""
    values = (stock_close, stock_previous, hsi_close, hsi_previous)
    if side not in ('BUY', 'SELL') or not all(isfinite(x) and x > 0 for x in values):
        return None
    cuts = CUTS.get(time_bucket(minute))
    if cuts is None:
        return None
    sign = 1 if side == 'BUY' else -1
    stock = sign * (stock_close / stock_previous - 1)
    market = sign * (hsi_close / hsi_previous - 1)
    return sum((stock >= stock_cut if stock_inclusive else stock > stock_cut)
               and (market >= market_cut if market_inclusive else market > market_cut)
               for stock_cut, stock_inclusive, market_cut, market_inclusive in cuts)


assert time_bucket('11:59') == time_bucket('12:00') == 23
''' % literal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'watch/signal_strength.py')
    parser.add_argument('--validation-bars', type=Path,
                        default=ROOT / 'studies/watch_signal/data/w19_2024h1_1m.csv.gz')
    args = parser.parse_args()
    train_hsi, train_refs = w15.load_hsi(ROOT / 'data/watch-hk-index1m-v1/index_1m.csv.gz')
    train = list(w19.events(ROOT / 'data/watch-hk1m-train-v1/bars_1m.csv.gz',
                            train_hsi, train_refs, '2025-12-01', '2026-08-14'))
    fitted = w19.fit(train)
    args.output.write_text(module_text(thresholds(fitted)), encoding='utf-8')

    spec = importlib.util.spec_from_file_location('signal_strength_frozen', args.output)
    frozen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(frozen)
    quality = w16.quality_scan(args.validation_bars)
    hsi, refs = w15.load_hsi(args.validation_bars)
    validation = list(w19.events(
        args.validation_bars, hsi, refs, '2024-01-02', '2024-05-31', set(quality)))
    expected = w19.score(validation, fitted)['C1']
    mismatches = 0
    for event, row in zip(validation, expected):
        day, side, group, stock_value, market_value = event
        sign = 1 if side == 'BUY' else -1
        stock_close = refs[day]  # overwritten below using the exact raw ratio
        stock_previous = 1.0
        stock_close = 1 + stock_value * sign
        hsi_close = 1 + market_value * sign
        minute = '12:00' if group == 23 else '%02d:%02d' % divmod(group * 30, 60)
        actual = frozen.score(side, minute, stock_close, stock_previous, hsi_close, 1.0)
        mismatches += actual != round(row[2])
    if mismatches:
        raise AssertionError('%d/%d frozen-score mismatches' % (mismatches, len(validation)))
    print('wrote %s; %d/%d mismatches' % (args.output, mismatches, len(validation)))


if __name__ == '__main__':
    main()
