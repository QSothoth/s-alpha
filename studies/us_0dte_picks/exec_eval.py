"""Smart buy / smart sell evaluation (notes/EXEC1_PREREG.md) on the frozen test set (notes/EXEC_TESTSET_CN.md).

Every rule sees only completed option 1m bars; a decision on bar m fills on the next traded bar (custody fill
model). A resting limit fills inside the bar that reaches it. Whatever has not filled by the end of the window
is filled the way the test set defines (last trade within 2 minutes before the end, else the next one, 'late').

    PYTHONUTF8=1 python3 -m studies.us_0dte_picks.exec_eval select --dataset <dir> --out <dir>
    PYTHONUTF8=1 python3 -m studies.us_0dte_picks.exec_eval validate --pick BUY:close=B2 ... --dataset <dir> --out <dir>
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
from collections import defaultdict
from pathlib import Path

from custody.dataset import Dataset
from custody.evaluate import PRIMARY_FILL, STRESS_FILLS
from custody.indicators import SessionIndicators
from custody.strategy import session_minute
from .exec_testset import FORCE_LOOKBACK, cases_for, labels, session_end

RULES = {
    'BUY': {'B1': ('trail', .10), 'B2': ('trail', .20), 'B3': ('trail', .30), 'B4': ('half', .20), 'B5': ('limit', .05)},
    'SELL': {'S1': ('trail', .10), 'S2': ('trail', .20), 'S3': ('trail', .30), 'S4': ('half', .20), 'S5': ('limit', .05)},
}
EXEC2 = {
    'BUY': {'BT1': ('twap_guard', .10), 'BT2': ('twap_guard', .20), 'BT3': ('twap_guard', .30),
            'BT4': ('back_twap_guard', .20)},
    'SELL': {'ST1': ('trail', .05), 'ST2': ('half', .10), 'ST3': ('front_twap', 15)},
}
EXEC3 = {   # one fill per order: only the moment is chosen (user 2026-10-26)
    'BUY': {'BM': ('at_fraction', .5), 'BG10': ('guard_wait', .10), 'BG20': ('guard_wait', .20)},
    'SELL': {'SM': ('at_fraction', .5), 'SG10': ('guard_wait', .10), 'SG20': ('guard_wait', .20)},
}
ROUND_POOLS = {'EXEC1': {'BUY': list(RULES['BUY']), 'SELL': list(RULES['SELL'])},
               'EXEC2': {'BUY': list(EXEC2['BUY']), 'SELL': ['S1'] + list(EXEC2['SELL'])},
               'EXEC3': {'BUY': ['BM', 'B2', 'B3', 'BG10', 'BG20'], 'SELL': ['SM', 'S1', 'S2', 'SG10', 'SG20']}}
ALL_RULES = {side: {**RULES[side], **EXEC2[side], **EXEC3[side]} for side in RULES}
KRULES = {   # EXEC4: rules read the signed same-day underlying 1m (notes/EXEC4_PREREG.md)
    'BUY': ('KB1', 'KB2', 'KB3', 'KB4', 'KB5'), 'SELL': ('KS1', 'KS2', 'KS3', 'KS4', 'KS5')}
ROUND_POOLS['EXEC4'] = {'BUY': ['BG10'] + list(KRULES['BUY']), 'SELL': ['S1'] + list(KRULES['SELL'])}
SINGLE_FILL_ROUNDS = {'EXEC3', 'EXEC4'}
TAIL_LIMIT = -0.40   # EXEC3: the 5% worst windows may not cost more than 40% of the arrival price
BASELINES = ('immediate', 'twap', 'end')
BOOTSTRAP = 1000


class Path_:
    """The option bars of one window: (minute, executable price, bar) for the given side."""

    def __init__(self, options, side, start, end, fill):
        self.side, self.end, self.fill = side, end, fill
        price = fill.buy if side == 'BUY' else fill.sell
        self.minutes = sorted(options)
        self.options, self.price = options, price
        self.window = [(m, price(options[m]), options[m]) for m in self.minutes if start + fill.delay_minutes <= m <= end]

    def next_after(self, minute):
        """Fill for a decision taken on bar ``minute``: (price, late)."""
        for m in self.minutes:
            if m > minute:
                return self.price(self.options[m]), m > self.end
        return None, True

    def forced(self):
        near = [m for m in range(self.end - FORCE_LOOKBACK, self.end + 1) if m in self.options
                and self.window and m >= self.window[0][0]]
        if near:
            return self.price(self.options[near[-1]]), False
        price, late = self.next_after(self.end)
        if price is None:  # nothing traded after the end that day: the last trade inside the window, flagged late
            return self.window[-1][1], True
        return price, late


def run_rule(path, kind, x, arrival):
    """Fill price and late flag of one rule on one window."""
    buy = path.side == 'BUY'
    if kind == 'at_fraction':
        first = path.window[0][0]
        due = first + x * (path.end - first)
        for m, p, _ in path.window:
            if m >= due:
                return p, False
        return path.forced()
    if kind == 'guard_wait':
        for m, p, _ in path.window:
            if (p >= arrival * (1 + x)) if buy else (p <= arrival * (1 - x)):
                filled, late = path.next_after(m) if m < path.end else (None, True)
                if filled is not None:
                    return filled, late
                break
        return path.forced()
    if kind == 'front_twap':
        start = path.window[0][0]
        prices = [p for m, p, _ in path.window if m < start + x] or [path.window[0][1]]
        return statistics.mean(prices), False
    if kind in ('twap_guard', 'back_twap_guard'):
        first, last = path.window[0][0], path.end
        slices = [(m, p) for m, p, _ in path.window
                  if kind == 'twap_guard' or m >= first + (last - first) / 2] or [path.window[-1][:2]]
        share, spent, done = 1 / len(slices), 0.0, 0.0
        buying = {m for m, _ in slices}
        for m, p, _ in path.window:
            if p >= arrival * (1 + x):              # runaway guard: the rest at the next trade
                rest, late = path.next_after(m) if m < path.end else path.forced()
                if rest is None:
                    rest, late = path.forced()
                return spent + (1 - done) * rest, late
            if m in buying:
                spent, done = spent + share * p, done + share
        return spent / done if done else path.forced()[0], False
    if kind == 'half':
        rest, late = run_rule(path, 'trail', x, arrival)
        return (arrival + rest) / 2, late
    if kind == 'limit':
        level = arrival * (1 - x) if buy else arrival * (1 + x)
        for m, p, _ in path.window:
            if (p <= level) if buy else (p >= level):
                return level, False
        return path.forced()
    best = None
    for m, p, _ in path.window:
        best = p if best is None else (min(best, p) if buy else max(best, p))
        if (p >= best * (1 + x)) if buy else (p <= best * (1 - x)):
            filled, late = path.next_after(m)
            if filled is not None and m < path.end:
                return filled, late
            break  # triggered on the last bar or nothing traded afterwards: the forced fill applies
    return path.forced()


class Snap:
    """Signed underlying state after the completed bar of one minute (CALL: price, PUT: minus price)."""
    __slots__ = ('c', 'hi', 'lo', 'vwap', 'e9', 'e21', 'atr', 'orh', 'low10', 'day_low', 'range')

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

    @property
    def trend(self):
        return 1 if self.c > self.vwap and self.e9 > self.e21 else -1 if self.c < self.vwap and self.e9 < self.e21 else 0


def underlying_series(data):
    s = 1 if data.case.direction == 'LONG' else -1
    ind, out, lows = SessionIndicators(9, 21, 14, 15), {}, []
    for bar in data.underlying:
        m = session_minute(data.session, bar.close_time)
        ind.update(bar, m)
        hi, lo = max(s * bar.high, s * bar.low), min(s * bar.high, s * bar.low)
        orh = (ind.or_high - ind.or_low) if ind.or_ready else (ind.high - ind.low)
        out[m] = Snap(c=s * bar.close, hi=hi, lo=lo, vwap=s * ind.vwap, e9=s * ind.ema_fast, e21=s * ind.ema_slow,
                      atr=ind.atr, orh=max(orh, ind.atr), low10=min(lows[-10:]) if lows else lo,
                      day_low=min(lows) if lows else lo, range=ind.high - ind.low)
        lows.append(lo)
    return out


def pattern_of(x):
    """EXEC5 pattern at the window start: trend / extension / day range (notes/EXEC5_PREREG.md)."""
    trend = {1: 'with', -1: 'against', 0: 'chop'}[x.trend]
    gap = (x.c - x.vwap) / x.orh
    extension = 'stretched' if gap > .5 else 'sunk' if gap < -.5 else 'normal'
    return '%s/%s/%s' % (trend, extension, 'expanded' if x.range >= 2 * x.orh else 'usual')


def run_krule(path, name, series, arrival, start):
    """Fill price and late flag of one EXEC4 rule."""
    def decide(m):
        if m >= path.end:
            return path.forced()
        filled, late = path.next_after(m)
        return (filled, late) if filled is not None else path.forced()

    first = max(start, 1)
    at_start = series[first]
    if name == 'KS4':
        return run_rule(path, 'trail', .10, arrival) if at_start.trend == 1 else (arrival, False)
    if name == 'KS2' and at_start.trend != 1:
        return arrival, False
    if name == 'KB4' and at_start.trend == 1:
        return arrival, False
    if name == 'KB3' and at_start.c - at_start.vwap <= .5 * at_start.orh:
        return arrival, False
    guard = {'KB1': .20, 'KB2': .20, 'KB3': .20, 'KB4': .10, 'KB5': .20}.get(name)
    touched = armed = made_high = False
    prev, top = None, None
    for m in range(start + 1, path.end + 1):
        x = series.get(m)
        if x is None:
            continue
        option = path.options.get(m)
        if guard is not None and option is not None and path.price(option) >= arrival * (1 + guard):
            return decide(m)
        hit = False
        if name in ('KB1', 'KB4'):
            hit = touched and prev is not None and x.c > prev
            touched = touched or x.c <= x.vwap + .25 * x.atr
        elif name == 'KB2':
            armed = armed or (x.trend == 1 and x.lo <= x.e21)
            hit = armed and x.c >= x.e9
        elif name == 'KB3':
            hit = x.c <= x.vwap + .25 * x.orh
        elif name == 'KB5':
            hit = top is not None and m >= start + 5 and x.c > top
        elif name == 'KS1':
            hit = x.c >= x.vwap + x.orh or x.c < x.vwap - .25 * x.atr
        elif name == 'KS2':
            hit = x.c < x.e21
        elif name == 'KS3':
            hit = x.c < x.low10
        elif name == 'KS5':
            made_high = made_high or (top is not None and x.c > top)
            hit = (made_high and x.c < x.e9) or x.c < x.vwap
        if hit:
            return decide(m)
        prev, top = x.c, x.c if top is None else max(top, x.c)
    return path.forced()


def improvement(side, arrival, price):
    return (arrival - price) / arrival if side == 'BUY' else (price - arrival) / arrival


def evaluate_dataset(roots, fill=PRIMARY_FILL, lengths=('close', 60)):
    rows = []
    for root in roots:
        dataset = Dataset(root, require_0dte=False)
        for case in dataset.cases:
            data = dataset.load(case)
            options = {session_minute(data.session, b.close_time): b for b in data.option}
            series = underlying_series(data)
            for side, start, length, kind in cases_for(data, lengths):
                path = Path_(options, side, start, start + length, fill)
                if not path.window:
                    continue
                arrival = path.window[0][1]
                prices = [p for _, p, _ in path.window]
                twap = statistics.mean(prices)
                end_price, end_late = path.forced()
                best, worst = (min(prices), max(prices)) if side == 'BUY' else (max(prices), min(prices))
                row = {'trade_date': case.trade_date, 'contract': case.contract, 'side': side, 'window': kind,
                       'start': start, 'length': length, 'arrival': arrival, 'twap': twap, 'best': best, 'worst': worst,
                       'fills': {'immediate': (arrival, False), 'twap': (twap, False), 'end': (end_price, end_late)},
                       **labels(data, start, length)}
                for name, (rule, x) in ALL_RULES[side].items():
                    row['fills'][name] = run_rule(path, rule, x, arrival)
                for name in KRULES[side]:
                    row['fills'][name] = run_krule(path, name, series, arrival, start)
                row['regime'] = {1: 'with', -1: 'against', 0: 'chop'}[series[max(start, 1)].trend]
                row['pattern'] = pattern_of(series[max(start, 1)])
                row['right'] = 'CALL' if case.direction == 'LONG' else 'PUT'
                rows.append(row)
    return rows


def metrics(rows, name):
    vals, vs_twap, capture, late = [], [], [], 0
    for r in rows:
        price, is_late = r['fills'][name]
        if price is None:
            continue
        vals.append(improvement(r['side'], r['arrival'], price))
        vs_twap.append(improvement(r['side'], r['twap'], price))
        span = abs(r['worst'] - r['best'])
        if span > 0:
            capture.append(max(0.0, min(1.0, 1 - abs(price - r['best']) / span)))
        late += bool(is_late)
    if not vals:
        return None
    ordered = sorted(vals)
    return {'n': len(vals), 'mean': statistics.mean(vals), 'median': statistics.median(vals),
            'p05': ordered[int(.05 * len(ordered))], 'p95': ordered[int(.95 * len(ordered)) - 1],
            'mean_vs_twap': statistics.mean(vs_twap), 'capture': statistics.mean(capture) if capture else None,
            'late_share': late / len(vals)}


def day_ci(rows, name, draws=BOOTSTRAP, seed=20261026):
    by_day = defaultdict(list)
    for r in rows:
        price, _ = r['fills'][name]
        if price is not None:
            by_day[r['trade_date']].append(improvement(r['side'], r['arrival'], price))
    days = sorted(by_day)
    rng, means = random.Random(seed), []
    for _ in range(draws):
        pool = [v for _ in days for v in by_day[rng.choice(days)]]
        means.append(statistics.mean(pool))
    means.sort()
    return [means[int(.025 * draws)], means[int(.975 * draws) - 1]]


STRATA = ('dte_bucket', 'premium', 'liquidity', 'session_part', 'option_path', 'moneyness', 'regime', 'right', 'pattern')
PATTERN_POOL = {
    'BUY': ['immediate', 'end', 'BM', 'B2', 'B3', 'BG10', 'BG20', 'KB1', 'KB2', 'KB3', 'KB4', 'KB5'],
    'SELL': ['immediate', 'end', 'SM', 'S1', 'S2', 'SG10', 'SG20', 'KS1', 'KS2', 'KS3', 'KS4', 'KS5'],
}
PATTERN_MIN_CASES, PATTERN_MIN_DAYS = 200, 10


def best_rule(rows, names):
    stats = {n: metrics(rows, n) for n in names}
    ok = [n for n in names if stats[n] and stats[n]['p05'] >= TAIL_LIMIT]
    return max(ok, key=lambda n: stats[n]['mean']) if ok else 'immediate'


def build_mapping(rows, names):
    overall = best_rule(rows, names)
    mapping = {}
    for pattern in sorted({r['pattern'] for r in rows}):
        cell = [r for r in rows if r['pattern'] == pattern]
        if len(cell) >= PATTERN_MIN_CASES and len({r['trade_date'] for r in cell}) >= PATTERN_MIN_DAYS:
            mapping[pattern] = best_rule(cell, names)
    return overall, mapping


def apply(rows, overall, mapping, tag):
    return [dict(r, fills={**r['fills'], tag: r['fills'][mapping.get(r['pattern'], overall)]}) for r in rows]


def pattern_study(rows):
    """EXEC5: pattern -> rule mapping, judged by leave-one-day-out against the best single rule."""
    out = {}
    for side in ('BUY', 'SELL'):
        names = PATTERN_POOL[side]
        for window in sorted({r['window'] for r in rows}):
            group = [r for r in rows if r['side'] == side and r['window'] == window]
            overall, mapping = build_mapping(group, names)
            stitched_pattern, stitched_single = [], []
            for day in sorted({r['trade_date'] for r in group}):
                train = [r for r in group if r['trade_date'] != day]
                test = [r for r in group if r['trade_date'] == day]
                o, mp = build_mapping(train, names)
                stitched_pattern += apply(test, o, mp, '_pattern')
                stitched_single += apply(test, o, {}, '_single')
            cells = {}
            for pattern in sorted({r['pattern'] for r in group}):
                cell = [r for r in group if r['pattern'] == pattern]
                cells[pattern] = {'cases': len(cell), 'days': len({r['trade_date'] for r in cell}),
                                  'chosen': mapping.get(pattern, overall),
                                  'means': {n: (metrics(cell, n) or {}).get('mean') for n in names}}
            lodo_pattern, lodo_single = metrics(stitched_pattern, '_pattern'), metrics(stitched_single, '_single')
            out['%s:%s' % (side, window)] = {
                'overall': overall, 'mapping': mapping, 'cells': cells,
                'lodo_pattern': lodo_pattern, 'lodo_single': lodo_single,
                'lodo_immediate': metrics(group, 'immediate'),
                'pattern_effective': (lodo_pattern['mean'] > lodo_single['mean'] and lodo_pattern['mean'] > 0
                                      and lodo_pattern['p05'] >= TAIL_LIMIT)}
    return out


def apply_mapping(rows, study):
    """Report-only: a mapping built on one segment applied to another."""
    out = {}
    for group_key, st in study.items():
        side, window = group_key.split(':')
        group = [r for r in rows if r['side'] == side and r['window'] == window]
        if group:
            out[group_key] = {'pattern': metrics(apply(group, st['overall'], st['mapping'], '_p'), '_p'),
                              'single': metrics(apply(group, st['overall'], {}, '_s'), '_s')}
    return out


def report(rows, ci=True, pool=None):
    out = {}
    for side in ('BUY', 'SELL'):
        for window in sorted({r['window'] for r in rows}):
            group = [r for r in rows if r['side'] == side and r['window'] == window]
            if not group:
                continue
            names = list(BASELINES) + (pool[side] if pool else list(ALL_RULES[side]))
            entry = {name: metrics(group, name) for name in names}
            if ci:
                for name in names:
                    entry[name]['ci95'] = day_ci(group, name)
            entry['_strata'] = {s: {v: {name: (metrics([r for r in group if r[s] == v], name) or {}).get('mean')
                                       for name in names} for v in sorted({str(r[s]) for r in group})}
                                for s in STRATA}
            out['%s:%s' % (side, window)] = entry
    return out


def select_single(entry, side, pool):
    """EXEC3: one-fill candidates and the immediate / end baselines; best mean with a 5% tail >= TAIL_LIMIT."""
    names = [n for n in ['immediate', 'end'] + pool[side] if entry.get(n)]
    ok = [n for n in names if entry[n]['p05'] >= TAIL_LIMIT]
    return max(ok, key=lambda n: entry[n]['mean']) if ok else 'immediate'


def lodo_single(group, side, pool):
    """Leave one day out with the EXEC3/EXEC4 selection rule; returns picks and the stitched out-of-sample metrics."""
    days = sorted({r['trade_date'] for r in group})
    names = ['immediate', 'end'] + pool[side]
    picks, stitched = {}, []
    for day in days:
        train = [r for r in group if r['trade_date'] != day]
        entry = {n: metrics(train, n) for n in names}
        pick = select_single(entry, side, pool)
        picks[day] = pick
        stitched += [dict(r, fills={**r['fills'], '_lodo': r['fills'][pick]}) for r in group if r['trade_date'] == day]
    m = metrics(stitched, '_lodo')
    from collections import Counter
    return {'pick_counts': dict(Counter(picks.values())), 'out_of_sample': m}


def passes_single(entry, name):
    m = entry[name]
    return {'mean_positive': m['mean'] > 0, 'ci_low_positive': m['ci95'][0] > 0, 'tail_within_limit': m['p05'] >= TAIL_LIMIT,
            'late_not_above_end': m['late_share'] <= entry['end']['late_share'] + 1e-9}


def select(entry, side, pool=None):
    """Highest mean improvement whose 5% tail is no worse than TWAP's."""
    names = [n for n in list(BASELINES) + (pool[side] if pool else list(RULES[side])) if entry.get(n)]
    tail = entry['twap']['p05']
    ok = [n for n in names if entry[n]['p05'] >= tail]
    return max(ok, key=lambda n: entry[n]['mean']) if ok else 'twap'


