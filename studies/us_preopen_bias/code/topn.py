"""S24+: daily Top-N long / Top-N short among option-active single stocks (the final deliverable's backtest).

Each day T (decision at 09:30): active pool (point-in-time prefilter) -> a technical score -> the N highest go long, the N
lowest go short -> scored on T's open -> close, net of a round-trip cost.  Standard library only.

    python3 studies/us_preopen_bias/code/topn.py --data DIR [--data DIR] --start 2023-08-01 --end 2024-12-31 --split 2024-05-01
"""
import argparse
import math
import random
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent))
import picks  # noqa: E402
import preopen  # noqa: E402

COST_BP = 10.0
N = 3
MIN_PRICE, MIN_TURNOVER, MIN_OPTION_VOLUME = 3.0, 5e6, 2000


def gate_days(dn):
    """Relaxed tradability, all before T: previous nominal close >= 3, previous 20-day mean turnover >= 5M."""
    ok = set()
    order = sorted(dn)
    for i, d in enumerate(order):
        if i >= 21 and dn[order[i - 1]][0] >= MIN_PRICE and mean(dn[order[j]][3] for j in range(i - 20, i)) >= MIN_TURNOVER:
            ok.add(d)
    return ok


def active_pools(rows, gate, unusual=None, min_ovol=MIN_OPTION_VOLUME):
    """{date: [row]}: gated names with T-1 option volume >= ``min_ovol`` contracts; with ``unusual``, also T-1 option
    volume >= unusual x its 20-session mean (option activity spike)."""
    out = defaultdict(list)
    for r in rows:
        f = r['f']
        if r['date'] not in gate.get(r['symbol'], ()) or (f.get('ovol1') or 0) < min_ovol:
            continue
        if unusual and not (f.get('ovol20') and f['ovol1'] >= unusual * f['ovol20']):
            continue
        if f.get('atr20') is None or r['y'].get('ret_oc') is None:
            continue
        out[r['date']].append(r)
    return out


def pick(pools, score, n=N):
    """[(date, side, row)]: top n by score long, bottom n short (names without a score are skipped)."""
    out = []
    for d in sorted(pools):
        xs = [(score(r['f']), r) for r in pools[d]]
        xs = sorted([(v, r) for v, r in xs if v is not None and math.isfinite(v)], key=lambda t: (t[0], t[1]['symbol']))
        if len(xs) < 2 * n:
            continue
        out += [(d, 1, r) for v, r in xs[-n:]] + [(d, -1, r) for v, r in xs[:n]]
    return out


def evaluate(items, split=None, draws=2000, seed=20260925):
    if not items:
        return {'n': 0}
    rec = [(d, side, side * r['y']['ret_oc'] * 1e4 - COST_BP) for d, side, r in items]
    by_day = defaultdict(list)
    for d, side, x in rec:
        by_day[d].append(x)
    days = sorted(by_day)
    rng = random.Random(seed)
    boots = sorted(mean([x for _ in days for x in by_day[days[rng.randrange(len(days))]]]) for _ in range(draws))
    net = [x for _, _, x in rec]
    wins, losses = [x for x in net if x > 0], [x for x in net if x <= 0]
    m = {'n': len(net), 'days': len(days), 'win': len(wins) / len(net), 'avg_win': mean(wins) if wins else 0.0,
         'avg_loss': mean(losses) if losses else 0.0, 'exp': mean(net), 'ci95': (boots[int(0.025 * draws)], boots[int(0.975 * draws) - 1]),
         'lo90': boots[int(0.05 * draws)], 'pf': sum(wins) / -sum(losses) if losses and sum(losses) < 0 else None}
    m['payoff'] = m['avg_win'] / -m['avg_loss'] if m['avg_loss'] < 0 else None
    for side, name in ((1, 'long'), (-1, 'short')):
        xs = [x for _, s, x in rec if s == side]
        m[name] = (len(xs), sum(1 for x in xs if x > 0) / len(xs) if xs else None, mean(xs) if xs else None)
    spread = defaultdict(lambda: [[], []])
    for d, side, x in rec:
        spread[d][0 if side > 0 else 1].append(x)
    m['spread_pos_days'] = mean(1.0 if mean(a) + mean(b) > 0 else 0.0 for a, b in spread.values() if a and b)
    if split:
        a = [x for d, _, x in rec if d < split]
        b = [x for d, _, x in rec if d >= split]
        m['half1'], m['half2'] = (len(a), mean(a) if a else None), (len(b), mean(b) if b else None)
    return m


