"""W32 does the strength grade guide trades? See notes/W32_PREREG.md.

usage: w32_guidance.py selection|validation [--candidates M1,M2,M3]
"""
import argparse
import csv
import gzip
import itertools
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import w12_audit as w12
import w15_market_score as w15
import w16_validate as w16
import w22_trade as w22
import w27_fixed_grade as w27

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'watch'))
import signal_grade  # noqa: E402

SEGMENTS = {
    'selection': dict(w22.SEGMENTS['selection'], daily='file'),
    'validation': dict(bars=ROOT / 'studies/watch_signal/data/w19_2024h1_1m.csv.gz',
                       hsi=ROOT / 'studies/watch_signal/data/w19_2024h1_1m.csv.gz',
                       start='2024-01-02', end='2024-05-31', daily='derived'),
}
RANGE_MODEL = (   # frozen W24 coefficients, as in watch/smc_watch.py
    ('10:00', 30, 1.0265, 0.6363, 0.2306), ('10:30', 60, 1.5006, 0.7525, 0.1455),
    ('11:00', 90, 1.6593, 0.7946, 0.1106), ('11:30', 120, 1.6151, 0.7943, 0.1029),
    ('13:30', 150, 1.4673, 0.8298, 0.0737), ('14:00', 180, 1.2360, 0.8087, 0.0821),
    ('14:30', 210, 0.9164, 0.7855, 0.0712), ('15:00', 240, 0.3957, 0.7525, 0.0384))
COST = 0.0010


def derived_daily(path):
    """Daily (high, low, close) per code from the 1m file's continuous session."""
    out = defaultdict(list)
    with gzip.open(path, 'rt', newline='') as fh:
        for (code, day), rows in itertools.groupby(csv.DictReader(fh), lambda r: (r['code'], r['time_key'][:10])):
            rows = [r for r in rows if r['time_key'][11:16] < '16:00']
            try:
                hs = [float(r['high']) for r in rows]; ls = [float(r['low']) for r in rows]
                closes = [float(r['close']) for r in sorted(rows, key=lambda r: r['time_key'])]
            except ValueError:
                continue
            if rows and min(ls) > 0:
                out[code].append((day, max(hs), min(ls), closes[-1]))
    return {c: sorted(v) for c, v in out.items()}


def left_forecast(bars, i, prev_range):
    index = {b[0][11:16]: k for k, b in enumerate(bars[:i + 1])}
    done = [m for m in RANGE_MODEL if m[0] in index]
    if not done or not prev_range or prev_range <= 0:
        return None
    cp, minutes, a, b, c = done[-1]
    k = index[cp]
    rv = sum(abs(math.log(bars[j][4] / bars[j - 1][4])) for j in range(1, k + 1))
    if rv <= 0:
        return None
    return math.exp(a + b * math.log(rv / minutes) + c * math.log(prev_range))


def collect(segment):
    cfg = SEGMENTS[segment]
    daily = w27.load_daily() if cfg['daily'] == 'file' else derived_daily(cfg['bars'])
    excluded = set(w16.quality_scan(cfg['bars']))
    hsi, refs = w15.load_hsi(cfg['hsi'])
    out = []
    for code, day, previous, bars in w22.sessions(cfg['bars'], cfg['start'], cfg['end'], excluded):
        sa, ia = w27.atr20(daily, code, day), w27.atr20(daily, 'HK.800000', day)
        prior = [r for r in daily.get(code, ()) if r[0] < day]
        prev_range = None
        if prior:
            # W24 used yesterday's (high - low) / open; the daily rows here carry no
            # open, so the close before yesterday stands in (a few bp apart).
            _, h, lo, _c = prior[-1]
            base = prior[-2][3] if len(prior) > 1 else None
            prev_range = (h - lo) / base if base else None
        if not previous or sa is None or ia is None:
            continue
        f = w12.corrected_features(bars)
        last = len(bars) - 1
        for m in w12.replica(bars, f, None, 'B0'):
            i = m['i']
            if m['tpb'] < 2 or i + 2 > last:
                continue
            side = 1 if m['side'] == 'BUY' else -1
            vr = f['vr'][i]
            h = hsi.get(day, {}).get(m['t'])
            g = signal_grade.grade(m['side'], vr if math.isfinite(vr) else None,
                                   (h / refs[day] - 1) if h and day in refs else None, ia,
                                   m['close'] / previous - 1, sa)
            if g is None:
                continue
            entry = bars[i + 1][4]
            hi = max(b[2] for b in bars[i + 2:]) if i + 2 <= last else entry
            lo = min(b[3] for b in bars[i + 2:]) if i + 2 <= last else entry
            atr = float(f['atr'][i])
            fav = (hi - entry) if side > 0 else (entry - lo)
            adv = (entry - lo) if side > 0 else (hi - entry)
            lf = left_forecast(bars, i, prev_range)
            out.append(dict(day=day, g=g, rest=(hi - lo) / entry, left=lf,
                            edge=(fav - adv) / atr if atr > 0 else None,
                            fclose=side * (bars[last][4] / entry - 1)))
    return out


