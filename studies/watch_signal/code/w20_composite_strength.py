"""W20 select a composite B/S strength from trend, structure and HSI context."""
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

import numpy as np

import w13_score as w13
import w15_market_score as w15
import w16_validate as w16
import w17_market_support as w17
import w18_market_support as w18

ROOT = Path(__file__).resolve().parents[3]
CANDIDATES = ('C1', 'C2', 'C3')
TRIGGERS = ('BOS', 'FVG', 'SWEEP')


def structure_values(mark, f):
    i = mark['i']
    sign = 1 if mark['side'] == 'BUY' else -1
    atr = float(f['atr'][i])
    values = []
    for trigger in mark['trigger'].split('+'):
        if trigger == 'BOS':
            pivot = f['sh'][i] if sign > 0 else f['sl'][i]
            value = sign * (f['c'][i] - pivot) / atr
        elif trigger == 'FVG':
            value = ((f['l'][i] - f['h'][i - 2]) if sign > 0
                     else (f['l'][i - 2] - f['h'][i])) / atr
        elif trigger == 'SWEEP':
            value = ((f['sl'][i] - f['l'][i]) if sign > 0
                     else (f['h'][i] - f['sh'][i])) / atr
        else:
            raise ValueError('unknown trigger: ' + trigger)
        if not math.isfinite(value) or value < 0:
            raise ValueError('invalid structure strength: %s %s' % (trigger, value))
        values.append((trigger, float(value)))
    return tuple(values)


def events(path, hsi, references, start, end, excluded=frozenset()):
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
                raise ValueError('outside W20 window: %r' % (key,))
            if code == 'HK.800000' or code in excluded:
                continue
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
            f = w13.w12.corrected_features(bars)
            for mark in w13.w12.replica(bars, f, None, 'B0'):
                i = mark['i']
                if mark['t'] not in hsi[day]:
                    raise ValueError('missing HSI minute: %s %s' % (day, mark['t']))
                sign = 1 if mark['side'] == 'BUY' else -1
                atr = float(f['atr'][i])
                trend = (sign * (f['c'][i] - f['vwap'][i]) / atr,
                         sign * (f['ema9'][i] - f['ema21'][i]) / atr,
                         sign * (f['rsi'][i] - 50))
                if any(not math.isfinite(value) or value < 0 for value in trend):
                    raise ValueError('invalid trend strength: %r' % (trend,))
                market = sign * (hsi[day][mark['t']] / references[day] - 1)
                future = (sign * (bars[i + 31][4] / bars[i + 1][4] - 1)
                          if i + 31 < len(bars) else None)
                yield (day, mark['side'], w18.bucket(mark['t']), *trend,
                       structure_values(mark, f), market, future)


def combine(candidate, trend, structure, market):
    values = (trend, structure, market)
    if candidate == 'C1':
        return sorted(values)[1]
    if candidate == 'C2':
        return sum(values) / 3
    return (trend * structure * market) ** (1 / 3)


def fit(train):
    price, ema, rsi, market = (defaultdict(list) for _ in range(4))
    trigger = defaultdict(list)
    for _day, _side, group, p, e, r, structures, m, _future in train:
        price[group].append(p); ema[group].append(e); rsi[group].append(r); market[group].append(m)
        for name, value in structures:
            trigger[name].append(value)
    for mapping in (price, ema, rsi, market, trigger):
        for values in mapping.values():
            values.sort()
    trend_raw, structure_raw = defaultdict(list), defaultdict(list)
    for _day, _side, group, p, e, r, structures, _m, _future in train:
        trend_raw[group].append(min(w17.percentile(price[group], p),
                                    w17.percentile(ema[group], e),
                                    w17.percentile(rsi[group], r)))
        structure_raw[group].append(max(w17.percentile(trigger[name], value)
                                        for name, value in structures))
    for mapping in (trend_raw, structure_raw):
        for values in mapping.values():
            values.sort()
    combined = {candidate: defaultdict(list) for candidate in CANDIDATES}
    for row in train:
        _day, _side, group, p, e, r, structures, m, _future = row
        t = w17.percentile(trend_raw[group], min(w17.percentile(price[group], p),
                                                 w17.percentile(ema[group], e),
                                                 w17.percentile(rsi[group], r)))
        s = w17.percentile(structure_raw[group], max(w17.percentile(trigger[name], value)
                                                     for name, value in structures))
        mk = w17.percentile(market[group], m)
        for candidate in CANDIDATES:
            combined[candidate][group].append(combine(candidate, t, s, mk))
    for candidate in CANDIDATES:
        for values in combined[candidate].values():
            values.sort()
    return dict(price=price, ema=ema, rsi=rsi, trigger=trigger, market=market,
                trend=trend_raw, structure=structure_raw, combined=combined)


def component_scores(row, fitted):
    _day, _side, group, p, e, r, structures, m, _future = row
    trend_raw = min(w17.percentile(fitted['price'][group], p),
                    w17.percentile(fitted['ema'][group], e),
                    w17.percentile(fitted['rsi'][group], r))
    structure_raw = max(w17.percentile(fitted['trigger'][name], value)
                        for name, value in structures)
    return (w17.percentile(fitted['trend'][group], trend_raw),
            w17.percentile(fitted['structure'][group], structure_raw),
            w17.percentile(fitted['market'][group], m))