def passes(entry, name):
    m = entry[name]
    return {'mean_positive': m['mean'] > 0, 'ci_low_positive': m['ci95'][0] > 0,
            'not_worse_than_twap': m['mean_vs_twap'] >= 0, 'tail_not_worse_than_twap': m['p05'] >= entry['twap']['p05'],
            'late_not_above_end': m['late_share'] <= entry['end']['late_share'] + 1e-9}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('command', choices=['select', 'validate', 'diagnose', 'patterns'])
    parser.add_argument('--apply-to', action='append', default=[], help='patterns: report the mapping on these datasets')
    parser.add_argument('--dataset', action='append', required=True)
    parser.add_argument('--pick', action='append', default=[], help='SIDE:window=NAME, from the selection report')
    parser.add_argument('--round', choices=sorted(ROUND_POOLS), default='EXEC1')
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    pool = ROUND_POOLS[args.round]
    rows = evaluate_dataset(args.dataset)
    if args.command == 'patterns':
        study = pattern_study(rows)
        result = {'stage': 'patterns', 'datasets': args.dataset, 'cases': len(rows), 'study': study}
        for extra in args.apply_to:
            result.setdefault('applied', {})[extra] = apply_mapping(evaluate_dataset([extra]), study)
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / 'exec5_patterns.json').write_text(json.dumps(result, indent=1, ensure_ascii=False))
        print(json.dumps({g: {'effective': v['pattern_effective'], 'overall': v['overall']} for g, v in study.items()}))
        return
    result = {'stage': args.command, 'round': args.round, 'datasets': args.dataset, 'cases': len(rows),
              'report': report(rows, pool=pool)}
    if args.command == 'select':
        if args.round in SINGLE_FILL_ROUNDS:
            result['selected'] = {g: select_single(e, g.split(':')[0], pool) for g, e in result['report'].items()}
            result['selection_checks'] = {g: passes_single(result['report'][g], n) if n != 'immediate' else None
                                          for g, n in result['selected'].items()}
            if args.round == 'EXEC4':
                result['lodo'] = {}
                for g in result['report']:
                    side, window = g.split(':')
                    group = [r for r in rows if r['side'] == side and r['window'] == window]
                    result['lodo'][g] = lodo_single(group, side, pool)
        else:
            result['selected'] = {g: select(e, g.split(':')[0], pool) for g, e in result['report'].items()}
        if args.round not in ('EXEC1',) and args.round not in SINGLE_FILL_ROUNDS:
            result['selection_checks'] = {g: passes(result['report'][g], n) if n not in BASELINES else None
                                          for g, n in result['selected'].items()}
        stressed = evaluate_dataset(args.dataset, STRESS_FILLS['slippage_0.5'])
        result['stress_slippage_0.5'] = {g: {n: (m or {}).get('mean') for n, m in e.items() if not n.startswith('_')}
                                        for g, e in report(stressed, ci=False, pool=pool).items()}
    elif args.command == 'validate':
        picks = dict(p.split('=') for p in args.pick)
        result['checks'] = {g: {'pick': n, **passes(result['report'][g], n)} for g, n in picks.items()}
        result['passed'] = {g: all(v for k, v in c.items() if k != 'pick') for g, c in result['checks'].items()}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / ('%s_%s.json' % (args.round.lower(), args.command))).write_text(json.dumps(result, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in result.items() if k in ('stage', 'cases', 'selected', 'passed')}, ensure_ascii=False))




