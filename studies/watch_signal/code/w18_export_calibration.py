"""Freeze W18 integer percentile boundaries and verify the live replica."""
import argparse
import bisect
import importlib.util
import pprint
from collections import defaultdict
from pathlib import Path

import w13_score as w13
import w15_market_score as w15
import w17_market_support as w17
import w18_market_support as w18

ROOT = Path(__file__).resolve().parents[3]


def boundaries(values):
    """100 monotone cut points reproduce rounded empirical percentiles."""
    unique = list(dict.fromkeys(values))
    result = []
    for target in range(1, 101):
        lo, hi = 0, len(unique)
        while lo < hi:
            mid = (lo + hi) // 2
            score = round(100 * bisect.bisect_right(values, unique[mid]) / len(values))
            if score >= target:
                hi = mid
            else:
                lo = mid + 1
        result.append(unique[lo])
    return tuple(result)


def module_text(cuts):
    literal = pprint.pformat(cuts, width=110, sort_dicts=True)
    return '''"""Frozen W18 market-support calibration; generated, do not hand edit."""
from bisect import bisect_right
from math import isfinite

CUTS = %s


def time_bucket(minute):
    if minute == '12:00':
        return 23
    hour, minute = map(int, minute.split(':'))
    return (hour * 60 + minute) // 30


def score(side, minute, hsi_close, previous_close):
    """0-100 market support, or None when the causal HSI input is unavailable."""
    if side not in ('BUY', 'SELL') or not all(
            isfinite(x) and x > 0 for x in (hsi_close, previous_close)):
        return None
    cuts = CUTS.get(time_bucket(minute))
    if cuts is None:
        return None
    support = (1 if side == 'BUY' else -1) * (hsi_close / previous_close - 1)
    return bisect_right(cuts, support)


assert time_bucket('11:59') == time_bucket('12:00') == 23
''' % literal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'watch/market_support.py')
    args = parser.parse_args()
    hsi, refs = w15.load_hsi(ROOT / 'data/watch-hk-index1m-v1/index_1m.csv.gz')
    distributions = defaultdict(list)
    for _day, _side, group, value in w17.events(
            w13.w12.sessions(ROOT / 'data/watch-hk1m-train-v1/bars_1m.csv.gz'),
            hsi, refs, bucket_fn=w18.bucket):
        distributions[group].append(value)
    for values in distributions.values():
        values.sort()
    cuts = {group: boundaries(values) for group, values in sorted(distributions.items())}
    args.output.write_text(module_text(cuts), encoding='utf-8')

    spec = importlib.util.spec_from_file_location('market_support_frozen', args.output)
    frozen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(frozen)
    validation = ROOT / 'studies/watch_signal/data/w18_2024-12_2025-05_1m.csv.gz'
    validation_hsi, validation_refs = w15.load_hsi(validation)
    total = mismatches = 0
    for day, side, group, value in w17.events(
            w18.sessions(validation, set()), validation_hsi, validation_refs,
            bucket_fn=w18.bucket):
        minute_close = validation_refs[day] * (1 + value * (1 if side == 'BUY' else -1))
        expected = round(w17.percentile(distributions[group], value))
        actual = frozen.score(side, '12:00' if group == 23 else '%02d:%02d' % divmod(group * 30, 60),
                              minute_close, validation_refs[day])
        total += 1
        mismatches += actual != expected
    if mismatches:
        raise AssertionError('%d/%d frozen-score mismatches' % (mismatches, total))
    print('wrote %s; %d/%d mismatches' % (args.output, mismatches, total))


if __name__ == '__main__':
    main()
