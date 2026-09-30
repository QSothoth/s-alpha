"""P4: post-hoc validation of A1 / A4 and filters on A1 (P3c).

Pre-registered in notes/P4_PREREG.md.  Offline and standard library only.  Run from the
repository root:

    python3 -m studies.us_0dte_picks.p4 select --out <new.json>
    python3 -m studies.us_0dte_picks.p4 validate --select-report <select.json> --out <new.json>
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from math import sqrt
from pathlib import Path
import random
from statistics import mean

from . import daily_k, p3

PREREG = p3.HERE / 'notes' / 'P4_PREREG.md'
PREREG_SHA256 = 'b144feaedb2433d0cc64fa4d961bd813dd54dd61b8b1ad699031e5cbfe145956'
FILTERS = ('C1_MARKET_ALIGN', 'C2_REL_STRENGTH', 'C3_EFFICIENCY', 'C4_VWAP_HOLD', 'C5_LATE_CONFIRM')
POST_HOC = ('A1_ORB', 'A4_THRUST_FOLLOW')
WINDOW, HALF = ('2023-06-26', '2026-09-25'), '2025-02-01'
LATE_INDEX, LATE_REMAINING = 11, 330  # the 10:30 bar


def first_touch_from(bars, entry_index, entry, sigma_rem, side):
    """p3.first_touch with a movable entry bar; scanning starts at the next bar."""
    target, stop = entry * (1 + side * p3.TARGET * sigma_rem), entry * (1 - side * p3.STOP * sigma_rem)
    best = 0.0
    for index in range(entry_index + 1, len(bars)):
        high, low = bars[index][2], bars[index][3]
        if (low <= stop) if side > 0 else (high >= stop):
            return -p3.STOP, False, True, best / sigma_rem, index, stop
        best = max(best, (high / entry - 1) if side > 0 else (1 - low / entry))
        if (high >= target) if side > 0 else (low <= target):
            return p3.TARGET, True, False, best / sigma_rem, index, target
    result = side * (bars[-1][4] / entry - 1) / sigma_rem
    return min(max(result, -p3.STOP), p3.TARGET), False, False, best / sigma_rem, len(bars) - 1, bars[-1][4]


def option_estimate(entry, exit_price, exit_index, iv, side, remaining):
    vol, year = p3.IV_SCALE * iv / 100, 390 * 252
    start = p3.bs_price(entry, entry, vol, remaining / year, side)
    end = p3.bs_price(exit_price, entry, vol, (390 - 5 * (exit_index + 1)) / year, side)
    return end / start - 1 if start > 0 else None


def spy_context():
    bars, _ = p3.sessions([str(Path(folder) / 'SPY.csv') for folder in p3.SELECT_K5['core']])
    ivs = p3.side_tables('SPY')[2]
    out = {}
    for day, day_bars in bars.items():
        iv = daily_k.iv_before(ivs, day)
        if iv:
            out[day] = (day_bars[p3.ENTRY_BAR - 1][4] / day_bars[0][1] - 1, iv / 100 / sqrt(252))
    return out


def augment(record, bars, spy):
    first6, o, p10 = bars[:6], bars[0][1], record['p10']
    high, low = max(b[2] for b in first6), min(b[3] for b in first6)
    record['eff'] = abs(p10 - o) / (high - low) if high > low else 0.0
    value = volume = 0.0
    sides = []
    for bar in first6:
        value += (bar[2] + bar[3] + bar[4]) / 3 * bar[5]
        volume += bar[5]
        vwap = value / volume if volume else bar[4]
        sides.append(1 if bar[4] > vwap else -1 if bar[4] < vwap else 0)
    record['vwap_sides'] = sides
    sigma = record['sigma_rem'] / sqrt(p3.REMAINING / 390)
    record['sigma'] = sigma
    context = spy.get(record['day'])
    record['spy_drive_z'] = context[0] / context[1] if context else None
    record['rel'] = (p10 / o - 1) - context[0] if context else None
    record['or5'] = (bars[0][2], bars[0][3])
    p1030 = bars[LATE_INDEX][4]
    record['p1030'] = p1030
    late_rem = sigma * sqrt(LATE_REMAINING / 390)
    for side in (1, -1):
        record['late', side] = first_touch_from(bars, LATE_INDEX, p1030, late_rem, side)


def filter_signal(record, name):
    base = p3.signal(record, 'A1_ORB')
    if not base:
        return None
    side, rank = base
    ok = {'C1_MARKET_ALIGN': record['spy_drive_z'] is not None and side * record['spy_drive_z'] >= .25,
          'C2_REL_STRENGTH': record['rel'] is not None and side * record['rel'] >= .5 * record['sigma'],
          'C3_EFFICIENCY': record['eff'] >= .6,
          'C4_VWAP_HOLD': all(s == side for s in record['vwap_sides']),
          'C5_LATE_CONFIRM': (record['p1030'] > record['or5'][0] if side > 0 else record['p1030'] < record['or5'][1])
                             and side * (record['p1030'] - record['p10']) > 0}[name]
    return (side, rank) if ok else None


def row(record, side, late):
    key = 'late' if late else 'outcome'
    result, target, stop, best, index, price = record[key, side]
    entry, remaining = (record['p1030'], LATE_REMAINING) if late else (record['p10'], p3.REMAINING)
    return {'payoff': result, 'target': target, 'stop': stop, 'chop': best < p3.CHOP, 'side': side,
            'edge': target - record[key, -side][1],
            'option': option_estimate(entry, price, index, record['iv'], side, remaining)}


def picks(records, name):
    signal = (lambda r: p3.signal(r, name)) if name in POST_HOC else (lambda r: filter_signal(r, name))
    late = name == 'C5_LATE_CONFIRM'
    by_day = defaultdict(list)
    for record in records:
        hit = signal(record)
        if hit:
            by_day[record['day']].append((-hit[1], record['symbol'], hit[0], record))
    return {day: [row(record, side, late) for _, _, side, record in sorted(items)[:p3.TOP]] for day, items in by_day.items()}


def summarize(rows, half):
    flat = [r for day in rows for r in rows[day]]
    if not flat:
        return {'picks': 0}
    order, rng = sorted(rows), random.Random(p3.SEED)
    boots = []
    for _ in range(p3.DRAWS):
        sample = [r for _ in order for r in rows[order[rng.randrange(len(order))]]]
        boots.append((mean(r['payoff'] for r in sample), mean(r['edge'] for r in sample)))
    q = lambda k, p: sorted(b[k] for b in boots)[int(p * p3.DRAWS)]
    options = [r['option'] for r in flat if r['option'] is not None]
    halves = [[r for day in rows if (day < half) == first for r in rows[day]] for first in (True, False)]
    return {'picks': len(flat), 'dates': len(rows), 'per_date': len(flat) / len(rows),
            'target_rate': mean(r['target'] for r in flat), 'stop_rate': mean(r['stop'] for r in flat),
            'chop_rate': mean(r['chop'] for r in flat), 'payoff': mean(r['payoff'] for r in flat),
            'payoff_ci95': [q(0, .025), q(0, .975)], 'payoff_lo90': q(0, .05),
            'edge': mean(r['edge'] for r in flat), 'edge_ci95': [q(1, .025), q(1, .975)], 'edge_lo90': q(1, .05),
            'halves_payoff': [mean(r['payoff'] for r in part) if part else None for part in halves],
            'long': sum(r['side'] > 0 for r in flat), 'short': sum(r['side'] < 0 for r in flat),
            'option_gross_mean': mean(options) if options else None,
            'option_gross_median': sorted(options)[len(options) // 2] if options else None,
            'option_doubled_rate': mean(o >= 1 for o in options) if options else None}


def select_gates(result, base_rate):
    if not result.get('picks'):
        return {'picks': False}
    return {'picks>=100': result['picks'] >= 100, 'dates>=50': result['dates'] >= 50,
            'target>=33%': result['target_rate'] >= .33, 'target>=A1+5pp': result['target_rate'] >= base_rate + .05,
            'payoff_ci95_low>0': result['payoff_ci95'][0] > 0, 'edge>=10pp': result['edge'] >= .10,
            'edge_ci95_low>0': result['edge_ci95'][0] > 0,
            'halves_payoff>0': all(v is not None and v > 0 for v in result['halves_payoff'])}


def validate_gates(result, filtered):
    if result.get('picks', 0) < 40:
        return {'picks>=40': False}
    gates = {'picks>=40': True, 'payoff_lo90>0': result['payoff_lo90'] > 0, 'edge_lo90>0': result['edge_lo90'] > 0}
    if filtered:
        gates['target>=30%'] = result['target_rate'] >= .30
    return gates


def build(phase):
    spy = spy_context()
    loaded = [(symbol, *p3.sessions(paths)) for symbol, paths in p3.universe(phase, 'a')]
    _, reference = p3.sessions([str(Path(folder) / 'AAPL.csv') for folder in p3.SELECT_K5['core']])
    calendar = sorted(reference.union(*(seen for _, _, seen in loaded)))
    records = []
    for symbol, bars, _ in loaded:
        weekly, mon_wed = daily_k.schedule(symbol)
        earnings = daily_k.reaction_days(symbol, calendar)
        for record in p3.features(symbol, bars, calendar, p3.side_tables(symbol), weekly, mon_wed, earnings, None, WINDOW):
            augment(record, bars[record['day']], spy)
            records.append(record)
    return records


def tier(result):
    rate = result.get('target_rate') or 0
    return 'A' if rate >= .40 else 'B' if rate >= .33 else '-'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('phase', choices=('select', 'validate'))
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--select-report', type=Path)
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error('refusing to overwrite ' + str(args.out))
    if hashlib.sha256(PREREG.read_bytes()).hexdigest() != PREREG_SHA256:
        raise SystemExit('P4_PREREG.md changed after registration')
    if args.phase == 'validate' and args.select_report is None:
        parser.error('validate needs --select-report')
    records = build(args.phase)
    report = {'study': 'P4', 'phase': args.phase, 'preregistration_sha256': PREREG_SHA256,
              'code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'name_days': len(records), 'names': len({r['symbol'] for r in records})}
    if args.phase == 'select':
        results = {name: summarize(picks(records, name), HALF) for name in ('A1_ORB',) + FILTERS}
        base = results['A1_ORB']['target_rate']
        for name in FILTERS:
            results[name]['gates'] = select_gates(results[name], base)
        report.update(a1_base_target_rate=base, results=results,
                      passed=[name for name in FILTERS if all(results[name]['gates'].values())])
    else:
        passed = json.loads(args.select_report.read_text(encoding='utf-8'))['passed']
        judged = list(POST_HOC) + passed
        results = {name: summarize(picks(records, name), HALF) for name in judged}
        for name in judged:
            results[name]['gates'] = validate_gates(results[name], name in FILTERS)
        report.update(judged=judged, results=results,
                      validated=[name for name in judged if all(results[name]['gates'].values())])
    for name, r in report['results'].items():
        r['tier'] = tier(r)
        if not r.get('picks'):
            print('%-17s no picks' % name)
            continue
        print('%-17s picks %4d dates %3d target %5.1f%% stop %5.1f%% chop %5.1f%% payoff %+.3f (%+.3f..%+.3f) edge %+5.1f%% (%+5.1f..%+5.1f) opt %+.0f%%/%+.0f%% dbl %4.1f%% tier %s' % (
            name, r['picks'], r['dates'], 100 * r['target_rate'], 100 * r['stop_rate'], 100 * r['chop_rate'], r['payoff'],
            r['payoff_ci95'][0], r['payoff_ci95'][1], 100 * r['edge'], 100 * r['edge_ci95'][0], 100 * r['edge_ci95'][1],
            100 * (r['option_gross_mean'] or 0), 100 * (r['option_gross_median'] or 0), 100 * (r['option_doubled_rate'] or 0), r['tier']))
    print({key: report[key] for key in ('name_days', 'names', 'passed', 'judged', 'validated') if key in report})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=1, default=str)
        handle.write('\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
