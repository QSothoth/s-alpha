"""Score direction candidates: hit rate of side * (close - open) > 0, clustered by trading day.

A candidate is ``fn(features) -> +1 (LONG) / -1 (SHORT) / 0 (no signal)``; it never sees labels.
"""
import random
from collections import defaultdict
from statistics import mean

BOOT = 2000
SEED = 20260924


def signals(rows, fn):
    out = []
    for r in rows:
        side = fn(r['f'])
        if side:
            out.append((r, side))
    return out


def base_rates(rows):
    """Unconditional P(up) and P(down) per symbol over ``rows`` (the whole segment)."""
    up, dn, n = defaultdict(int), defaultdict(int), defaultdict(int)
    for r in rows:
        s = r['symbol']
        n[s] += 1
        up[s] += r['y']['up']
        dn[s] += r['y']['down']
    return {s: (up[s] / n[s], dn[s] / n[s]) for s in n}


def _win(r, side):
    return r['y']['up'] if side > 0 else r['y']['down']


def _boot(by_day, stat, draws=BOOT, seed=SEED):
    days = sorted(by_day)
    rng = random.Random(seed)
    vals = []
    for _ in range(draws):
        pick = [by_day[days[rng.randrange(len(days))]] for _ in days]
        v = stat([x for grp in pick for x in grp])
        if v is not None:
            vals.append(v)
    vals.sort()
    if not vals:
        return None, None, None
    return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1], vals[int(0.05 * len(vals))]


def score(rows, fn, split=None):
    """Metrics for one candidate on one segment.  ``split`` is the date that starts the second half."""
    base = base_rates(rows)
    sig = signals(rows, fn)
    all_days = {r['date'] for r in rows}
    if not sig:
        return {'n': 0}
    items = [(r['date'], _win(r, side), base[r['symbol']][0 if side > 0 else 1], side * r['y']['ret_oc'], side,
              r['f']['is_index']) for r, side in sig]
    by_day = defaultdict(list)
    for it in items:
        by_day[it[0]].append(it)

    def hit(xs):
        return mean(x[1] for x in xs) if xs else None

    def excess(xs):
        return mean(x[1] - x[2] for x in xs) if xs else None

    lo, hi, lo90 = _boot(by_day, hit)
    elo, ehi, _ = _boot(by_day, excess)
    res = {
        'n': len(items), 'days': len(by_day), 'seg_days': len(all_days),
        'per_day': len(items) / len(all_days), 'day_coverage': len(by_day) / len(all_days),
        'hit': hit(items), 'hit_ci95': (lo, hi), 'hit_lo90': lo90,
        'base': mean(x[2] for x in items), 'excess': excess(items), 'excess_ci95': (elo, ehi),
        'mean_bp': 1e4 * mean(x[3] for x in items),
        'long_n': sum(1 for x in items if x[4] > 0), 'long_hit': hit([x for x in items if x[4] > 0]),
        'short_n': sum(1 for x in items if x[4] < 0), 'short_hit': hit([x for x in items if x[4] < 0]),
        'index_n': sum(1 for x in items if x[5]), 'index_hit': hit([x for x in items if x[5]]),
        'single_n': sum(1 for x in items if not x[5]), 'single_hit': hit([x for x in items if not x[5]]),
    }
    if split:
        a = [x for x in items if x[0] < split]
        b = [x for x in items if x[0] >= split]
        res['half1'] = (len(a), hit(a))
        res['half2'] = (len(b), hit(b))
    return res


def gates(m, min_n=150, min_days=60, min_excess=0.02, min_half=0.51):
    """S-round selection gates (pre-registered in notes/S1_PREREG.md)."""
    if not m.get('n'):
        return {'enough': False}
    g = {
        'enough': m['n'] >= min_n and m['days'] >= min_days,
        'ci_above_50': m['hit_ci95'][0] is not None and m['hit_ci95'][0] > 0.5,
        'excess': m['excess'] >= min_excess,
    }
    if 'half1' in m:
        g['halves'] = all(h is not None and h > min_half for _, h in (m['half1'], m['half2']))
    return g


def oneshot_gates(m):
    """One-shot test without a selection segment (notes/S8_PREREG.md)."""
    if not m.get('n'):
        return {'enough': False}
    return {'n>=100': m['n'] >= 100, 'hit>=53': m['hit'] >= 0.53,
            'ci95>50': m['hit_ci95'][0] is not None and m['hit_ci95'][0] > 0.5, 'excess>0': m['excess'] > 0}


def fmt(name, m, g=None):
    if not m.get('n'):
        return '%-28s no signals' % name
    p = lambda x: '  -  ' if x is None else '%5.1f' % (100 * x)
    s = ('%-28s n=%5d days=%4d /day=%4.2f hit=%s [%s,%s] base=%s exc=%+5.1f [%+5.1f,%+5.1f] %+6.1fbp '
         'L %4d:%s S %4d:%s idx %4d:%s stk %4d:%s' % (
             name, m['n'], m['days'], m['per_day'], p(m['hit']), p(m['hit_ci95'][0]), p(m['hit_ci95'][1]),
             p(m['base']), 100 * m['excess'], 100 * m['excess_ci95'][0], 100 * m['excess_ci95'][1], m['mean_bp'],
             m['long_n'], p(m['long_hit']), m['short_n'], p(m['short_hit']),
             m['index_n'], p(m['index_hit']), m['single_n'], p(m['single_hit'])))
    if 'half1' in m:
        s += ' halves %d:%s / %d:%s' % (m['half1'][0], p(m['half1'][1]), m['half2'][0], p(m['half2'][1]))
    if g is not None:
        s += '  gates ' + ' '.join('%s=%s' % (k, 'Y' if v else 'n') for k, v in g.items())
        s += '  => ' + ('PASS' if all(g.values()) else 'fail')
    return s
