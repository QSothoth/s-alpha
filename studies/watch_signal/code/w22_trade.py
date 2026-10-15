"""W22 evaluate each B/S as a fixed 2R/1R trade; see notes/W22_PREREG.md."""
import argparse
import csv
import gzip
import itertools
import json
import math
import resource
import sqlite3
import tempfile
import time
from collections import defaultdict
from pathlib import Path

import w12_audit as w12
import w15_market_score as w15
import w16_validate as w16

ROOT = Path(__file__).resolve().parents[3]
CANDIDATES = ('C1', 'C2', 'C3', 'C4', 'C5')
COSTS = (0.0010, 0.0025)
R_ATR, TARGET_R, HOLD = 2.0, 2.0, 60
SEGMENTS = {
    'selection': dict(bars=ROOT / 'data/watch-hk1m-train-v1/bars_1m.csv.gz',
                      hsi=ROOT / 'data/watch-hk-index1m-v1/index_1m.csv.gz',
                      start='2025-12-01', end='2026-08-14'),
    'validation': dict(bars=ROOT / 'studies/watch_signal/data/w18_2024-12_2025-05_1m.csv.gz',
                       hsi=ROOT / 'studies/watch_signal/data/w18_2024-12_2025-05_1m.csv.gz',
                       start='2024-12-02', end='2025-05-30'),
}
DAILY = ROOT / 'studies/watch_signal/data/day_2024-06_2026-09.csv.gz'


def sessions(path, start, end, excluded):
    """(code, day, previous close, bars) with the W16 quality rules."""
    seen = set()
    with gzip.open(path, 'rt', newline='') as fh:
        for key, rows in itertools.groupby(csv.DictReader(fh), lambda r: (r['code'], r['time_key'][:10])):
            if key in seen:
                raise ValueError('non-contiguous stock-day: %r' % (key,))
            seen.add(key)
            code, day = key
            if code == 'HK.800000' or code in excluded:
                continue
            if not start <= day <= end:
                raise ValueError('outside window: %r' % (key,))
            rows = list(rows)
            first = min(rows, key=lambda r: r['time_key'])
            previous = float(first['last_close'] or 0) if first['time_key'][11:16] == '09:30' else 0.0
            bars = sorted((r['time_key'], *w12.checked_values(r, ('open', 'high', 'low', 'close', 'volume')))
                          for r in rows if r['time_key'][11:16] < '16:00')
            if len({b[0] for b in bars}) != len(bars):
                raise ValueError('duplicate minute: %r' % (key,))
            if len(bars) >= 200:
                yield code, day, (previous if math.isfinite(previous) and previous > 0 else None), bars


def trade(bars, i, side, atr):
    """Gross R of one trade entered at the close of bar i + 1, plus the exit kind."""
    j = i + 1
    entry = bars[j][4]
    r = R_ATR * atr
    sign = 1 if side == 'BUY' else -1
    stop, target = entry - sign * r, entry + sign * TARGET_R * r
    last = min(j + HOLD, len(bars) - 1)
    for k in range(j + 1, last + 1):
        o, h, lo = bars[k][1], bars[k][2], bars[k][3]
        if sign * (o - stop) <= 0:
            return sign * (o - entry) / r, 'stop', entry, r
        hit_stop = lo <= stop if sign > 0 else h >= stop
        hit_target = h >= target if sign > 0 else lo <= target
        if hit_stop:
            return -1.0, 'stop', entry, r
        if hit_target:
            return TARGET_R, 'target', entry, r
    return sign * (bars[last][4] - entry) / r, 'timeout', entry, r


def membership(m, s, mk):
    against = s is not None and mk is not None and s < 0 and mk < 0
    return dict(C1=True, C2=m['daily'] is True,
                C3=s is not None and mk is not None and s > 0 and mk > 0,
                C4=against, C5=m['daily'] is True and against)