def score(events_, fitted):
    out = {candidate: [] for candidate in CANDIDATES}
    for row in events_:
        day, side, group, *_rest, future = row
        trend, structure, market = component_scores(row, fitted)
        for candidate in CANDIDATES:
            raw = combine(candidate, trend, structure, market)
            value = w17.percentile(fitted['combined'][candidate][group], raw)
            out[candidate].append((day, side, value, future, trend, structure, market))
    return out


def mean(values):
    return sum(values) / len(values) if values else math.nan


def daily_t(rows):
    by_day = defaultdict(lambda: [[], []])
    for day, _side, score_, future, *_components in rows:
        if future is None:
            continue
        if score_ >= 67:
            by_day[day][0].append(future)
        elif score_ <= 33:
            by_day[day][1].append(future)
    diffs = np.array([mean(high) - mean(low) for high, low in by_day.values() if high and low])
    value = float(diffs.mean()) if len(diffs) else math.nan
    t = float(value / (diffs.std(ddof=1) / math.sqrt(len(diffs)))) if len(diffs) > 1 and diffs.std(ddof=1) else math.nan
    return value * 10000, t, len(diffs)


def evaluate(rows, hsi, references):
    counts = {side: sum(row[1] == side for row in rows) for side in ('BUY', 'SELL')}
    high_all = [row for row in rows if row[2] >= 67]
    low_all = [row for row in rows if row[2] <= 33]
    high = [row for row in high_all if row[3] is not None]
    low = [row for row in low_all if row[3] is not None]
    future = dict(
        high_bp=mean([row[3] for row in high]) * 10000,
        low_bp=mean([row[3] for row in low]) * 10000,
        difference_bp=(mean([row[3] for row in high]) - mean([row[3] for row in low])) * 10000,
        daily=dict(zip(('difference_bp', 't', 'days'), daily_t(rows))),
        side_difference_bp={side: (mean([row[3] for row in high if row[1] == side])
                                   - mean([row[3] for row in low if row[1] == side])) * 10000
                            for side in ('BUY', 'SELL')})
    component_spread = {
        name: mean([row[index] for row in high_all]) - mean([row[index] for row in low_all])
        for name, index in (('trend', 4), ('structure', 5), ('market', 6))}
    days = {row[0] for row in rows}
    full_market = {day: hsi[day][max(hsi[day])] / references[day] - 1 for day in days}
    ordered = sorted(days, key=lambda day: (full_market[day], day))
    extreme_days = {'DOWN': ordered[:10], 'UP': list(reversed(ordered[-10:]))}
    extreme, daily = {}, []
    for regime, selected_days in extreme_days.items():
        aligned_side = 'BUY' if regime == 'UP' else 'SELL'
        selected = [row for row in rows if row[0] in selected_days]
        aligned = [row[2] for row in selected if row[1] == aligned_side]
        opposed = [row[2] for row in selected if row[1] != aligned_side]
        extreme[regime] = dict(days=selected_days, aligned_mean=mean(aligned),
                               opposed_mean=mean(opposed), separation=mean(aligned)-mean(opposed))
        for day in selected_days:
            day_rows = [row for row in selected if row[0] == day]
            a = mean([row[2] for row in day_rows if row[1] == aligned_side])
            o = mean([row[2] for row in day_rows if row[1] != aligned_side])
            daily.append(dict(day=day, regime=regime, hsi_return_pct=full_market[day] * 100,
                              aligned_mean=a, opposed_mean=o, pass_day=a > o))
    gates = dict(
        sample=min(counts.values()) >= 30000,
        centered=45 <= mean([row[2] for row in rows]) <= 55,
        future=(future['daily']['difference_bp'] > 0 and future['daily']['t'] >= 2
                and all(value > 0 for value in future['side_difference_bp'].values())),
        intrinsic=(component_spread['trend'] >= 20 and component_spread['structure'] >= 20),
        extremes=(extreme['UP']['separation'] >= 20 and extreme['DOWN']['separation'] >= 20
                  and sum(row['pass_day'] for row in daily) >= 15))
    return dict(n=len(rows), counts=counts, overall_mean=mean([row[2] for row in rows]),
                future=future, component_spread=component_spread, extreme=extreme,
                daily_pass=sum(row['pass_day'] for row in daily), daily_checks=daily,
                gates=gates, pass_all=all(gates.values()))


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
    quality = w16.quality_scan(args.selection_bars)
    hsi, refs = w15.load_hsi(args.selection_bars)
    selection = list(events(args.selection_bars, hsi, refs, '2024-06-03', '2024-11-29', set(quality)))
    scored = score(selection, fitted)
    results = {candidate: evaluate(scored[candidate], hsi, refs) for candidate in CANDIDATES}
    counts = dict(buckets={str(group): len(values) for group, values in sorted(fitted['price'].items())},
                  triggers={name: len(fitted['trigger'][name]) for name in TRIGGERS})
    training_gate = min(counts['buckets'].values()) >= 2000 and min(counts['triggers'].values()) >= 10000
    selected = next((candidate for candidate in CANDIDATES
                     if training_gate and results[candidate]['pass_all']), None)
    print(json.dumps(w13.w12.clean(dict(
        definition='trend + structure + HSI composite B/S strength', candidates={
            'C1': 'median', 'C2': 'mean', 'C3': 'geometric'}, training_n=len(train),
        training_counts=counts, training_gate=training_gate,
        selection_days=len({row[0] for row in selection}), excluded_invalid_codes=quality,
        results=results, selected=selected, deployment_allowed=False,
        elapsed_seconds=time.monotonic() - started,
        max_rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)),
        ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
