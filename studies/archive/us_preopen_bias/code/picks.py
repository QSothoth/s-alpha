"""S21: daily long / short lists of volatile, option-liquid names (notes/S21_PREREG.md).  Standard library only.

Each day T (decision at 09:30): eligible names -> a candidate rule returns N longs and N shorts -> scored on T's
open -> close.  One picked name = one pick.

    python3 studies/us_preopen_bias/code/picks.py --data DIR [--data DIR ...] --daily-none DIR \
        --start 2023-08-01 --end 2024-12-31 --split 2024-05-01 [--n 3]
"""
import argparse
import csv
import random
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent))
import preopen  # noqa: E402

MIN_OPTION_VOLUME = 5000
EXCLUDE = ('US.KOD', 'US.AVTX')   # 5m data disagreed with Yahoo (S20 data check)


def load_nominal(dirs):
    """{sym: {date: (close, high, low, turnover)}} from unadjusted daily K: <dir>/daily_none, else <dir>/daily."""
    out = {}
    for d in dirs:
        # a release dir holds adjusted prices in daily/ next to daily_none/; only a raw unadjusted pull names it daily/
        sub = 'daily_none' if (Path(d) / 'daily_none').is_dir() else 'daily'
        for p in Path(d).glob('%s/*.csv' % sub):
            with p.open(encoding='utf-8') as fh:
                out.setdefault('US.' + p.stem, {}).update(
                    {r['date']: (float(r['close']), float(r['high']), float(r['low']), float(r['turnover']))
                     for r in csv.DictReader(fh)})
    return out


def eligible_days(dn):
    """Previous nominal close >= 5, nominal ATR14 >= 0.50, previous 20-day mean turnover >= 10M (all before T)."""
    ok = set()
    order = sorted(dn)
    for i, d in enumerate(order):
        if i < 21:
            continue
        pc = dn[order[i - 1]][0]
        trs = [max(dn[order[j]][1], dn[order[j - 1]][0]) - min(dn[order[j]][2], dn[order[j - 1]][0]) for j in range(i - 14, i)]
        if pc >= 5 and mean(trs) >= 0.5 and mean(dn[order[j]][3] for j in range(i - 20, i)) >= 1e7:
            ok.add(d)
    return ok


def _top(rows, key, n, reverse=True, cond=None):
    xs = [r for r in rows if r['f'].get(key) is not None and (cond is None or cond(r['f']))]
    return sorted(xs, key=lambda r: (r['f'][key], r['symbol']), reverse=reverse)[:n]


def p1_gap_go(pool, n):
    return (_top(pool, 'gap_z', n, True, lambda f: f['gap_z'] >= 0.5),
            _top(pool, 'gap_z', n, False, lambda f: f['gap_z'] <= -0.5))


def p2_gap_fade(pool, n):
    longs, shorts = p1_gap_go(pool, n)
    return shorts, longs


def p3_pm_volume_go(pool, n):
    return (_top(pool, 'pm_ratio', n, True, lambda f: f['pm_ratio'] >= 2 and f['gap'] > 0),
            _top(pool, 'pm_ratio', n, True, lambda f: f['pm_ratio'] >= 2 and f['gap'] < 0))