# ---------------------------------------------------------------- EXEC6: human-trader overlays
HUMAN = {
    'BUY': {'B0': ('immediate', None), 'HB1': ('immediate', .10), 'HB2': ('immediate', .20)},
    'SELL': {'S0': ('immediate', None), 'S1': ('trail', None), 'HS1': ('immediate', .10), 'HS2': ('immediate', .20),
             'HS3': ('trail', .10)},
}
HUMAN_BASE = {'HB1': 'B0', 'HB2': 'B0', 'HS1': 'S0', 'HS2': 'S0', 'HS3': 'S1'}
OPEN_BUFFER, SPIKE_LOOKBACK, SPIKE_WAIT, LOCAL_SPAN, BAD_SHARE = 5, 3, 5, 5, .20
GUARD_BUY, GUARD_SELL = 1.20, 0.80


def _bar_after(path, minute):
    for m in path.minutes:
        if m > minute:
            return m, path.price(path.options[m])
    return None


def _forced_bar(path):
    near = [m for m in range(path.end - FORCE_LOOKBACK, path.end + 1) if m in path.options and m >= path.window[0][0]]
    if near:
        return near[-1], path.price(path.options[near[-1]]), False
    nxt = _bar_after(path, path.end)
    if nxt:
        return nxt[0], nxt[1], True
    m, p, _ = path.window[-1]
    return m, p, True


