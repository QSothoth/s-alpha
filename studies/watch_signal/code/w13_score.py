"""W13 causal walk-forward score screening; aggregate state only."""
import argparse
import json
import math
import resource
import sqlite3
import tempfile
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

import w12_audit as w12

ROOT = Path(__file__).resolve().parents[3]
FIRST_PREDICT_MONTH = '2026-03'
CANDIDATES = ('P1', 'P2')
MIN_CELL = 200


def density(tpb):
    return 'tpb<2' if tpb < 2 else ('2<=tpb<5' if tpb < 5 else 'tpb>=5')


def cells(mark):
    daily = {True: 'D+', False: 'D-', None: 'D?'}[mark['daily']]
    p1 = (density(mark['tpb']), daily)
    return p1, p1 + (mark['trigger'],)


class Count:
    def __init__(self):
        self.n = self.wins = self.nret = 0
        self.ret = 0.0

    def add(self, ret):
        self.nret += 1
        self.ret += ret
        if ret:
            self.n += 1
            self.wins += ret > 0

    def merge(self, other):
        self.n += other.n
        self.wins += other.wins
        self.nret += other.nret
        self.ret += other.ret


def probability(count):
    return (count.wins + 0.5) / (count.n + 1)


def check_primitives():
    count = Count()
    for value in (0.01, -0.01, 0.0):
        count.add(value)
    assert (count.n, count.wins, count.nret) == (2, 1, 3)
    assert probability(count) == 0.5
    assert [density(x) for x in (1.99, 2.0, 4.99, 5.0)] == [
        'tpb<2', '2<=tpb<5', '2<=tpb<5', 'tpb>=5']
    grouped = defaultdict(Count)
    grouped[('2026-02-27', 'BUY', 'P1', ('tpb<2', 'D+'))].add(0.01)
    grouped[('2026-03-02', 'BUY', 'P1', ('tpb<2', 'D+'))].add(-0.01)
    global_count, fitted = fit_before(grouped, '2026-03')
    assert (global_count.n, fitted['P1'][('tpb<2', 'D+')].wins) == (1, 1)


def collect(bars_path, daily_path, limit_days=0):
    grouped = defaultdict(Count)
    processed = 0
    with tempfile.TemporaryDirectory(prefix='w13-score-') as tmp:
        db = sqlite3.connect(str(Path(tmp) / 'daily.sqlite'))
        w12.daily_db(daily_path, db)
        for (code, day), bars in w12.sessions(bars_path):
            context = w12.daily_context(db, code, day)
            f = w12.corrected_features(bars)
            for mark in w12.replica(bars, f, context, 'B0'):
                i = mark['i']
                if i + 31 >= len(bars):
                    continue
                sign = 1 if mark['side'] == 'BUY' else -1
                ret = sign * (bars[i + 31][4] / bars[i + 1][4] - 1)
                p1, p2 = cells(mark)
                for candidate, cell in zip(CANDIDATES, (p1, p2)):
                    grouped[(day, mark['side'], candidate, cell)].add(ret)
            processed += 1
            if limit_days and processed >= limit_days:
                break
        db.close()
    return grouped, processed


def fit_before(grouped, month):
    global_count = Count()
    fitted = {candidate: defaultdict(Count) for candidate in CANDIDATES}
    for (day, _side, candidate, cell), count in grouped.items():
        if day[:7] >= month:
            continue
        fitted[candidate][cell].merge(count)
        if candidate == 'P1':
            global_count.merge(count)
    return global_count, fitted


def predictions(grouped):
    rows = []
    months = sorted({day[:7] for day, *_ in grouped if day[:7] >= FIRST_PREDICT_MONTH})
    for month in months:
        global_count, fitted = fit_before(grouped, month)
        base = probability(global_count)
        for (day, side, candidate, cell), count in grouped.items():
            if day[:7] != month:
                continue
            trained = fitted[candidate][cell]
            if trained.n >= MIN_CELL:
                p = probability(trained)
            elif candidate == 'P2':
                parent = fitted['P1'][cell[:2]]
                p = probability(parent) if parent.n >= MIN_CELL else base
            else:
                p = base
            rows.append(dict(day=day, side=side, candidate=candidate, p=p, base=base,
                             n=count.n, wins=count.wins, nret=count.nret, ret=count.ret))
    return rows


def regression(rows, outcome):
    # Aggregate OLS with intercept; x is score points centered at 50.
    xtx = np.zeros((2, 2)); xty = np.zeros(2)
    for row in rows:
        n = row['n'] if outcome == 'win' else row['nret']
        y = row['wins'] if outcome == 'win' else row['ret'] * 10000
        x = (row['p'] * 100 - 50)
        v = np.array([1.0, x])
        xtx += n * np.outer(v, v)
        xty += v * y
    if np.linalg.det(xtx) == 0:
        return dict(slope=None, t=None)
    inv = np.linalg.inv(xtx)
    beta = inv @ xty
    scores = defaultdict(lambda: np.zeros(2))
    for row in rows:
        n = row['n'] if outcome == 'win' else row['nret']
        y = row['wins'] if outcome == 'win' else row['ret'] * 10000
        x = row['p'] * 100 - 50
        residual_sum = y - n * (beta[0] + beta[1] * x)
        scores[row['day']] += np.array([1.0, x]) * residual_sum
    g = len(scores)
    meat = sum((np.outer(v, v) for v in scores.values()), np.zeros((2, 2)))
    cov = inv @ meat @ inv * g / (g - 1) if g > 1 else np.full((2, 2), np.nan)
    se = math.sqrt(max(cov[1, 1], 0))
    return dict(slope=float(beta[1]), t=float(beta[1] / se) if se else None)