def gates(m):
    """Selection: positive net expectancy that survives day resampling, PF >= 1.2, both halves positive, and either
    a win rate >= 53% or a payoff ratio >= 1.3."""
    if not m.get('n'):
        return {'n>=300': False}
    return {'n>=300': m['n'] >= 300, 'exp>0': m['exp'] > 0, 'ci95>0': m['ci95'][0] > 0,
            'pf>=1.2': (m['pf'] or 0) >= 1.2,
            'halves>0': 'half1' in m and all(h is not None and h > 0 for _, h in (m['half1'], m['half2'])),
            'win>=53|payoff>=1.3': m['win'] >= 0.53 or (m['payoff'] or 0) >= 1.3}


def final_gates(m):
    """Validation (one shot): net expectancy > 0 with the 90% lower bound > 0 and PF >= 1.1."""
    return {'exp>0': m['exp'] > 0, 'lo90>0': m['lo90'] > 0, 'pf>=1.1': (m['pf'] or 0) >= 1.1}


def fmt(name, m, g=None):
    if not m.get('n'):
        return '%-26s no picks' % name
    p = lambda x: '  -  ' if x is None else '%5.1f' % (100 * x)
    s = ('%-26s n=%5d days=%3d win=%s%% payoff %s exp %+6.1fbp [%+6.1f,%+6.1f] PF %s | L %d:%s%%:%+.1f S %d:%s%%:%+.1f | '
         'spread>0 days %s%%' % (name, m['n'], m['days'], p(m['win']), '%.2f' % m['payoff'] if m['payoff'] else ' - ',
                                  m['exp'], m['ci95'][0], m['ci95'][1], '%.2f' % m['pf'] if m['pf'] else ' - ',
                                  m['long'][0], p(m['long'][1]), m['long'][2] or 0, m['short'][0], p(m['short'][1]), m['short'][2] or 0,
                                  p(m['spread_pos_days'])))
    if 'half1' in m:
        s += ' | halves %d:%+.1f / %d:%+.1f' % (m['half1'][0], m['half1'][1] or 0, m['half2'][0], m['half2'][1] or 0)
    if g is not None:
        s += '\n      gates ' + ' '.join('%s=%s' % (k, 'Y' if v else 'n') for k, v in g.items()) + \
             '  => ' + ('PASS' if all(g.values()) else 'fail')
    return s


def _ratio(a, b):
    return a / b if a is not None and b else None


SCORES = {   # higher = long, lower = short; all known by 09:30 of T
    'X1_reversal_1d': lambda f: -f['r1_z'] if f.get('r1_z') is not None else None,
    'X2_intraday_momentum': lambda f: _ratio(f.get('id_sum20'), f.get('atr20')),
    'X3_intraday_vs_overnight': lambda f: (_ratio(f['id_sum20'] - f['on_sum20'], f['atr20'])
                                           if f.get('id_sum20') is not None and f.get('on_sum20') is not None else None),
    'X4_gap_fade': lambda f: -f['gap_z'] if f.get('gap_z') is not None else None,
    'X5_put_call_contrarian': lambda f: f.get('pcr_z'),
}


# ---- S25 (notes/S25_PREREG.md): continuation of extreme moves, option-activity spikes ----
SCORES_S25 = {
    'Y1_momentum_1d': lambda f: f['r1_z'] if f.get('r1_z') is not None else None,
    'Y2_gap_continuation': lambda f: f.get('gap_z'),
}


def rank_sum_picks(pools, n=N):
    """Y3 / Y4: sum of the day's ranks of T-1 move and T gap (both in ATR); top n long, bottom n short."""
    out = []
    for d in sorted(pools):
        xs = [r for r in pools[d] if r['f'].get('r1_z') is not None and r['f'].get('gap_z') is not None]
        if len(xs) < 2 * n:
            continue
        r1 = {id(r): k for k, r in enumerate(sorted(xs, key=lambda r: (r['f']['r1_z'], r['symbol'])))}
        gp = {id(r): k for k, r in enumerate(sorted(xs, key=lambda r: (r['f']['gap_z'], r['symbol'])))}
        ranked = sorted(xs, key=lambda r: (r1[id(r)] + gp[id(r)], r['symbol']))
        out += [(d, 1, r) for r in ranked[-n:]] + [(d, -1, r) for r in ranked[:n]]
    return out


# ---- S26 (notes/S26_PREREG.md): options sentiment + volatility premium + closing strength ----
def liquid_pools(pools, top=60):
    return {d: sorted(v, key=lambda r: (-(r['f'].get('ovol1') or 0), r['symbol']))[:top] for d, v in pools.items()}


def composite_scores(pool):
    """z(pcr_z) - z(iv - hv) + z(clv1) within the day's pool; names missing any input are dropped."""
    xs = [r for r in pool if r['f'].get('pcr_z') is not None and r['f'].get('iv') is not None
          and r['f'].get('hv') is not None and r['f'].get('clv1') is not None]
    if len(xs) < 10:
        return {}

    def z(vals):
        m, sd = mean(vals), (mean((v - mean(vals)) ** 2 for v in vals)) ** 0.5
        return [(v - m) / sd if sd > 0 else 0.0 for v in vals]
    a = z([r['f']['pcr_z'] for r in xs])
    b = z([r['f']['iv'] - r['f']['hv'] for r in xs])
    c = z([r['f']['clv1'] for r in xs])
    return {id(r): a[k] - b[k] + c[k] for k, r in enumerate(xs)}