def _fill_after(path, minute):
    """Decision on bar ``minute``: fill on the next trade inside the window, else the forced fill."""
    nxt = _bar_after(path, minute) if minute < path.end else None
    return (nxt[0], nxt[1], nxt[0] > path.end) if nxt else _forced_bar(path)


def base_bar(path, base):
    if base == 'immediate':
        m, p, _ = path.window[0]
        return m, p, False
    best = None
    for m, p, _ in path.window:                         # S1: trail 10% from the running best sellable price
        best = p if best is None else max(best, p)
        if p <= best * .9 and m < path.end:
            return _fill_after(path, m)
    return _forced_bar(path)


def human_overlay(path, intent, arrival, spike):
    """Opening buffer, then no chasing a spike / dumping into a flush, with protection and the deadline."""
    m, p, late = intent
    if late:
        return intent
    buy = path.side == 'BUY'
    if m < OPEN_BUFFER:
        later = [x for x in path.minutes if x >= OPEN_BUFFER]
        if not later or later[0] > path.end:
            return _forced_bar(path)
        m = later[0]
        p = path.price(path.options[m])
    before = [x for x in path.minutes if x < m][-(SPIKE_LOOKBACK + 1):]
    if len(before) == SPIKE_LOOKBACK + 1:
        old, last = path.price(path.options[before[0]]), path.price(path.options[before[-1]])
        move = (last / old - 1) if buy else (1 - last / old)
        if move >= spike:
            prev = last
            for x in [y for y in path.minutes if m <= y <= min(path.end, m + SPIKE_WAIT)]:
                q = path.price(path.options[x])
                if (buy and q >= arrival * GUARD_BUY) or (not buy and q <= arrival * GUARD_SELL):
                    return _fill_after(path, x)
                if (q < prev) if buy else (q > prev):
                    return _fill_after(path, x)
                prev = q
            waited = [y for y in path.minutes if m + SPIKE_WAIT <= y <= path.end]
            if waited:
                return waited[0], path.price(path.options[waited[0]]), False
            return _forced_bar(path)
    return m, p, False


