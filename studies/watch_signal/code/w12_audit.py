"""W12 correction audit and fixed candidates; bounded stock-day streaming only."""
import argparse
import csv
import gzip
import importlib.util
import itertools
import json
import math
import resource
import sqlite3
import sys
import tempfile
import time
import types
from collections import defaultdict
from pathlib import Path

import numpy as np

import feat

ROOT = Path(__file__).resolve().parents[3]
START, END = '2025-12-01', '2026-08-14'
VARIANTS = ('B0', 'C1', 'C2')
DENSITIES = ('tpb<2', '2<=tpb<5', 'tpb>=5')
LAYERS = ('all', 'tpb>=2') + DENSITIES + tuple(
    density + '|' + daily for density in DENSITIES for daily in ('D+', 'D-', 'D?'))


def tick(price, day):
    bands = [(0.25, 0.001), (0.5, 0.005),
             (10, 0.005 if day >= '2026-08-03' else 0.01),
             (20, 0.01 if day >= '2025-08-04' else 0.02)]
    if day >= '2025-08-04':
        bands.append((50, 0.02))
    bands += [(100, 0.05), (200, 0.1), (500, 0.2), (1000, 0.5),
              (2000, 1.0), (5000, 2.0)]
    return next((step for upper, step in bands if price <= upper), 5.0)


def corrected_features(bars):
    t = np.array([int(b[0][11:13]) * 60 + int(b[0][14:16]) for b in bars])
    f = feat.build(t, np.array([b[1:] for b in bars], dtype=float))
    vr, tpb, total = [], [], 0.0
    for i, b in enumerate(bars):
        prior = bars[max(0, i - 20):i]
        mean = sum(x[5] for x in prior) / len(prior) if prior else 0
        vr.append(b[5] / mean if mean > 0 else math.nan)
        if i:
            total += (b[2] - b[3]) / tick(b[4], b[0][:10])
        tpb.append(total / max(i, 1))
    f['vr'], f['tpb'] = vr, tpb
    return f


def replica(bars, f, context, variant):
    out, last = [], {}
    for i in range(25, len(bars)):
        c, h, l, atr = (float(f[k][i]) for k in ('c', 'h', 'l', 'atr'))
        if atr <= 0:
            continue
        sh, sl = float(f['sh'][i]), float(f['sl'][i])
        bull, bear = [], []
        if c > sh and (variant == 'B0' or f['c'][i - 1] <= sh):
            bull.append('BOS')
        if c < sl and (variant == 'B0' or f['c'][i - 1] >= sl):
            bear.append('BOS')
        if l - f['h'][i - 2] > 0.25 * atr:
            bull.append('FVG')
        elif f['l'][i - 2] - h > 0.25 * atr:
            bear.append('FVG')
        if l < sl <= c:
            bull.append('SWEEP')
        if h > sh >= c:
            bear.append('SWEEP')
        if c > f['vwap'][i] and f['ema9'][i] > f['ema21'][i] and f['rsi'][i] >= 50 and bull:
            side, trigger, zone, stop = 'BUY', bull, f['pos'][i] <= 0.5, sl
        elif c < f['vwap'][i] and f['ema9'][i] < f['ema21'][i] and f['rsi'][i] <= 50 and bear:
            side, trigger, zone, stop = 'SELL', bear, f['pos'][i] >= 0.5, sh
        else:
            continue
        tier = 'vol' if f['vr'][i] >= 1.5 and zone else 'plain'
        key = side if variant == 'C2' else (side, tier)
        if i - last.get(key, -10000) < 15:
            continue
        last[key] = i
        daily = None if context is None else bool(
            (context['ret5d'] <= 0 and c <= context['pdh']) if side == 'BUY'
            else (context['ret5d'] >= 0 and c >= context['pdl']))
        out.append(dict(i=i, t=bars[i][0][11:16], side=side, tier=tier,
                        tpb=round(f['tpb'][i], 2), fine=f['tpb'][i] >= 5,
                        coarse=f['tpb'][i] < 2, trigger='+'.join(trigger), close=c,
                        rsi=round(float(f['rsi'][i]), 1), vwap=round(float(f['vwap'][i]), 3),
                        vol_ratio=round(f['vr'][i], 2) if math.isfinite(f['vr'][i]) else None,
                        pos=round(float(f['pos'][i]), 2), stop=None if math.isnan(stop) else stop,
                        daily=daily))
    return out