def pick_composite(pools, n=N):
    out = []
    for d in sorted(pools):
        sc = composite_scores(pools[d])
        ranked = sorted((r for r in pools[d] if id(r) in sc), key=lambda r: (sc[id(r)], r['symbol']))
        if len(ranked) < 2 * n:
            continue
        out += [(d, 1, r) for r in ranked[-n:]] + [(d, -1, r) for r in ranked[:n]]
    return out


def basket(items, split=None, draws=2000, seed=20260925):
    """Daily long-basket mean minus short-basket mean (gross bp); a win = a day with a positive spread."""
    days = defaultdict(lambda: [[], []])
    for d, side, r in items:
        days[d][0 if side > 0 else 1].append(r['y']['ret_oc'] * 1e4)
    sp = {d: mean(a) - mean(b) for d, (a, b) in days.items() if a and b}
    if not sp:
        return {'days': 0}
    order = sorted(sp)
    xs = [sp[d] for d in order]
    rng = random.Random(seed)
    boots = sorted(mean(xs[rng.randrange(len(xs))] for _ in xs) for _ in range(draws))
    pos, neg = [x for x in xs if x > 0], [x for x in xs if x <= 0]
    m = {'days': len(xs), 'spread': mean(xs), 'ci95': (boots[int(0.025 * draws)], boots[int(0.975 * draws) - 1]),
         'lo90': boots[int(0.05 * draws)], 'win': len(pos) / len(xs),
         'payoff': mean(pos) / -mean(neg) if pos and neg and mean(neg) < 0 else None}
    if split:
        a = [sp[d] for d in order if d < split]
        b = [sp[d] for d in order if d >= split]
        m['half1'], m['half2'] = mean(a) if a else None, mean(b) if b else None
    return m


def basket_gates(m, final=False, cost=20.0):
    lo = m['lo90'] if final else m['ci95'][0]
    g = {'net>0': m['spread'] - cost > 0, ('lo90-cost>0' if final else 'ci95-cost>0'): lo - cost > 0}
    if not final:
        g['win>=53'] = m['win'] >= 0.53
        g['halves>0'] = m.get('half1') is not None and m['half1'] - cost > 0 and m['half2'] - cost > 0
    return g


def fmt_basket(name, m, g=None):
    s = ('%-26s basket days=%3d spread %+6.1fbp gross [%+6.1f,%+6.1f] (net of 20bp %+6.1f) win(days spread>0) %.1f%% payoff %s' % (
        name, m['days'], m['spread'], m['ci95'][0], m['ci95'][1], m['spread'] - 20, 100 * m['win'],
        '%.2f' % m['payoff'] if m['payoff'] else '-'))
    if m.get('half1') is not None:
        s += ' halves %+.1f / %+.1f' % (m['half1'], m['half2'])
    if g is not None:
        s += '\n      basket gates ' + ' '.join('%s=%s' % (k, 'Y' if v else 'n') for k, v in g.items()) + \
             '  => ' + ('PASS' if all(g.values()) else 'fail')
    return s


# ---- S27 (notes/S27_PREREG.md): relaxed liquidity, one shot on the unused names ranked 301-600 ----
S27_MIN_OPTION_VOLUME = 1000
S27_SPLIT = '2025-01-01'


