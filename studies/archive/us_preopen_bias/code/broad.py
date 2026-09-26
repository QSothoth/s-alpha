"""S23: daily lists on the broad option-active universe, balancing liquidity, move size and option payoff (notes/S23_PREREG.md).

Option-payoff proxy per name-day = |open -> close| / implied daily move (T-1 30-day IV / sqrt(252)).  Standard library only.

    python3 studies/us_preopen_bias/code/broad.py --data DIR [--data DIR] --start 2023-08-01 --end 2024-12-31
"""
import argparse
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean, median, pstdev

sys.path.insert(0, str(Path(__file__).resolve().parent))
import picks  # noqa: E402
import preopen  # noqa: E402

TOP_UNIVERSE = 60
PICKS_PER_DAY = 6
S22_NAMES = {x['code'] for xs in json.load(open(Path(__file__).resolve().parents[1] / 'notes' / 'universe_smallmid.json',
                                                encoding='utf-8'))['themes'].values() for x in xs}


def day_pools(rows, elig):
    """{date: [row]}: top 60 of the superset by the 20-session mean option volume before T-1, then the liquidity gates."""
    by_day = defaultdict(list)
    for r in rows:
        if r['f'].get('ovol20'):
            by_day[r['date']].append(r)
    out = {}
    for d, rs in by_day.items():
        top = sorted(rs, key=lambda r: (-r['f']['ovol20'], r['symbol']))[:TOP_UNIVERSE]
        pool = [r for r in top if d in elig.get(r['symbol'], ()) and (r['f'].get('ovol1') or 0) >= picks.MIN_OPTION_VOLUME
                and r['f'].get('implied_move') and r['f'].get('atr20') and r['f'].get('gap_z') is not None
                and r['y'].get('mag') is not None]
        if pool:
            out[d] = pool
    return out


def _z(vals):
    m, s = mean(vals), pstdev(vals)
    return [(v - m) / s if s > 0 else 0.0 for v in vals]


def b1_gap_size(pool):
    return {id(r): abs(r['f']['gap_z']) for r in pool}


def b2_cheap_options(pool):
    return {id(r): r['f']['atr20'] / r['f']['implied_move'] for r in pool}


def b3_gap_x_cheap(pool):
    return {id(r): abs(r['f']['gap']) / r['f']['implied_move'] for r in pool}


def b4_balanced(pool):
    ok = [r for r in pool if r['f'].get('iv') is not None and r['f'].get('hv') is not None and r['f'].get('ovol20')]
    if len(ok) < 3:
        return {}
    parts = [_z([abs(r['f']['gap_z']) for r in ok]),
             _z([math.log(r['f']['ovol1'] / r['f']['ovol20']) for r in ok]),
             _z([-(r['f']['iv'] - r['f']['hv']) for r in ok]),
             _z([math.log(r['f']['ovol1']) for r in ok])]
    return {id(r): sum(p[k] for p in parts) for k, r in enumerate(ok)}


def b5_liquid_big_gap(pool):
    liquid = sorted(pool, key=lambda r: (-r['f']['ovol1'], r['symbol']))[:30]
    return {id(r): abs(r['f']['gap']) for r in liquid}


CANDIDATES = {'B1_gap_size': b1_gap_size, 'B2_cheap_options': b2_cheap_options, 'B3_gap_x_cheap': b3_gap_x_cheap,
              'B4_balanced': b4_balanced, 'B5_liquid_big_gap': b5_liquid_big_gap}


def select(pools, fn, k=PICKS_PER_DAY):
    """[(date, row, side, pool)] with side = gap direction (context, not validated)."""
    out = []
    for d in sorted(pools):
        pool = pools[d]
        sc = fn(pool)
        ranked = sorted((r for r in pool if id(r) in sc), key=lambda r: (-sc[id(r)], r['symbol']))[:k]
        out += [(d, r, 1 if r['f']['gap'] >= 0 else -1, pool) for r in ranked]
    return out


def evaluate(items, draws=2000, seed=20260925):
    if not items:
        return {'n': 0}
    by_day = defaultdict(list)
    for d, r, side, pool in items:
        pmag = mean(x['y']['mag'] for x in pool)
        pmove = mean(abs(x['y']['ret_oc']) for x in pool)
        pvol = median(x['f']['ovol1'] for x in pool)
        by_day[d].append((r['y']['mag'], pmag, abs(r['y']['ret_oc']), pmove, r['f']['ovol1'], pvol,
                          r['y']['up'] if side > 0 else r['y']['down'], r['symbol']))

    def lift(groups, a, b):
        xs = [x for g in groups for x in g]
        return mean(x[a] for x in xs) / mean(x[b] for x in xs)

    days = sorted(by_day)
    rng = random.Random(seed)
    boots = sorted(lift([by_day[days[rng.randrange(len(days))]] for _ in days], 0, 1) for _ in range(draws))
    xs = [x for d in days for x in by_day[d]]
    return {'n': len(xs), 'days': len(days), 'payoff_lift': lift(by_day.values(), 0, 1),
            'payoff_ci95': (boots[int(0.025 * draws)], boots[int(0.975 * draws) - 1]), 'payoff_lo90': boots[int(0.05 * draws)],
            'move_lift': lift(by_day.values(), 2, 3), 'liq_ratio': median(x[4] for x in xs) / median(x[5] for x in xs),
            'mag_mean': mean(x[0] for x in xs), 'pool_mag_mean': mean(x[1] for x in xs), 'mag_gt1': mean(x[0] > 1 for x in xs),
            'gap_hit': mean(x[6] for x in xs), 'move_mean': mean(x[2] for x in xs), 'names': len({x[7] for x in xs})}