def bad_fill(path, minute, price):
    around = [path.price(path.options[x]) for x in path.minutes if abs(x - minute) <= LOCAL_SPAN]
    lo, hi = min(around), max(around)
    if hi <= lo:
        return None
    pos = (price - lo) / (hi - lo)
    return pos >= 1 - BAD_SHARE if path.side == 'BUY' else pos <= BAD_SHARE


def evaluate_human(roots, fill=PRIMARY_FILL, lengths=('close', 60)):
    rows = []
    for root in roots:
        dataset = Dataset(root, require_0dte=False)
        for case in dataset.cases:
            data = dataset.load(case)
            options = {session_minute(data.session, b.close_time): b for b in data.option}
            for side, start, length, kind in cases_for(data, lengths):
                path = Path_(options, side, start, start + length, fill)
                if not path.window:
                    continue
                arrival = path.window[0][1]
                row = {'trade_date': case.trade_date, 'side': side, 'window': kind, 'start': start, 'res': {},
                       **labels(data, start, length)}
                for name, (base, spike) in HUMAN[side].items():
                    intent = base_bar(path, base)
                    m, p, late = intent if spike is None else human_overlay(path, intent, arrival, spike)
                    row['res'][name] = (improvement(side, arrival, p), bad_fill(path, m, p), late)
                rows.append(row)
    return rows