def iv_half(pools):
    """The half of each day's pool with the higher implied daily move (IV / sqrt(252)); ties by symbol."""
    out = {}
    for d, v in pools.items():
        xs = sorted((r for r in v if r['f'].get('implied_move')), key=lambda r: (-r['f']['implied_move'], r['symbol']))
        out[d] = xs[:len(xs) // 2]
    return out


def s27_runs(pools):
    half = iv_half(pools)
    pcr = SCORES['X5_put_call_contrarian']
    return [('Z1_pcr_top3', pick(pools, pcr)), ('Z2_pcr_ivhalf_top3', pick(half, pcr)),
            ('Z3_pcr_ivhalf_top5', pick(half, pcr, 5)), ('Z4_composite_top3', pick_composite(pools))]


def s27_gates(m, b, cost=20.0):
    """Basket: gross - cost > 0, 95% lower bound - cost > 0, >= 53% of days positive, both halves gross > cost.
    Per pick (net of COST_BP): expectancy > 0 with the 95% lower bound > 0 and PF >= 1.1."""
    bk = {'net>0': b['spread'] - cost > 0, 'ci95-cost>0': b['ci95'][0] - cost > 0, 'win>=53': b['win'] >= 0.53,
          'halves>cost': b.get('half1') is not None and b['half1'] > cost and b['half2'] > cost}
    pk = {'exp>0': m['exp'] > 0, 'ci95>0': m['ci95'][0] > 0, 'pf>=1.1': (m['pf'] or 0) >= 1.1}
    return bk, pk


def dir_move(items):
    """Mean of side x open->close / implied daily move (the options view; descriptive)."""
    xs = [side * r['y']['ret_oc'] / r['f']['implied_move'] for _, side, r in items if r['f'].get('implied_move')]
    return mean(xs) if xs else None


def load(dirs, start, end, exclude=()):
    rows = [r for r in preopen.build(preopen.load(dirs), start, end) if r['symbol'] not in exclude]
    gate = {s: gate_days(v) for s, v in picks.load_nominal(dirs).items()}
    return rows, gate


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', action='append', required=True)
    ap.add_argument('--start', required=True)
    ap.add_argument('--end', required=True)
    ap.add_argument('--split', default=None)
    ap.add_argument('--unusual', type=float, default=None, help='option-activity spike filter, e.g. 1.5')
    ap.add_argument('--exclude', default='')
    ap.add_argument('--only', default=None)
    ap.add_argument('--final', action='store_true')
    ap.add_argument('--round', default='S24', choices=('S24', 'S25-price', 'S25-options', 'S26', 'S27'))
    ap.add_argument('--drop', default='', help='comma list of symbols to drop (e.g. names seen before)')
    a = ap.parse_args()
    excl = set(a.exclude.split(',')) if a.exclude else set()
    excl |= set(a.drop.split(',')) if a.drop else set()
    rows, gate = load(a.data, a.start, a.end, excl)
    if a.round == 'S27':
        pools = active_pools(rows, gate, min_ovol=S27_MIN_OPTION_VOLUME)
        print('days %d, mean active pool %.1f, symbols %d (S27, option volume >= %d)' % (
            len(pools), mean(len(v) for v in pools.values()), len({r['symbol'] for v in pools.values() for r in v}),
            S27_MIN_OPTION_VOLUME))
        for name, items in s27_runs(pools):
            m = evaluate(items, S27_SPLIT)
            b = basket(items, S27_SPLIT)
            bk, pk = s27_gates(m, b)
            print(fmt(name, m, pk))
            print(fmt_basket('', b, bk))
            print('      options view: side x open->close / implied daily move %+.3f' % dir_move(items))
        return
    if a.round == 'S26':
        pools = active_pools(rows, gate)
        liq = liquid_pools(pools)
        pcr = SCORES['X5_put_call_contrarian']
        runs = [('W1_pcr_top3', pick(pools, pcr)), ('W2_pcr_liquid_top3', pick(liq, pcr)),
                ('W3_composite_top3', pick_composite(pools)), ('W4_composite_liquid_top3', pick_composite(liq)),
                ('W5_composite_top5', pick_composite(pools, 5))]
        print('days %d, mean active pool %.1f (S26)' % (len(pools), mean(len(v) for v in pools.values())))
        for name, items in runs:
            if a.only and name.split('_')[0] not in a.only.split(','):
                continue
            m = evaluate(items, a.split)
            print(fmt(name, m, final_gates(m) if a.final else gates(m)))
            b = basket(items, a.split)
            print(fmt_basket('', b, basket_gates(b, final=a.final)))
        return
    if a.round != 'S24':
        runs = []
        if a.round == 'S25-price':
            pools = active_pools(rows, gate)
            runs = [(k, pick(pools, fn)) for k, fn in SCORES_S25.items()] + [('Y3_momentum_plus_gap', rank_sum_picks(pools))]
        else:
            pools = active_pools(rows, gate, unusual=1.5)
            runs = [('Y4_momentum_unusual_options', rank_sum_picks(pools)),
                    ('Y5_put_call_unusual_options', pick(pools, SCORES['X5_put_call_contrarian']))]
        print('days %d, mean active pool %.1f (%s)' % (len(pools), mean(len(v) for v in pools.values()), a.round))
        for name, items in runs:
            if a.only and name.split('_')[0] not in a.only.split(','):
                continue
            m = evaluate(items, a.split)
            print(fmt(name, m, final_gates(m) if a.final else gates(m)))
        return
    pools = active_pools(rows, gate, a.unusual)
    print('days %d, mean active pool %.1f (unusual=%s)' % (len(pools), mean(len(v) for v in pools.values()), a.unusual))
    for name, fn in SCORES.items():
        if a.only and name.split('_')[0] not in a.only.split(','):
            continue
        m = evaluate(pick(pools, fn), a.split)
        print(fmt(name, m, final_gates(m) if a.final else gates(m)))


if __name__ == '__main__':
    main()