def p4_inplay_pcr(pool, n):
    inplay = sorted([r for r in pool if r['f'].get('gap_z') is not None and r['f'].get('pcr_z') is not None],
                    key=lambda r: (-abs(r['f']['gap_z']), r['symbol']))[:10]
    ranked = sorted(inplay, key=lambda r: (-r['f']['pcr_z'], r['symbol']))
    k = min(n, len(ranked) // 2)
    return ranked[:k], ranked[len(ranked) - k:] if k else []


def p5_attention_short_fear_long(pool, n):
    shorts = sorted([r for r in pool if r['f'].get('ah_z') is not None and abs(r['f']['ah_z']) >= 1],
                    key=lambda r: (-abs(r['f']['ah_z']), r['symbol']))[:n]
    taken = {r['symbol'] for r in shorts}
    longs = _top([r for r in pool if r['symbol'] not in taken], 'pcr_z', n, True, lambda f: f['pcr_z'] >= 1)
    return longs, shorts


CANDIDATES = {'P1_gap_go': p1_gap_go, 'P2_gap_fade': p2_gap_fade, 'P3_pm_volume_go': p3_pm_volume_go,
              'P4_inplay_pcr': p4_inplay_pcr, 'P5_attention_short_fear_long': p5_attention_short_fear_long}


def pools(rows, elig):
    by_day = defaultdict(list)
    for r in rows:
        f, y = r['f'], r['y']
        if r['symbol'] in EXCLUDE or r['date'] not in elig.get(r['symbol'], ()):
            continue
        if not f.get('ovol1') or f['ovol1'] < MIN_OPTION_VOLUME or not f.get('atr20'):
            continue
        if y.get('hi_oc') is None or y.get('lo_oc') is None:
            continue
        by_day[r['date']].append(r)
    return by_day


def pick_items(by_day, fn, n):
    """[(date, side, row, pool_same_side_rate, pool_mean_abs_atr, pool_mean_mfe_side)]"""
    out = []
    for d in sorted(by_day):
        pool = by_day[d]
        longs, shorts = fn(pool, n)
        up = mean(r['y']['up'] for r in pool)
        dn = mean(r['y']['down'] for r in pool)
        mag = mean(abs(r['y']['ret_oc']) / r['f']['atr20'] for r in pool)
        mfe_l = mean(r['y']['hi_oc'] / r['f']['atr20'] for r in pool)
        mfe_s = mean(-r['y']['lo_oc'] / r['f']['atr20'] for r in pool)
        out += [(d, 1, r, up, mag, mfe_l) for r in longs]
        out += [(d, -1, r, dn, mag, mfe_s) for r in shorts]
    return out


def _boot(by_day, stat, draws=2000, seed=20260925):
    days = sorted(by_day)
    rng = random.Random(seed)
    vals = sorted(stat([x for _ in days for x in by_day[days[rng.randrange(len(days))]]]) for _ in range(draws))
    return vals[int(0.025 * draws)], vals[int(0.975 * draws) - 1], vals[int(0.05 * draws)]


def score(items, split=None):
    if not items:
        return {'n': 0}
    rec = []
    for d, side, r, base, pmag, pmfe in items:
        y, atr = r['y'], r['f']['atr20']
        win = y['up'] if side > 0 else y['down']
        signed = side * y['ret_oc'] / atr
        mfe = (y['hi_oc'] if side > 0 else -y['lo_oc']) / atr
        rec.append({'date': d, 'side': side, 'win': win, 'base': base, 'signed': signed, 'mfe': mfe, 'pmfe': pmfe,
                    'absm': abs(y['ret_oc']) / atr, 'pmag': pmag, 'bp': side * y['ret_oc'] * 1e4})
    by_day = defaultdict(list)
    for x in rec:
        by_day[x['date']].append(x)
    hit = lambda xs: mean(x['win'] for x in xs)
    exc = lambda xs: mean(x['win'] - x['base'] for x in xs)
    lo, hi, lo90 = _boot(by_day, hit)
    elo, ehi, _ = _boot(by_day, exc)
    days_all = {x['date'] for x in rec}
    m = {'n': len(rec), 'days': len(days_all), 'hit': hit(rec), 'ci95': (lo, hi), 'lo90': lo90, 'base': mean(x['base'] for x in rec),
         'excess': exc(rec), 'excess_ci95': (elo, ehi), 'mag_ratio': mean(x['absm'] for x in rec) / mean(x['pmag'] for x in rec),
         'signed_atr': mean(x['signed'] for x in rec), 'mfe_atr': mean(x['mfe'] for x in rec), 'pool_mfe_atr': mean(x['pmfe'] for x in rec),
         'big': mean(x['signed'] >= 0.5 for x in rec), 'bp': mean(x['bp'] for x in rec)}
    for side, name in ((1, 'long'), (-1, 'short')):
        xs = [x for x in rec if x['side'] == side]
        m[name] = (len(xs), hit(xs) if xs else None, mean(x['signed'] for x in xs) if xs else None)
    if split:
        a = [x for x in rec if x['date'] < split]
        b = [x for x in rec if x['date'] >= split]
        m['half1'] = (len(a), hit(a) if a else None)
        m['half2'] = (len(b), hit(b) if b else None)
    return m


def gates(m):
    if not m.get('n'):
        return {'enough': False}
    return {'enough': m['n'] >= 150 and m['days'] >= 60, 'ci95>50': m['ci95'][0] > 0.5, 'excess>=2pp': m['excess'] >= 0.02,
            'halves>51': 'half1' in m and all(h is not None and h > 0.51 for _, h in (m['half1'], m['half2'])),
            'mag>=1.2': m['mag_ratio'] >= 1.2}


def fmt(name, m, g=None):
    if not m.get('n'):
        return '%-32s no picks' % name
    p = lambda x: '  -  ' if x is None else '%5.1f' % (100 * x)
    s = ('%-32s n=%4d days=%3d hit=%s [%s,%s] base=%s exc=%+5.1f [%+5.1f,%+5.1f] mag=%.2fx signed=%+.2fATR mfe=%.2fATR (pool %.2f) '
         'big=%s %+6.1fbp  L %d:%s:%+.2f  S %d:%s:%+.2f' % (
             name, m['n'], m['days'], p(m['hit']), p(m['ci95'][0]), p(m['ci95'][1]), p(m['base']), 100 * m['excess'],
             100 * m['excess_ci95'][0], 100 * m['excess_ci95'][1], m['mag_ratio'], m['signed_atr'], m['mfe_atr'], m['pool_mfe_atr'],
             p(m['big']), m['bp'], m['long'][0], p(m['long'][1]), m['long'][2] or 0, m['short'][0], p(m['short'][1]), m['short'][2] or 0))
    if 'half1' in m:
        s += '  halves %d:%s / %d:%s' % (m['half1'][0], p(m['half1'][1]), m['half2'][0], p(m['half2'][1]))
    if g is not None:
        s += '\n      gates ' + ' '.join('%s=%s' % (k, 'Y' if v else 'n') for k, v in g.items()) + \
             '  => ' + ('PASS' if all(g.values()) else 'fail')
    return s


def score_magnitude(items, draws=2000, seed=20260925):
    """S22: size of the day's move of the listed names vs the same day's eligible pool (direction ignored)."""
    by_day = defaultdict(list)
    for d, side, r, base, pmag, pmfe in items:
        y, atr = r['y'], r['f']['atr20']
        by_day[d].append((abs(y['ret_oc']) / atr, pmag, (y['hi_oc'] - y['lo_oc']) / atr, r))
    if not by_day:
        return {'n': 0}

    def ratios(groups):
        xs = [x for g in groups for x in g]
        return mean(x[0] for x in xs) / mean(x[1] for x in xs)

    days = sorted(by_day)
    rng = random.Random(seed)
    boots = sorted(ratios([by_day[days[rng.randrange(len(days))]] for _ in days]) for _ in range(draws))
    xs = [x for d in days for x in by_day[d]]
    return {'n': len(xs), 'days': len(days), 'mag_ratio': ratios(by_day.values()),
            'mag_ci95': (boots[int(0.025 * draws)], boots[int(0.975 * draws) - 1]), 'mag_lo90': boots[int(0.05 * draws)],
            'names_range_atr': mean(x[2] for x in xs)}


def range_ratio(by_day, items):
    """Mean (high - low) / open / ATR of the listed names over the same days' pool mean."""
    pool = {d: mean((r['y']['hi_oc'] - r['y']['lo_oc']) / r['f']['atr20'] for r in by_day[d]) for d in by_day}
    picked = [((r['y']['hi_oc'] - r['y']['lo_oc']) / r['f']['atr20'], pool[d]) for d, side, r, *_ in items]
    return mean(p for p, _ in picked) / mean(q for _, q in picked) if picked else None


def payoff_table(items):
    """Per pick on the underlying, open -> close of T: win rate, average win / loss (%), payoff ratio, expectancy."""
    rets = [side * r['y']['ret_oc'] for d, side, r, *_ in items]
    if not rets:
        return None
    wins = [x for x in rets if x > 0]
    losses = [x for x in rets if x <= 0]
    aw = mean(wins) if wins else 0.0
    al = mean(losses) if losses else 0.0
    return {'n': len(rets), 'win': len(wins) / len(rets), 'avg_win': aw, 'avg_loss': al,
            'payoff': aw / -al if al < 0 else None, 'exp': mean(rets),
            'pf': sum(wins) / -sum(losses) if sum(losses) < 0 else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', action='append', required=True, help='dirs with daily/ option_stats/ iv/ short_volume/ ext30/')
    ap.add_argument('--daily-none', action='append', required=True)
    ap.add_argument('--start', required=True)
    ap.add_argument('--end', required=True)
    ap.add_argument('--split', default=None)
    ap.add_argument('--n', default='3')
    ap.add_argument('--only', default=None)
    ap.add_argument('--no-gates', action='store_true')
    ap.add_argument('--magnitude', action='store_true', help='S22: magnitude-only check of the P1 / P3 lists')
    ap.add_argument('--payoff', action='store_true', help='descriptive win rate / payoff ratio of the lists, both directions')
    a = ap.parse_args()
    rows = preopen.build(preopen.load(a.data), a.start, a.end)
    elig = {s: eligible_days(v) for s, v in load_nominal(a.daily_none).items()}
    by_day = pools(rows, elig)
    print('eligible name-days %d over %d days (mean pool %.1f)' % (sum(len(v) for v in by_day.values()), len(by_day),
                                                                  mean(len(v) for v in by_day.values())))
    if a.payoff:
        def fade(fn):
            return lambda pool, n: tuple(reversed(fn(pool, n)))
        for label, fn in (('gap list, go with gap', p1_gap_go), ('gap list, fade gap', fade(p1_gap_go)),
                          ('pre-market list, go with gap', p3_pm_volume_go), ('pre-market list, fade gap', fade(p3_pm_volume_go))):
            for side_name, keep in (('both', None), ('longs', 1), ('shorts', -1)):
                items = [x for x in pick_items(by_day, fn, 3) if keep is None or x[1] == keep]
                t = payoff_table(items)
                if t:
                    print('%-30s %-6s n=%4d win=%5.1f%% avg win %+5.2f%% avg loss %+5.2f%% payoff %.2f exp %+6.3f%% PF %.2f' % (
                        label, side_name, t['n'], 100 * t['win'], 100 * t['avg_win'], 100 * t['avg_loss'],
                        t['payoff'] or 0, 100 * t['exp'], t['pf'] or 0))
        return
    if a.magnitude:
        for name, fn in (('M1_gap_inplay', p1_gap_go), ('M2_pm_inplay', p3_pm_volume_go)):
            items = pick_items(by_day, fn, 3)
            m, rr = score_magnitude(items), range_ratio(by_day, items)
            ok = m['mag_ratio'] >= 1.2 and rr >= 1.2 and m['mag_lo90'] > 1.0
            print('%-16s n=%d days=%d  |move| ratio %.2fx [%.2f, %.2f] lo90 %.2f  range ratio %.2fx  => %s' % (
                name, m['n'], m['days'], m['mag_ratio'], m['mag_ci95'][0], m['mag_ci95'][1], m['mag_lo90'], rr,
                'HOLDS' if ok else 'FAILS'))
            d = score(items)
            print('      (descriptive) gap-direction hit %.1f%% [%.1f, %.1f]' % (100 * d['hit'], 100 * d['ci95'][0], 100 * d['ci95'][1]))
        return
    for n in [int(x) for x in a.n.split(',')]:
        for name, fn in CANDIDATES.items():
            if a.only and name.split('_')[0] not in a.only.split(','):
                continue
            m = score(pick_items(by_day, fn, n), a.split)
            print(fmt('%s N=%d' % (name, n), m, None if a.no_gates or n != 3 else gates(m)))


if __name__ == '__main__':
    main()