def events(segment):
    cfg = SEGMENTS[segment]
    excluded = set(w16.quality_scan(cfg['bars']))
    hsi, refs = w15.load_hsi(cfg['hsi'])
    out, stock_days = [], 0
    with tempfile.TemporaryDirectory(prefix='w22-') as tmp:
        db = sqlite3.connect(str(Path(tmp) / 'daily.sqlite'))
        w12.daily_db(DAILY, db)
        for code, day, previous, bars in sessions(cfg['bars'], cfg['start'], cfg['end'], excluded):
            stock_days += 1
            context = w12.daily_context(db, code, day)
            f = w12.corrected_features(bars)
            for m in w12.replica(bars, f, context, 'B0'):
                i = m['i']
                if m['coarse'] or i + 2 >= len(bars):
                    continue
                atr = float(f['atr'][i])
                sign = 1 if m['side'] == 'BUY' else -1
                s = sign * (m['close'] / previous - 1) if previous else None
                h = hsi.get(day, {}).get(m['t'])
                mk = sign * (h / refs[day] - 1) if h and day in refs else None
                gross, kind, entry, r = trade(bars, i, m['side'], atr)
                out.append(dict(day=day, code=code, side=m['side'], gross=gross, kind=kind,
                                cost_r=[c * entry / r for c in COSTS], tpb=m['tpb'],
                                groups=membership(m, s, mk)))
        db.close()
    return out, dict(stock_days=stock_days, excluded=sorted(excluded))


def summarize(rows, cost_index):
    if not rows:
        return dict(n=0)
    net = [x['gross'] - x['cost_r'][cost_index] for x in rows]
    by_day = defaultdict(list)
    for x, v in zip(rows, net):
        by_day[x['day']].append(v)
    mean = sum(net) / len(net)
    # Day-clustered t: residual sums per trading day.
    influence = {d: sum(v - mean for v in vs) / len(net) for d, vs in by_day.items()}
    n_days = len(influence)
    se = math.sqrt(n_days / (n_days - 1) * sum(x * x for x in influence.values())) if n_days > 1 else 0
    wins = [v for v in net if v > 0]
    losses = [v for v in net if v <= 0]
    side = {s: [v for x, v in zip(rows, net) if x['side'] == s] for s in ('BUY', 'SELL')}
    kinds = defaultdict(int)
    for x in rows:
        kinds[x['kind']] += 1
    return dict(
        n=len(rows), days=n_days, gross_r=sum(x['gross'] for x in rows) / len(rows),
        net_r=mean, t_day=mean / se if se else math.nan,
        win_rate=len(wins) / len(net), avg_win_r=sum(wins) / len(wins) if wins else math.nan,
        avg_loss_r=sum(losses) / len(losses) if losses else math.nan,
        target=kinds['target'] / len(rows), stop=kinds['stop'] / len(rows),
        timeout=kinds['timeout'] / len(rows),
        buy_n=len(side['BUY']), buy_net_r=sum(side['BUY']) / len(side['BUY']) if side['BUY'] else math.nan,
        sell_n=len(side['SELL']), sell_net_r=sum(side['SELL']) / len(side['SELL']) if side['SELL'] else math.nan,
        median_cost_r=sorted(x['cost_r'][cost_index] for x in rows)[len(rows) // 2])


def gates(summary, segment):
    n_min, d_min = (300, 40) if segment == 'selection' else (150, 0)
    return dict(sample=summary['n'] >= n_min and summary['days'] >= d_min,
                positive=summary['net_r'] > 0 and summary['t_day'] >= 2,
                both_sides=summary['buy_net_r'] > 0 and summary['sell_net_r'] > 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('segment', choices=sorted(SEGMENTS))
    parser.add_argument('--candidates', default=','.join(CANDIDATES),
                        help='validation: only the candidates that passed selection')
    args = parser.parse_args()
    started = time.monotonic()
    rows, meta = events(args.segment)
    stock_days = meta['stock_days']
    result = {}
    for c in args.candidates.split(','):
        part = [x for x in rows if x['groups'][c]]
        main_s = summarize(part, 0)
        result[c] = dict(per_stock_day=len(part) / stock_days, cost_010=main_s,
                         cost_025=summarize(part, 1), gates=gates(main_s, args.segment) if part else {})
        result[c]['pass'] = bool(part) and all(result[c]['gates'].values())
    tiers = {}
    for name, lo, hi in (('2<=tpb<5', 2, 5), ('tpb>=5', 5, math.inf)):
        tiers[name] = summarize([x for x in rows if lo <= x['tpb'] < hi], 0)
    print(json.dumps(w12.clean(dict(
        segment=args.segment, config=dict(R_ATR=R_ATR, TARGET_R=TARGET_R, HOLD=HOLD, costs=COSTS),
        stock_days=stock_days, excluded=meta['excluded'], trades=len(rows), candidates=result,
        tpb_tiers=tiers, elapsed_seconds=round(time.monotonic() - started, 1),
        max_rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)),
        ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