def human_report(rows, draws=BOOTSTRAP, seed=20261026):
    out = {}
    for side in ('BUY', 'SELL'):
        for window in sorted({r['window'] for r in rows}):
            group = [r for r in rows if r['side'] == side and r['window'] == window]
            if not group:
                continue
            entry = {}
            for name in HUMAN[side]:
                vals = sorted(r['res'][name][0] for r in group)
                bads = [r['res'][name][1] for r in group if r['res'][name][1] is not None]
                entry[name] = {'n': len(vals), 'mean': statistics.mean(vals), 'p05': vals[int(.05 * len(vals))],
                               'bad_rate': sum(bads) / len(bads), 'late_share': sum(r['res'][name][2] for r in group) / len(group)}
            days = sorted({r['trade_date'] for r in group})
            by_day = defaultdict(list)
            for r in group:
                by_day[r['trade_date']].append(r)
            rng = random.Random(seed)
            for name, base in HUMAN_BASE.items():
                if name not in HUMAN[side]:
                    continue
                d_mean, d_bad = [], []
                for _ in range(draws):
                    pool = [r for _ in days for r in by_day[rng.choice(days)]]
                    d_mean.append(statistics.mean(r['res'][name][0] - r['res'][base][0] for r in pool))
                    pairs = [(r['res'][name][1], r['res'][base][1]) for r in pool
                             if r['res'][name][1] is not None and r['res'][base][1] is not None]
                    d_bad.append(sum(a for a, _ in pairs) / len(pairs) - sum(b for _, b in pairs) / len(pairs))
                d_mean.sort(), d_bad.sort()
                ci = lambda xs: [xs[int(.025 * draws)], xs[int(.975 * draws) - 1]]
                e = entry[name]
                e.update(base=base, diff_mean_ci95=ci(d_mean), diff_bad_ci95=ci(d_bad))
                e['holds'] = (e['bad_rate'] < entry[base]['bad_rate'] and e['diff_bad_ci95'][1] < 0
                              and e['diff_mean_ci95'][0] >= -.005 and e['p05'] >= entry[base]['p05'])
            out['%s:%s' % (side, window)] = entry
    return out


def human_main(argv=None):
    parser = argparse.ArgumentParser(description='EXEC6 human-trader overlays')
    parser.add_argument('--dataset', action='append', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--tag', default='select')
    args = parser.parse_args(argv)
    rows = evaluate_human(args.dataset)
    result = {'stage': 'EXEC6', 'tag': args.tag, 'datasets': args.dataset, 'cases': len(rows), 'report': human_report(rows)}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / ('exec6_%s.json' % args.tag)).write_text(json.dumps(result, indent=1, ensure_ascii=False))
    print(json.dumps({g: {n: v.get('holds') for n, v in e.items() if 'holds' in v} for g, e in result['report'].items()}))


# ---------------------------------------------------------------- EXEC7: the scenario playbook (notes/EXEC7_PREREG.md)
PLAY_OPEN, PLAY_SPIKE_ATR, PLAY_SPIKE_OPT = 5, 2.0, .15
PLAY_LATE_0DTE = 300                                   # 14:30: a 0DTE window counts its remaining time at half


def _option_change(path, m, bars=3):
    seen = [x for x in path.minutes if x <= m][-(bars + 1):]
    if len(seen) < bars + 1:
        return None
    return path.price(path.options[seen[-1]]) / path.price(path.options[seen[0]]) - 1


def _thin(path, m):
    return sum(1 for x in path.minutes if m - 10 < x <= m) < 5


def scenario(series, path, m):
    x = series[m]
    if m < PLAY_OPEN:
        return 'open'
    thin = _thin(path, m)
    back = series.get(m - 3)
    move = (x.c - back.c) / x.atr if back else 0.0
    opt = None if thin else _option_change(path, m)
    if move >= PLAY_SPIKE_ATR or (opt is not None and opt >= PLAY_SPIKE_OPT):
        return 'spike_up'
    if move <= -PLAY_SPIKE_ATR or (opt is not None and opt <= -PLAY_SPIKE_OPT):
        return 'spike_down'
    if x.c - x.vwap > x.orh:
        return 'stretched'
    if x.c - x.vwap < -x.orh:
        return 'sunk'
    if x.trend == 1:
        return 'with'
    if x.trend == -1:
        return 'against'
    recent = [series[k] for k in range(m - 5, m) if k in series]
    if x.c > x.vwap and any(r.c < r.vwap for r in recent):
        return 'reclaim'
    if x.c < x.vwap and any(r.c > r.vwap for r in recent):
        return 'lose'
    return 'chop'


def play_act(side, scen, series, m):
    x, p = series[m], series.get(m - 1)
    if scen == 'open':
        return False
    up = p is not None and x.c > p.c
    down = p is not None and x.c < p.c
    if scen == 'chop':
        recent = [series[k] for k in range(m - 9, m + 1) if k in series]
        mid = (max(r.hi for r in recent) + min(r.lo for r in recent)) / 2
        return x.c <= mid if side == 'BUY' else x.c >= mid
    if side == 'BUY':
        return {'spike_up': down, 'spike_down': up, 'stretched': x.c - x.vwap <= .5 * x.orh, 'sunk': up,
                'with': p is not None and p.c <= p.e9 + .25 * p.atr and up,
                'against': (up and x.lo >= p.lo) or x.c > x.vwap if p is not None else x.c > x.vwap,
                'reclaim': True,
                'lose': (up and x.lo >= p.lo) or x.c > x.vwap if p is not None else x.c > x.vwap}[scen]
    return {'spike_up': p is not None and x.c <= p.c, 'spike_down': up, 'stretched': down, 'sunk': up,
            'with': x.c < x.e9, 'against': up, 'reclaim': False, 'lose': True}[scen]


def run_playbook(path, series, arrival, start, zero_dte, act=None, guard=(GUARD_BUY, GUARD_SELL), stop_low=False,
                 sell_waits_flush=True):
    """(minute, price, late, trigger) of one playbook order (EXEC7 defaults; EXEC8 passes its own table)."""
    act = act or play_act
    buy, total = path.side == 'BUY', max(path.end - start, 1)
    band, spike_wait = 0, 0
    for m in range(max(start, 1), path.end + 1):
        if m not in series:
            continue
        option = path.options.get(m)
        if option is not None:
            q = path.price(option)
            if (buy and q >= arrival * guard[0]) or (not buy and q <= arrival * guard[1]):
                return (*_fill_after(path, m), 'protect')
        if _thin(path, m) and path.end - m <= 15:
            return (*_fill_after(path, m), 'thin_deadline')
        r = (path.end - m) / total
        if zero_dte and m >= PLAY_LATE_0DTE:
            r /= 2
        scen = scenario(series, path, m)
        if stop_low and not buy and scen != 'open' and series[m].c < series[m].day_low:
            return (*_fill_after(path, m), 'stop_low')
        ok, trigger = act(path.side, scen, series, m), scen
        if not ok and r < .2:
            adverse = scen == 'spike_up' if buy else (sell_waits_flush and scen == 'spike_down')
            if adverse and spike_wait < 1:
                spike_wait += 1
            else:
                ok, trigger = True, 'urgency'
        elif not ok and r < .5:
            band += 1
            if band > 3:
                ok, trigger = True, 'urgency'
        if ok:
            return (*_fill_after(path, m), trigger)
    return (*_forced_bar(path), 'forced')


