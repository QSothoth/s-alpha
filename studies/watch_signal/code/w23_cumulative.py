"""W23 does the day's running B/S tally call the rest of the day? See notes/W23_PREREG.md."""
import argparse
import json
import math
import resource
import time
from collections import defaultdict

import w12_audit as w12
import w16_validate as w16
import w22_trade as w22

CHECKPOINTS = ('10:30', '11:30', '13:30', '14:30')
CANDIDATES = ('K1', 'K2', 'K3')
COST = 0.0010


def direction(candidate, sides):
    """+1 / -1 / 0 from the sides of the marks so far, oldest first."""
    if candidate == 'K1':
        n = sides.count(1) - sides.count(-1)
        return (n > 0) - (n < 0) if abs(n) >= 2 else 0
    if candidate == 'K2':
        return sides[-1] if len(sides) >= 3 and len(set(sides[-3:])) == 1 else 0
    if candidate == 'K3':
        return sides[0] if len(sides) >= 2 and len(set(sides)) == 1 else 0
    raise ValueError(candidate)


def observations(segment):
    cfg = w22.SEGMENTS[segment]
    excluded = set(w16.quality_scan(cfg['bars']))
    out, stock_days = [], 0
    for code, day, _previous, bars in w22.sessions(cfg['bars'], cfg['start'], cfg['end'], excluded):
        stock_days += 1
        f = w12.corrected_features(bars)
        marks = [(m['i'], 1 if m['side'] == 'BUY' else -1)
                 for m in w12.replica(bars, f, None, 'B0') if not m['coarse']]
        minutes = {b[0][11:16]: i for i, b in enumerate(bars)}
        last = len(bars) - 1
        for cp in CHECKPOINTS:
            i = minutes.get(cp)
            if i is None or i + 1 >= last or f['tpb'][i] < 2:
                continue
            sides = [s for j, s in marks if j <= i]
            entry, close = bars[i + 1][4], bars[last][4]
            rest = close / entry - 1
            move = bars[i][4] / bars[0][1] - 1
            momentum = (move > 0) - (move < 0)
            for c in CANDIDATES:
                d = direction(c, sides) if sides else 0
                if d:
                    out.append(dict(day=day, cp=cp, cand=c, dir=d, gross=d * rest,
                                    net=d * rest - COST, mom=momentum * rest, agree=d == momentum))
    return out, stock_days


def clustered(rows, key):
    if not rows:
        return math.nan, math.nan
    values = [key(x) for x in rows]
    mean = sum(values) / len(values)
    infl = defaultdict(float)
    for x, v in zip(rows, values):
        infl[x['day']] += (v - mean) / len(values)
    n = len(infl)
    se = math.sqrt(n / (n - 1) * sum(v * v for v in infl.values())) if n > 1 else 0
    return mean, mean / se if se else math.nan


def summarize(rows, segment):
    if not rows:
        return dict(n=0, passed=False)
    net, t = clustered(rows, lambda x: x['net'])
    gross, _ = clustered(rows, lambda x: x['gross'])
    excess, t_excess = clustered(rows, lambda x: x['gross'] - x['mom'])
    mom, _ = clustered(rows, lambda x: x['mom'])
    longs = [x['net'] for x in rows if x['dir'] > 0]
    shorts = [x['net'] for x in rows if x['dir'] < 0]
    s = dict(n=len(rows), days=len({x['day'] for x in rows}),
             long_share=len(longs) / len(rows), gross_bp=gross * 1e4, net_bp=net * 1e4, t=t,
             long_net_bp=sum(longs) / len(longs) * 1e4 if longs else math.nan,
             short_net_bp=sum(shorts) / len(shorts) * 1e4 if shorts else math.nan,
             momentum_bp=mom * 1e4, excess_bp=excess * 1e4, t_excess=t_excess,
             agree=sum(x['agree'] for x in rows) / len(rows))
    n_min, d_min = (1000, 40) if segment == 'selection' else (500, 0)
    s['gates'] = dict(sample=s['n'] >= n_min and s['days'] >= d_min,
                      tradable=s['net_bp'] > 0 and s['t'] >= 2,
                      both_sides=bool(longs and shorts) and s['long_net_bp'] > 0 and s['short_net_bp'] > 0,
                      incremental=s['excess_bp'] > 0 and s['t_excess'] >= 2)
    s['passed'] = all(s['gates'].values())
    return s


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('segment', choices=sorted(w22.SEGMENTS))
    parser.add_argument('--candidates', default=','.join(CANDIDATES))
    args = parser.parse_args()
    started = time.monotonic()
    rows, stock_days = observations(args.segment)
    result = {}
    for c in args.candidates.split(','):
        part = [x for x in rows if x['cand'] == c]
        result[c] = dict(all=summarize(part, args.segment),
                         by_checkpoint={cp: summarize([x for x in part if x['cp'] == cp], args.segment)
                                        for cp in CHECKPOINTS})
    print(json.dumps(w12.clean(dict(
        segment=args.segment, stock_days=stock_days, cost=COST, candidates=result,
        elapsed_seconds=round(time.monotonic() - started, 1),
        max_rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)),
        ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