def checked_values(row, fields):
    values = tuple(float(row[k] or 0) for k in fields)
    if any(not math.isfinite(v) or (v < 0 if k == 'volume' else v <= 0)
           for k, v in zip(fields, values)):
        raise ValueError('invalid price/volume: %s %s' % (row['code'], row['time_key']))
    return values


def sessions(path):
    seen = set()
    with gzip.open(path, 'rt', newline='') as fh:
        for key, rows in itertools.groupby(csv.DictReader(fh), lambda r: (r['code'], r['time_key'][:10])):
            if key in seen:
                raise ValueError('non-contiguous stock-day: %r' % (key,))
            seen.add(key)
            if not START <= key[1] <= END:
                raise ValueError('outside registered selection window: %r' % (key,))
            bars = [(r['time_key'], *checked_values(r, ('open', 'high', 'low', 'close', 'volume')))
                    for r in rows if r['time_key'][11:16] < '16:00']
            bars.sort()
            if len({b[0] for b in bars}) != len(bars):
                raise ValueError('duplicate minute: %r' % (key,))
            if len(bars) >= 200:
                yield key, bars


def daily_db(path, db):
    db.execute('PRAGMA cache_size = -2048')
    db.execute('CREATE TABLE daily (code TEXT, day TEXT, close REAL, high REAL, low REAL, PRIMARY KEY(code, day))')
    with gzip.open(path, 'rt', newline='') as fh:
        rows = ((r['code'], r['time_key'][:10], float(r['close']), float(r['high']), float(r['low']))
                for r in csv.DictReader(fh) if r['time_key'][:10] <= END)
        db.executemany('INSERT INTO daily VALUES (?, ?, ?, ?, ?)', rows)
    db.commit()


def daily_context(db, code, day):
    rows = db.execute('SELECT day, close, high, low FROM daily WHERE code = ? AND day < ? ORDER BY day DESC LIMIT 6',
                      (code, day)).fetchall()
    if len(rows) < 6:
        return None
    # Old QFQ history can contain nonpositive prices; validate only the six
    # sessions actually used, without dropping or replacing bad context rows.
    for prev, close, high, low in rows:
        checked_values(dict(code=code, time_key=prev, close=close, high=high, low=low),
                       ('close', 'high', 'low'))
    return dict(ret5d=rows[0][1] / rows[5][1] - 1, pdh=rows[0][2], pdl=rows[0][3])