def gates(m, lo_key='payoff_ci95', final=False):
    if not m.get('n'):
        return {'enough': False}
    lo = m['payoff_lo90'] if final else m['payoff_ci95'][0]
    g = {'payoff>=1.2': m['payoff_lift'] >= 1.2, ('lo90>1' if final else 'ci95>1'): lo > 1.0,
         'move>=1.2': m['move_lift'] >= 1.2, 'liq>=1': m['liq_ratio'] >= 1.0}
    if not final:
        g = dict({'n>=300': m['n'] >= 300}, **g)
    return g


def fmt(name, m, g=None):
    if not m.get('n'):
        return '%-20s no picks' % name
    s = ('%-20s n=%4d days=%3d names=%3d payoff-proxy %.2fx [%.2f, %.2f] lo90 %.2f (picks %.2f vs pool %.2f, >1: %.0f%%) '
         'move %.2fx (|oc| %.2f%%) liquidity %.2fx  gap-side hit %.1f%%' % (
             name, m['n'], m['days'], m['names'], m['payoff_lift'], m['payoff_ci95'][0], m['payoff_ci95'][1], m['payoff_lo90'],
             m['mag_mean'], m['pool_mag_mean'], 100 * m['mag_gt1'], m['move_lift'], 100 * m['move_mean'], m['liq_ratio'],
             100 * m['gap_hit']))
    if g is not None:
        s += '\n      gates ' + ' '.join('%s=%s' % (k, 'Y' if v else 'n') for k, v in g.items()) + \
             '  => ' + ('PASS' if all(g.values()) else 'fail')
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', action='append', required=True, help='dirs with daily/ daily_none/ option_stats/ iv/')
    ap.add_argument('--start', required=True)
    ap.add_argument('--end', required=True)
    ap.add_argument('--only', default=None)
    ap.add_argument('--final', action='store_true', help='validation gates (90% lower bound)')
    ap.add_argument('--exclude-s22', action='store_true', help='drop the 34 names whose 2025+ gap magnitude S22 used')
    ap.add_argument('--exclude', default='US.NOK,US.SPCX', help='names failing the Yahoo / Tencent check')
    ap.add_argument('--payoff', action='store_true', help='descriptive win rate / payoff ratio per pick')
    a = ap.parse_args()
    excl = set(a.exclude.split(',')) if a.exclude else set()
    rows = [r for r in preopen.build(preopen.load(a.data), a.start, a.end) if r['symbol'] not in excl]
    if a.exclude_s22:
        rows = [r for r in rows if r['symbol'] not in S22_NAMES]
    elig = {s: picks.eligible_days(v) for s, v in picks.load_nominal(a.data).items()}
    pools = day_pools(rows, elig)
    print('days %d, mean pool %.1f, superset rows %d' % (len(pools), mean(len(v) for v in pools.values()), len(rows)))
    if a.payoff:   # descriptive: per pick on the underlying, open -> close, and the best intraday reach vs implied
        for name, fn in CANDIDATES.items():
            if a.only and name.split('_')[0] not in a.only.split(','):
                continue
            items = select(pools, fn)
            for label, flip in (('with gap', 1), ('fade gap', -1)):
                t = picks.payoff_table([(d, side * flip, r) for d, r, side, pool in items])
                reach = mean(max(r['y']['hi_oc'], -r['y']['lo_oc']) / r['f']['implied_move'] for d, r, side, pool in items)
                print('%-20s %-8s n=%4d win=%5.1f%% avg win %+5.2f%% avg loss %+5.2f%% payoff %.2f exp %+6.3f%% PF %.2f  '
                      'best intraday reach / implied %.2f' % (name, label, t['n'], 100 * t['win'], 100 * t['avg_win'],
                                                             100 * t['avg_loss'], t['payoff'] or 0, 100 * t['exp'], t['pf'] or 0, reach))
        return
    for name, fn in CANDIDATES.items():
        if a.only and name.split('_')[0] not in a.only.split(','):
            continue
        m = evaluate(select(pools, fn))
        print(fmt(name, m, gates(m, final=a.final)))


if __name__ == '__main__':
    main()