def paired_brier(rows):
    days = defaultdict(lambda: [0.0, 0.0, 0])
    for row in rows:
        w, n, p, b = row['wins'], row['n'], row['p'], row['base']
        loss = w * (1 - p) ** 2 + (n - w) * p ** 2
        base = w * (1 - b) ** 2 + (n - w) * b ** 2
        days[row['day']][0] += loss
        days[row['day']][1] += base
        days[row['day']][2] += n
    diffs = np.array([(loss - base) / n for loss, base, n in days.values() if n])
    mean = float(diffs.mean())
    t = float(mean / (diffs.std(ddof=1) / math.sqrt(len(diffs)))) if len(diffs) > 1 and diffs.std(ddof=1) else None
    return mean, t


def summarize(rows, candidate):
    selected = [row for row in rows if row['candidate'] == candidate]
    n = sum(row['n'] for row in selected)
    wins = sum(row['wins'] for row in selected)
    predicted = sum(row['p'] * row['n'] for row in selected) / n
    actual = wins / n
    loss = sum(row['wins'] * (1 - row['p']) ** 2 + (row['n'] - row['wins']) * row['p'] ** 2
               for row in selected) / n
    base_loss = sum(row['wins'] * (1 - row['base']) ** 2 + (row['n'] - row['wins']) * row['base'] ** 2
                    for row in selected) / n
    brier_diff, brier_t = paired_brier(selected)
    hit = regression(selected, 'win')
    returns = regression(selected, 'ret')
    side_hit = {side: regression([r for r in selected if r['side'] == side], 'win')
                for side in ('BUY', 'SELL')}
    scores = np.array([row['p'] * 100 for row in selected for _ in range(row['n'])])
    counts = {side: sum(row['n'] for row in selected if row['side'] == side) for side in ('BUY', 'SELL')}
    gates = dict(sample=len({row['day'] for row in selected}) >= 60 and min(counts.values()) >= 10000,
                 brier=brier_diff < 0 and brier_t is not None and brier_t <= -2,
                 hit_slope=hit['slope'] is not None and hit['slope'] > 0 and hit['t'] is not None and hit['t'] >= 2,
                 return_slope=returns['slope'] is not None and returns['slope'] > 0 and returns['t'] is not None and returns['t'] >= 2,
                 both_sides=all(side_hit[s]['slope'] is not None and side_hit[s]['slope'] > 0 for s in side_hit),
                 calibrated=abs(actual - predicted) <= 0.01 and float(scores.std()) >= 0.5)
    return dict(candidate=candidate, days=len({row['day'] for row in selected}), n=n, counts=counts,
                actual_pct=actual * 100, predicted_pct=predicted * 100,
                calibration_error_points=(actual - predicted) * 100,
                brier=loss, baseline_brier=base_loss, brier_daily_diff=brier_diff, brier_diff_t=brier_t,
                hit_regression=hit, return_bp_regression=returns, side_hit_regression=side_hit,
                score_min=float(scores.min()), score_max=float(scores.max()), score_std=float(scores.std()),
                gates=gates, selection_pass=all(gates.values()), deployment_allowed=False)


def full_mapping(grouped, candidate):
    global_count, fitted = fit_before(grouped, '9999-99')
    out = []
    for cell, count in sorted(fitted[candidate].items(), key=lambda item: repr(item[0])):
        if count.n >= MIN_CELL:
            p = probability(count)
        elif candidate == 'P2':
            parent = fitted['P1'][cell[:2]]
            p = probability(parent) if parent.n >= MIN_CELL else probability(global_count)
        else:
            p = probability(global_count)
        out.append(dict(cell=list(cell), n=count.n, score=round(p * 100, 2)))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bars', type=Path, default=ROOT / 'data/watch-hk1m-train-v1/bars_1m.csv.gz')
    parser.add_argument('--daily', type=Path, default=ROOT / 'studies/watch_signal/data/day_2024-06_2026-09.csv.gz')
    parser.add_argument('--limit-days', type=int, default=0, help='Engineering smoke check only.')
    args = parser.parse_args()
    if args.limit_days < 0:
        parser.error('--limit-days cannot be negative')
    check_primitives()
    started = time.monotonic()
    grouped, processed = collect(args.bars, args.daily, args.limit_days)
    rows = predictions(grouped)
    summaries = [summarize(rows, candidate) for candidate in CANDIDATES] if rows else []
    passing = [s for s in summaries if s['selection_pass']]
    picked = min(passing, key=lambda s: (s['brier'], CANDIDATES.index(s['candidate'])))['candidate'] if passing else None
    output = dict(window=[w12.START, w12.END], first_predict_month=FIRST_PREDICT_MONTH,
                  partial=bool(args.limit_days), stock_days=processed,
                  elapsed_seconds=time.monotonic() - started,
                  max_rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                  summaries=summaries, selected_for_future_validation=picked,
                  mappings={candidate: full_mapping(grouped, candidate) for candidate in CANDIDATES})
    print(json.dumps(w12.clean(output), ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
