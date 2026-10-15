"""W31 rare-high grade cuts on the W27 score; see notes/W31_PREREG.md.

Fits the cuts on the HK selection segment, then checks the HK 2024-12 segment.
"""
import json
import math
from collections import defaultdict

import numpy as np

import w12_audit as w12
import w27_fixed_grade as w27

TARGET = (30, 30, 25, 10, 5)
TOLERANCE = (6, 6, 6, 3, 2)


def score(r):
    return (r['v'] + r['m'] + r['p']) / 3


def regrade(rows, cuts):
    for r in rows:
        r['g'] = 1 + sum(score(r) >= c for c in cuts)
    return rows


def describe(rows):
    out = {}
    for k in range(1, 6):
        part = [r for r in rows if r['g'] == k]
        out[k] = dict(
            share=len(part) / len(rows) * 100,
            vol=float(np.median([2 ** (r['v'] * 3 - 1) for r in part])),
            index_atr=float(np.median([r['m'] * 2 - 1 for r in part])),
            stock_atr=float(np.median([r['p'] * 2 - 1 for r in part])),
            fclose_bp=w27.mean([r.get('fclose') for r in part if r['tpb'] >= 2]) * 1e4,
            target=w27.mean([1.0 if r['kind'] == 'target' else 0.0 for r in part
                             if r['tpb'] >= 2 and 'kind' in r]))
    return out


def gates(rows):
    share = {k: sum(r['g'] == k for r in rows) / len(rows) * 100 for k in range(1, 6)}
    comp = {c: [w27.mean([r[c] for r in rows if r['g'] == k]) for k in range(1, 6)] for c in 'vmp'}
    tiers = []
    for lo, hi in ((0, 2), (2, 5), (5, math.inf)):
        part = [r for r in rows if lo <= r['tpb'] < hi]
        tiers.append(sum(r['g'] == 5 for r in part) / len(part) * 100)
    by_code = defaultdict(list)
    for r in rows:
        by_code[r['code']].append(r['g'])
    big = [v for v in by_code.values() if len(v) >= 50]
    five = sum(5 in v for v in big) / len(big)
    halves = [w27.mean([1.0 if r['g'] == 5 else 0.0 for r in rows if test(r['t'])]) * 100
              for test in (lambda t: t < '12:01', lambda t: t >= '13:00')]
    return dict(share=share, tiers_grade5=tiers, stocks_with_grade5=five, halves_grade5=halves,
                gates=dict(
                    shares=all(abs(share[k] - TARGET[k - 1]) <= TOLERANCE[k - 1] for k in range(1, 6)),
                    monotonic=all(all(a < b for a, b in zip(v, v[1:])) for v in comp.values()),
                    tiers=all(2 <= x <= 10 for x in tiers),
                    stocks=five >= 0.60,
                    halves=all(2 <= x <= 10 for x in halves)))


def main():
    daily = w27.load_daily()
    fit_rows = w27.collect('selection', daily)
    scores = np.array([score(r) for r in fit_rows])
    cuts = [round(float(q), 2) for q in np.quantile(scores, [0.30, 0.60, 0.85, 0.95])]
    check_rows = regrade(w27.collect('validation', daily), cuts)
    regrade(fit_rows, cuts)
    result = dict(cuts=cuts, fit=dict(describe=describe(fit_rows), **gates(fit_rows)),
                  check=dict(describe=describe(check_rows), **gates(check_rows)))
    result['passed'] = all(result['check']['gates'].values())
    print(json.dumps(w12.clean(result), indent=2))


if __name__ == '__main__':
    main()