def watcher():
    stub = types.ModuleType('futu')
    stub.AuType = stub.KLType = stub.SubType = type('X', (), dict(K_1M=None, K_DAY=None, NONE=None, QFQ=None))
    stub.OpenQuoteContext, stub.RET_OK = object, 0
    sys.modules['futu'] = stub
    spec = importlib.util.spec_from_file_location('w12_watcher', ROOT / 'watch/smc_watch.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_replica(w, key, bars, f, context, expected):
    actual = w.with_daily(w.marks(bars)[0], context)
    if expected != actual:
        pairs = itertools.zip_longest(expected, actual)
        first = next((a, b) for a, b in pairs if a != b)
        raise AssertionError(('replica mismatch', key, first))
    cut = len(bars) // 2
    assert w.with_daily(w.marks(bars[:cut])[0], context) == [m for m in expected if m['i'] < cut], key
    small = corrected_features(bars[:cut])
    for field in ('vr', 'tpb'):
        np.testing.assert_allclose(small[field], f[field][:cut], rtol=0, atol=0, equal_nan=True)
    for field in ('vwap', 'ema9', 'ema21', 'rsi', 'atr', 'pos', 'sh', 'sl', 'dhi', 'dlo'):
        np.testing.assert_allclose(small[field], f[field][:cut], rtol=1e-12, atol=1e-12, equal_nan=True)
    assert replica(bars[:cut], small, context, 'B0') == [m for m in expected if m['i'] < cut], key
    return len(expected)


class Totals:
    def __init__(self):
        self.notifications = 0
        self.days = defaultdict(lambda: [0, 0.0, 0, 0.0])

    def add(self, day, side, ret):
        self.notifications += 1
        if ret is not None:
            offset = 0 if side == 'BUY' else 2
            self.days[day][offset] += 1
            self.days[day][offset + 1] += ret

    def summary(self):
        ns = [sum(v[o] for v in self.days.values()) for o in (0, 2)]
        means = [sum(v[o + 1] for v in self.days.values()) / n if n else math.nan
                 for o, n in zip((0, 2), ns)]
        mu = sum(means) / 2
        # Cluster influence uses residual sums, allowing different daily counts.
        influence = {d: sum((v[o + 1] - v[o] * m) / n for o, n, m in zip((0, 2), ns, means)) / 2
                     for d, v in self.days.items()} if min(ns) else {}
        return dict(notifications=self.notifications, n=sum(ns), days=len(self.days),
                    n_buy=ns[0], n_sell=ns[1],
                    days_buy=sum(v[0] > 0 for v in self.days.values()),
                    days_sell=sum(v[2] > 0 for v in self.days.values()),
                    buy_bp=means[0] * 10000, sell_bp=means[1] * 10000,
                    mean_bp=mu * 10000, t_day=cluster_t(mu, influence)), influence


def cluster_t(mean, influence):
    n = len(influence)
    se = math.sqrt(n / (n - 1) * sum(x * x for x in influence.values())) if n > 1 else 0
    return mean / se if se else math.nan


def check_statistics():
    # Three equal-sized clusters have mean 0.02 and t=sqrt(12). Replication
    # within a day must not create extra independent observations.
    for repeats in (1, 10):
        totals = Totals()
        for day, ret in (('a', 0.01), ('b', 0.02), ('c', 0.03)):
            for _ in range(repeats):
                for side in ('BUY', 'SELL'):
                    totals.add(day, side, ret)
        summary, _ = totals.summary()
        assert math.isclose(summary['mean_bp'], 200, abs_tol=1e-8)
        assert math.isclose(summary['t_day'], math.sqrt(12), abs_tol=1e-8)


def check_inputs():
    row = dict(code='HK.00001', time_key='2026-01-05 09:30:00',
               open='100', high='101', low='99', close='100', volume='')
    assert checked_values(row, ('close', 'volume')) == (100.0, 0.0)
    for fields in (('open', 'high', 'low', 'close', 'volume'), ('close', 'high', 'low')):
        for field in fields:
            bad_values = ('nan', 'inf', '-1') if field == 'volume' else ('nan', 'inf', '-1', '0', '')
            for bad in bad_values:
                try:
                    checked_values(dict(row, **{field: bad}), fields)
                except ValueError:
                    pass
                else:
                    raise AssertionError(('invalid input accepted', field, bad))
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE TABLE daily (code TEXT, day TEXT, close REAL, high REAL, low REAL)')
        db.executemany('INSERT INTO daily VALUES (?, ?, ?, ?, ?)',
                       [('HK.00001', '2026-01-%02d' % day, 100, 101, 0 if day == 1 else 99)
                        for day in range(1, 8)])
        assert daily_context(db, 'HK.00001', '2026-01-08') == dict(ret5d=0, pdh=101, pdl=99)
        db.execute("UPDATE daily SET low = 0 WHERE day = '2026-01-07'")
        try:
            daily_context(db, 'HK.00001', '2026-01-08')
        except ValueError:
            pass
        else:
            raise AssertionError('invalid daily context accepted')


def clean(value):
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return None if isinstance(value, float) and not math.isfinite(value) else value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bars', type=Path, default=ROOT / 'data/watch-hk1m-train-v1/bars_1m.csv.gz')
    parser.add_argument('--daily', type=Path, default=ROOT / 'studies/watch_signal/data/day_2024-06_2026-09.csv.gz')
    parser.add_argument('--limit-days', type=int, default=0, help='Smoke check only; never a full selection result.')
    parser.add_argument('--audit-days', type=int, default=40)
    parser.add_argument('--audit-only', action='store_true')
    args = parser.parse_args()
    if args.audit_days <= 0 or args.limit_days < 0:
        parser.error('--audit-days must be positive; --limit-days cannot be negative')
    if args.audit_days != 40 and not (args.audit_only or args.limit_days):
        parser.error('changing --audit-days requires --audit-only or --limit-days')
    check_inputs()
    check_statistics()
    started, processed, checked, audited_marks = time.monotonic(), 0, 0, 0
    groups = {} if args.audit_only else {(v, layer): Totals() for v in VARIANTS for layer in LAYERS}
    w = watcher()
    with tempfile.TemporaryDirectory(prefix='w12-audit-') as tmp:
        db = sqlite3.connect(str(Path(tmp) / 'daily.sqlite'))
        daily_db(args.daily, db)
        for (code, day), bars in sessions(args.bars):
            context = daily_context(db, code, day)
            f = corrected_features(bars)
            baseline = replica(bars, f, context, 'B0')
            if checked < args.audit_days:
                audited_marks += check_replica(w, (code, day), bars, f, context, baseline)
                checked += 1
            if not args.audit_only:
                for variant in VARIANTS:
                    marks = baseline if variant == 'B0' else replica(bars, f, context, variant)
                    for m in marks:
                        i = m['i']
                        density = f['tpb'][i]
                        layer = 'tpb<2' if density < 2 else ('2<=tpb<5' if density < 5 else 'tpb>=5')
                        daily = {True: 'D+', False: 'D-', None: 'D?'}[m['daily']]
                        ret = ((bars[i + 31][4] / bars[i + 1][4] - 1) * (1 if m['side'] == 'BUY' else -1)
                               if i + 31 < len(bars) else None)
                        layers = ['all', layer, layer + '|' + daily]
                        if density >= 2:
                            layers.append('tpb>=2')
                        for label in layers:
                            groups[(variant, label)].add(day, m['side'], ret)
            processed += 1
            if processed % 2000 == 0:
                print('processed=%d elapsed=%.1fs rss=%.1fMB' %
                      (processed, time.monotonic() - started, resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024),
                      file=sys.stderr, flush=True)
            if (args.limit_days and processed >= args.limit_days) or (args.audit_only and checked >= args.audit_days):
                break
        db.close()
    assert checked == args.audit_days, (checked, args.audit_days)
    summaries = {key: value.summary() for key, value in groups.items()}
    rows = []
    for (variant, layer), (summary, influence) in sorted(summaries.items()):
        base, bi = summaries[('B0', layer)]
        delta = (summary['mean_bp'] - base['mean_bp']) / 10000
        differences = {d: influence.get(d, 0) - bi.get(d, 0) for d in set(influence) | set(bi)}
        rows.append(dict(variant=variant, layer=layer, **summary, delta_bp=delta * 10000,
                         delta_t=cluster_t(delta, differences),
                         notification_reduction=(1 - summary['notifications'] / base['notifications']
                                                 if base['notifications'] else None)))
    decisions = {}
    for variant in VARIANTS[1:] if rows else ():
        s = next(r for r in rows if r['variant'] == variant and r['layer'] == 'tpb>=2')
        b = summaries[('B0', 'tpb>=2')][0]
        gates = dict(sample=min(s['n_buy'], s['n_sell']) >= 200 and min(s['days_buy'], s['days_sell']) >= 60,
                     positive=s['mean_bp'] > 0 and s['t_day'] >= 2,
                     improvement=s['delta_bp'] > 0 and s['delta_t'] >= 2,
                     both_sides=s['buy_bp'] >= b['buy_bp'] and s['sell_bp'] >= b['sell_bp'])
        decisions[variant] = dict(gates=gates, selection_pass=all(gates.values()), deployment_allowed=False)
    output = dict(window=[START, END], partial=bool(args.limit_days or args.audit_only),
                  bars=str(args.bars), daily=str(args.daily), stock_days=processed,
                  replica_days=checked, replica_marks=audited_marks, replica_mismatches=0,
                  elapsed_seconds=time.monotonic() - started,
                  max_rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                  decisions=decisions, rows=rows)
    print(json.dumps(clean(output), ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