def clustered(rows, key):
    vals = [(r['day'], key(r)) for r in rows]
    vals = [(d, v) for d, v in vals if v is not None and math.isfinite(v)]
    if len(vals) < 30:
        return math.nan, math.nan, len(vals)
    mean = sum(v for _, v in vals) / len(vals)
    infl = defaultdict(float)
    for d, v in vals:
        infl[d] += (v - mean) / len(vals)
    n = len(infl)
    se = math.sqrt(n / (n - 1) * sum(x * x for x in infl.values()))
    return mean, mean / se if se else math.nan, len(vals)


def diff_t(rows, key, hi=5, lo=1):
    """Grade hi minus grade lo, day-clustered (per-day difference of means)."""
    by = defaultdict(lambda: {hi: [], lo: []})
    for r in rows:
        v = key(r)
        if r['g'] in (hi, lo) and v is not None and math.isfinite(v):
            by[r['day']][r['g']].append(v)
    a = [v for d in by.values() for v in d[hi]]
    b = [v for d in by.values() for v in d[lo]]
    if len(a) < 30 or len(b) < 30:
        return math.nan, math.nan
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    infl = {d: (sum(x - ma for x in v[hi]) / len(a) - sum(x - mb for x in v[lo]) / len(b)) for d, v in by.items()}
    n = len(infl)
    se = math.sqrt(n / (n - 1) * sum(x * x for x in infl.values()))
    return ma - mb, (ma - mb) / se if se else math.nan


def evaluate(rows, candidates):
    res = {'n': len(rows), 'per_grade': {}}
    lr = lambda r: math.log(r['rest'] / r['left']) if r['left'] and r['rest'] > 0 else None
    for k in range(1, 6):
        part = [r for r in rows if r['g'] == k]
        res['per_grade'][k] = dict(
            n=len(part),
            log_rest_over_left=clustered(part, lr)[0],
            rest_pct=clustered(part, lambda r: r['rest'] * 100)[0],
            edge_atr=clustered(part, lambda r: r['edge']),
            fclose_net_bp=[x * 1e4 if i == 0 else x for i, x in
                           enumerate(clustered(part, lambda r: r['fclose'] - COST)[:2])])
    out = {}
    if 'M1' in candidates:
        means = [res['per_grade'][k]['log_rest_over_left'] for k in range(1, 6)]
        d, t = diff_t(rows, lr)
        out['M1'] = dict(means=means, ratio_5_over_1=math.exp(d) if math.isfinite(d) else math.nan, t=t,
                         passed=all(a < b for a, b in zip(means, means[1:])) and t >= 3 and math.exp(d) >= 1.3)
    if 'M2' in candidates:
        m5, t5, _ = res['per_grade'][5]['edge_atr']
        d, t = diff_t(rows, lambda r: r['edge'])
        out['M2'] = dict(grade5=m5, t5=t5, diff=d, t_diff=t,
                         passed=m5 > 0 and t5 >= 2 and d > 0 and t >= 2)
    if 'M3' in candidates:
        m, t = res['per_grade'][5]['fclose_net_bp']
        out['M3'] = dict(net_bp=m, t=t, passed=m > 0 and t >= 2)
    res['candidates'] = out
    return res


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('segment', choices=sorted(SEGMENTS))
    parser.add_argument('--candidates', default='M1,M2,M3')
    args = parser.parse_args()
    rows = collect(args.segment)
    print(json.dumps(w12.clean(evaluate(rows, args.candidates.split(','))), indent=2, default=list))


if __name__ == '__main__':
    main()