def evaluate_playbook(roots, fill=PRIMARY_FILL, lengths=('close', 60), second=False):
    from .exec_testset import dte
    rows = []
    for root in roots:
        dataset = Dataset(root, require_0dte=False)
        for case in dataset.cases:
            data = dataset.load(case)
            options = {session_minute(data.session, b.close_time): b for b in data.option}
            series = underlying_series(data)
            zero = dte(data) == 0
            for side, start, length, kind in cases_for(data, lengths):
                path = Path_(options, side, start, start + length, fill)
                if not path.window:
                    continue
                arrival = path.window[0][1]
                row = {'trade_date': case.trade_date, 'side': side, 'window': kind, 'res': {}, **labels(data, start, length)}
                m0, p0, _ = path.window[0]
                row['res']['immediate'] = (0.0, bad_fill(path, m0, p0), False, good_fill(path, m0, p0))
                me, pe, le = _forced_bar(path)
                row['res']['end'] = (improvement(side, arrival, pe), bad_fill(path, me, pe), le, good_fill(path, me, pe))
                human = 'HB2' if side == 'BUY' else 'HS2'
                m, p, late = human_overlay(path, base_bar(path, 'immediate'), arrival, .20)
                row['res'][human] = (improvement(side, arrival, p), bad_fill(path, m, p), late, good_fill(path, m, p))
                m, p, late, trigger = run_playbook(path, series, arrival, start, zero)
                row['res']['playbook'] = (improvement(side, arrival, p), bad_fill(path, m, p), late, good_fill(path, m, p))
                row['trigger'] = trigger
                if second:
                    m, p, late, trigger = run_playbook2(path, series, arrival, start, zero)
                    row['res']['playbook2'] = (improvement(side, arrival, p), bad_fill(path, m, p), late,
                                               good_fill(path, m, p))
                    row['trigger2'] = trigger
                rows.append(row)
    return rows


def good_fill(path, minute, price):
    around = [path.price(path.options[x]) for x in path.minutes if abs(x - minute) <= LOCAL_SPAN]
    lo, hi = min(around), max(around)
    if hi <= lo:
        return None
    pos = (price - lo) / (hi - lo)
    return pos <= BAD_SHARE if path.side == 'BUY' else pos >= 1 - BAD_SHARE


def _summ(rows, name):
    vals = sorted(r['res'][name][0] for r in rows)
    bads = [r['res'][name][1] for r in rows if r['res'][name][1] is not None]
    goods = [r['res'][name][3] for r in rows if r['res'][name][3] is not None]
    return {'n': len(vals), 'mean': statistics.mean(vals), 'p05': vals[int(.05 * len(vals))],
            'bad_rate': sum(bads) / len(bads) if bads else None, 'good_rate': sum(goods) / len(goods) if goods else None,
            'late_share': sum(r['res'][name][2] for r in rows) / len(rows)}


def playbook_report(rows, draws=BOOTSTRAP, seed=20261026):
    out = {}
    for side in ('BUY', 'SELL'):
        for window in sorted({r['window'] for r in rows}):
            group = [r for r in rows if r['side'] == side and r['window'] == window]
            if not group:
                continue
            human = 'HB2' if side == 'BUY' else 'HS2'
            entry = {n: _summ(group, n) for n in ('immediate', 'end', human, 'playbook')}
            days = sorted({r['trade_date'] for r in group})
            by_day = defaultdict(list)
            for r in group:
                by_day[r['trade_date']].append(r)
            rng, d_mean, d_bad = random.Random(seed), [], []
            for _ in range(draws):
                pool = [r for _ in days for r in by_day[rng.choice(days)]]
                d_mean.append(statistics.mean(r['res']['playbook'][0] for r in pool))
                pairs = [(r['res']['playbook'][1], r['res']['immediate'][1]) for r in pool
                         if r['res']['playbook'][1] is not None and r['res']['immediate'][1] is not None]
                d_bad.append(sum(a for a, _ in pairs) / len(pairs) - sum(b for _, b in pairs) / len(pairs))
            d_mean.sort(), d_bad.sort()
            ci = lambda xs: [xs[int(.025 * draws)], xs[int(.975 * draws) - 1]]
            pb = entry['playbook']
            pb.update(diff_mean_ci95=ci(d_mean), diff_bad_ci95=ci(d_bad))
            pb['checks'] = {'bad_rate_lower': pb['bad_rate'] < entry['immediate']['bad_rate'] and pb['diff_bad_ci95'][1] < 0,
                            'mean_not_worse': pb['diff_mean_ci95'][0] >= -.005, 'tail_within_20': pb['p05'] >= -.20,
                            'late_ok': pb['late_share'] <= entry['end']['late_share'] + 1e-9}
            pb['passed'] = all(pb['checks'].values())
            triggers = defaultdict(list)
            for r in group:
                triggers[r['trigger']].append(r)
            entry['by_trigger'] = {t: _summ(rs, 'playbook') for t, rs in sorted(triggers.items())}
            out['%s:%s' % (side, window)] = entry
    return out


