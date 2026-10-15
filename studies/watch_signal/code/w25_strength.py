"""W25 cross-stock B/S strength grade 1-5; see notes/W25_PREREG.md.

fit:   python w25_strength.py fit OUT.json        (selection segment)
check: python w25_strength.py check FIT.json      (check segment, one shot)
"""
import argparse
import bisect
import json
import math
from collections import defaultdict

import numpy as np

import w12_audit as w12
import w15_market_score as w15
import w16_validate as w16
import w22_trade as w22

FIT_SEGMENT, CHECK_SEGMENT = 'selection', 'validation'


def collect(segment):
    cfg = w22.SEGMENTS[segment]
    excluded = set(w16.quality_scan(cfg['bars']))
    hsi, refs = w15.load_hsi(cfg['hsi'])
    out, prev = [], {}
    for code, day, previous, bars in w22.sessions(cfg['bars'], cfg['start'], cfg['end'], excluded):
        p = prev.get(code)
        prev[code] = (max(b[2] for b in bars) - min(b[3] for b in bars)) / bars[0][1]
        f = w12.corrected_features(bars)
        for m in w12.replica(bars, f, None, 'B0'):
            i, side = m['i'], (1 if m['side'] == 'BUY' else -1)
            v = f['vr'][i]
            h = hsi.get(day, {}).get(m['t'])
            row = dict(code=code, day=day, t=m['t'], tpb=m['tpb'],
                       V=v if math.isfinite(v) else None,
                       M=side * (h / refs[day] - 1) if h and day in refs else None,
                       P=side * (m['close'] / previous - 1) / p if previous and p and p > 0 else None)
            if i + 31 < len(bars):
                row['f30'] = side * (bars[i + 31][4] / bars[i + 1][4] - 1)
            if i + 2 < len(bars):
                row['fclose'] = side * (bars[-1][4] / bars[i + 1][4] - 1)
                row['r'], row['kind'], _, _ = w22.trade(bars, i, m['side'], float(f['atr'][i]))
            out.append(row)
    return out


def cuts(values):
    return [float(x) for x in np.quantile(np.array(values, dtype=float), np.arange(1, 100) / 100.0)]


def pct(table, x):
    return bisect.bisect_right(table, x)          # 0..99


def score(row, fit):
    if None in (row['V'], row['M'], row['P']):
        return None
    return (pct(fit['V'], row['V']) + pct(fit['M'], row['M']) + pct(fit['P'], row['P'])) / 3.0


def grade(s, fit):
    return None if s is None else 1 + bisect.bisect_right(fit['grade'], s)


def fit_tables(rows):
    fit = {k: cuts([r[k] for r in rows if r[k] is not None]) for k in ('V', 'M', 'P')}
    scores = [score(r, fit) for r in rows]
    fit['grade'] = [float(x) for x in np.quantile([s for s in scores if s is not None], [0.2, 0.4, 0.6, 0.8])]
    fit['n'] = len(rows)
    fit['n_scored'] = sum(s is not None for s in scores)
    return fit


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else math.nan


def check(rows, fit):
    for r in rows:
        r['g'] = grade(score(r, fit), fit)
    g = [r for r in rows if r['g']]
    share = {k: sum(r['g'] == k for r in g) / len(g) for k in range(1, 6)}
    comp = {c: [mean([r[c] for r in g if r['g'] == k]) for k in range(1, 6)] for c in ('V', 'M', 'P')}
    tiers = {}
    for name, lo, hi in (('tpb<2', 0, 2), ('2<=tpb<5', 2, 5), ('tpb>=5', 5, math.inf)):
        part = [r for r in g if lo <= r['tpb'] < hi]
        tiers[name] = {k: sum(r['g'] == k for r in part) / len(part) for k in range(1, 6)} if part else {}
    by_code = defaultdict(list)
    for r in g:
        by_code[r['code']].append(r['g'])
    big = {c: v for c, v in by_code.items() if len(v) >= 50}
    with_five = sum(5 in v for v in big.values()) / len(big)
    halves = {}
    for name, test in (('am', lambda t: t < '12:01'), ('pm', lambda t: t >= '13:00')):
        part = [r for r in g if test(r['t'])]
        halves[name] = sum(r['g'] == 5 for r in part) / len(part)
    gates = dict(
        distribution=all(0.12 <= v <= 0.28 for v in share.values()),
        monotonic=all(all(a < b for a, b in zip(v, v[1:])) for v in comp.values()),
        tiers=all(all(0.08 <= x <= 0.32 for x in t.values()) for t in tiers.values() if t),
        stocks=with_five >= 0.80,
        sessions=all(0.10 <= v <= 0.30 for v in halves.values()))
    report = {}
    for scope, keep in (('all', lambda r: True), ('tpb>=2', lambda r: r['tpb'] >= 2)):
        report[scope] = {}
        for k in range(1, 6):
            part = [r for r in g if r['g'] == k and keep(r)]
            report[scope][k] = dict(
                n=len(part),
                f30_bp=mean([r.get('f30') for r in part]) * 1e4,
                fclose_bp=mean([r.get('fclose') for r in part]) * 1e4,
                target=mean([1.0 if r.get('kind') == 'target' else 0.0 for r in part if 'kind' in r]),
                gross_r=mean([r.get('r') for r in part]))
    return dict(n=len(rows), graded=len(g), share=share, components=comp, tiers=tiers,
                stocks_with_grade5=with_five, stocks_counted=len(big), sessions_grade5=halves,
                gates=gates, passed=all(gates.values()), outcomes=report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('fit', 'check'))
    parser.add_argument('path')
    args = parser.parse_args()
    if args.mode == 'fit':
        fit = fit_tables(collect(FIT_SEGMENT))
        json.dump(fit, open(args.path, 'w'))
        print('fitted', fit['n'], 'scored', fit['n_scored'], 'grade cuts', fit['grade'])
    else:
        fit = json.load(open(args.path))
        print(json.dumps(w12.clean(check(collect(CHECK_SEGMENT), fit)), indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
