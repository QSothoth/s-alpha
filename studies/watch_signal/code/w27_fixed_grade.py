"""W27 fixed (unfitted) B/S strength grade, checked on local HK data; see notes/W27_PREREG.md."""
import csv
import gzip
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import w12_audit as w12
import w15_market_score as w15
import w16_validate as w16
import w22_trade as w22

ROOT = Path(__file__).resolve().parents[3]
DAILY = ROOT / 'studies/watch_signal/data/day_2024-06_2026-09.csv.gz'


def load_daily():
    rows = defaultdict(list)
    with gzip.open(DAILY, 'rt', newline='') as fh:
        for r in csv.DictReader(fh):
            rows[r['code']].append((r['time_key'][:10], float(r['high']), float(r['low']), float(r['close'])))
    return {c: sorted(v) for c, v in rows.items()}


def atr20(daily, code, day):
    """Mean true range / previous close over the 20 sessions before `day`."""
    rows = [r for r in daily.get(code, ()) if r[0] < day][-21:]
    if len(rows) < 21:
        return None
    out = []
    for (_, h0, l0, c0), (_, h, l, c) in zip(rows, rows[1:]):
        if min(c0, h, l) <= 0:
            return None
        out.append((max(h, c0) - min(l, c0)) / c0)
    return sum(out) / len(out)


def clip(x, lo, hi):
    return max(lo, min(hi, x))


def grade(side, vol_ratio, idx_ret, idx_atr, stk_ret, stk_atr):
    """Fixed W27 grade 1-5 and the three part scores, or None."""
    if None in (vol_ratio, idx_ret, idx_atr, stk_ret, stk_atr) or vol_ratio <= 0 or idx_atr <= 0 or stk_atr <= 0:
        return None
    v = (clip(math.log2(vol_ratio), -1, 2) + 1) / 3
    m = (clip(side * idx_ret / idx_atr, -1, 1) + 1) / 2
    p = (clip(side * stk_ret / stk_atr, -1, 1) + 1) / 2
    return min(5, 1 + int((v + m + p) / 3 * 5)), v, m, p


def collect(segment, daily):
    cfg = w22.SEGMENTS[segment]
    excluded = set(w16.quality_scan(cfg['bars']))
    hsi, refs = w15.load_hsi(cfg['hsi'])
    out = []
    for code, day, previous, bars in w22.sessions(cfg['bars'], cfg['start'], cfg['end'], excluded):
        sa, ia = atr20(daily, code, day), atr20(daily, 'HK.800000', day)
        f = w12.corrected_features(bars)
        for m in w12.replica(bars, f, None, 'B0'):
            i, side = m['i'], (1 if m['side'] == 'BUY' else -1)
            vr = f['vr'][i]
            h = hsi.get(day, {}).get(m['t'])
            g = grade(side, vr if math.isfinite(vr) else None,
                      (h / refs[day] - 1) if h and day in refs else None, ia,
                      (m['close'] / previous - 1) if previous else None, sa)
            if g is None:
                continue
            row = dict(code=code, day=day, t=m['t'], tpb=m['tpb'], g=g[0], v=g[1], m=g[2], p=g[3])
            if i + 31 < len(bars):
                row['f30'] = side * (bars[i + 31][4] / bars[i + 1][4] - 1)
            if i + 2 < len(bars):
                row['fclose'] = side * (bars[-1][4] / bars[i + 1][4] - 1)
                row['r'], row['kind'], _, _ = w22.trade(bars, i, m['side'], float(f['atr'][i]))
            out.append(row)
    return out


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else math.nan


def check(rows):
    share = {k: sum(r['g'] == k for r in rows) / len(rows) for k in range(1, 6)}
    comp = {c: [mean([r[c] for r in rows if r['g'] == k]) for k in range(1, 6)] for c in 'vmp'}
    tiers = {}
    for name, lo, hi in (('tpb<2', 0, 2), ('2<=tpb<5', 2, 5), ('tpb>=5', 5, math.inf)):
        part = [r for r in rows if lo <= r['tpb'] < hi]
        tiers[name] = {k: sum(r['g'] == k for r in part) / len(part) for k in range(1, 6)}
    by_code = defaultdict(list)
    for r in rows:
        by_code[r['code']].append(r['g'])
    big = [v for v in by_code.values() if len(v) >= 50]
    five = sum(5 in v for v in big) / len(big)
    halves = {name: mean([1.0 if r['g'] == 5 else 0.0 for r in rows if test(r['t'])])
              for name, test in (('am', lambda t: t < '12:01'), ('pm', lambda t: t >= '13:00'))}
    gates = dict(distribution=all(0.05 <= v <= 0.40 for v in share.values()),
                 monotonic=all(all(a < b for a, b in zip(v, v[1:])) for v in comp.values()),
                 tiers=all(min(t.values()) >= 0.03 for t in tiers.values()),
                 stocks=five >= 0.80,
                 sessions=all(0.03 <= v <= 0.40 for v in halves.values()))
    outcomes = {}
    for scope, keep in (('all', lambda r: True), ('tpb>=2', lambda r: r['tpb'] >= 2)):
        outcomes[scope] = {k: dict(
            n=sum(1 for r in rows if r['g'] == k and keep(r)),
            f30_bp=mean([r.get('f30') for r in rows if r['g'] == k and keep(r)]) * 1e4,
            fclose_bp=mean([r.get('fclose') for r in rows if r['g'] == k and keep(r)]) * 1e4,
            target=mean([1.0 if r['kind'] == 'target' else 0.0 for r in rows if r['g'] == k and keep(r) and 'kind' in r]),
            gross_r=mean([r.get('r') for r in rows if r['g'] == k and keep(r)])) for k in range(1, 6)}
    return dict(n=len(rows), share=share, components=comp, tiers=tiers, stocks_with_grade5=five,
                stocks_counted=len(big), sessions_grade5=halves, gates=gates,
                passed=all(gates.values()), outcomes=outcomes)


if __name__ == '__main__':
    daily = load_daily()
    print(json.dumps(w12.clean(check(collect(sys.argv[1], daily))), indent=2))