def playbook_main(argv=None):
    parser = argparse.ArgumentParser(description='EXEC7 scenario playbook test')
    parser.add_argument('--dataset', action='append', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--tag', default='select')
    args = parser.parse_args(argv)
    rows = evaluate_playbook(args.dataset)
    result = {'stage': 'EXEC7', 'tag': args.tag, 'datasets': args.dataset, 'cases': len(rows), 'report': playbook_report(rows)}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / ('exec7_%s.json' % args.tag)).write_text(json.dumps(result, indent=1, ensure_ascii=False))
    print(json.dumps({g: e['playbook']['passed'] for g, e in result['report'].items()}))


# ---------------------------------------------------------------- EXEC8: playbook v2 (notes/EXEC8_PREREG.md)
PLAY2_GUARD = (1.10, 0.90)   # a guarded fill must leave room inside the -20% tail limit (EXEC8 design reason)


def play2_act(side, scen, series, m):
    """EXEC8 table: sell into strength, leave weakness at once; buy pullbacks, never a spike."""
    x, p = series[m], series.get(m - 1)
    if scen == 'open':
        return False
    if scen == 'chop':
        return play_act(side, scen, series, m)
    up = p is not None and x.c > p.c
    if side == 'BUY':
        pullback = p is not None and p.c <= p.e9 + .25 * p.atr and up
        rebuild = (up and x.lo >= p.lo) or x.c > x.vwap if p is not None else x.c > x.vwap
        return {'spike_up': pullback, 'spike_down': up, 'stretched': x.c - x.vwap <= .5 * x.orh, 'sunk': up,
                'with': pullback, 'against': rebuild, 'reclaim': True, 'lose': rebuild}[scen]
    fade = p is not None and x.c <= p.c
    prior = [series[k].c for k in range(m - 10, m - 1) if k in series]
    push = fade and bool(prior) and p.c >= max(prior)
    return {'spike_up': fade, 'stretched': fade, 'with': push, 'reclaim': push,
            'spike_down': True, 'sunk': True, 'against': True, 'lose': True}[scen]


def run_playbook2(path, series, arrival, start, zero_dte):
    return run_playbook(path, series, arrival, start, zero_dte, act=play2_act, guard=PLAY2_GUARD, stop_low=True,
                        sell_waits_flush=False)


def _paired(group, a, b, draws=BOOTSTRAP, seed=20261026):
    """Day-clustered bootstrap of a - b: mean improvement, bad-fill rate and good-fill rate (95% intervals)."""
    days = sorted({r['trade_date'] for r in group})
    by_day = defaultdict(list)
    for r in group:
        by_day[r['trade_date']].append(r)
    rng, out = random.Random(seed), {'mean': [], 'bad': [], 'good': []}
    for _ in range(draws):
        pool = [r for _ in days for r in by_day[rng.choice(days)]]
        out['mean'].append(statistics.mean(r['res'][a][0] - r['res'][b][0] for r in pool))
        for key, i in (('bad', 1), ('good', 3)):
            pairs = [(r['res'][a][i], r['res'][b][i]) for r in pool
                     if r['res'][a][i] is not None and r['res'][b][i] is not None]
            out[key].append(sum(x for x, _ in pairs) / len(pairs) - sum(y for _, y in pairs) / len(pairs))
    return {k + '_ci95': [sorted(v)[int(.025 * draws)], sorted(v)[int(.975 * draws) - 1]] for k, v in out.items()}


def playbook2_report(rows):
    out = {}
    for side in ('BUY', 'SELL'):
        for window in sorted({r['window'] for r in rows}):
            group = [r for r in rows if r['side'] == side and r['window'] == window]
            if not group:
                continue
            human = 'HB2' if side == 'BUY' else 'HS2'
            entry = {n: _summ(group, n) for n in ('immediate', 'end', human, 'playbook', 'playbook2')}
            pb, imm = entry['playbook2'], entry['immediate']
            pb['vs_immediate'], pb['vs_' + human] = _paired(group, 'playbook2', 'immediate'), _paired(group, 'playbook2', human)
            pb['checks'] = {'bad_rate_lower': pb['bad_rate'] < imm['bad_rate'] and pb['vs_immediate']['bad_ci95'][1] < 0,
                            'mean_not_worse': pb['vs_immediate']['mean_ci95'][0] >= -.005, 'tail_within_20': pb['p05'] >= -.20,
                            'late_ok': pb['late_share'] <= entry['end']['late_share'] + 1e-9}
            pb['passed'] = all(pb['checks'].values())
            if side == 'BUY':
                pb['not_worse_than_HB2'] = (pb['bad_rate'] <= entry['HB2']['bad_rate']
                                            and pb['vs_HB2']['mean_ci95'][0] >= -.005)
            else:
                pb['sells_sharper'] = pb['bad_rate'] < imm['bad_rate'] and pb['good_rate'] > imm['good_rate']
            triggers = defaultdict(list)
            for r in group:
                triggers[r['trigger2']].append(r)
            entry['by_trigger'] = {t: _summ(rs, 'playbook2') for t, rs in sorted(triggers.items())}
            out['%s:%s' % (side, window)] = entry
    return out


def playbook2_main(argv=None):
    parser = argparse.ArgumentParser(description='EXEC8 playbook v2 test')
    parser.add_argument('--dataset', action='append', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--tag', default='select')
    args = parser.parse_args(argv)
    rows = evaluate_playbook(args.dataset, second=True)
    result = {'stage': 'EXEC8', 'tag': args.tag, 'datasets': args.dataset, 'cases': len(rows),
              'report': playbook2_report(rows)}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / ('exec8_%s.json' % args.tag)).write_text(json.dumps(result, indent=1, ensure_ascii=False))
    print(json.dumps({g: e['playbook2']['passed'] for g, e in result['report'].items()}))


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'human':
        human_main(sys.argv[2:])
    elif len(sys.argv) > 1 and sys.argv[1] == 'playbook':
        playbook_main(sys.argv[2:])
    elif len(sys.argv) > 1 and sys.argv[1] == 'playbook2':
        playbook2_main(sys.argv[2:])
    else:
        main()
