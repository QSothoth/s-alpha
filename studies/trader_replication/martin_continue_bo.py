"""Continuation BO: identify when same-session list reentries follow a close exit."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from . import panels, system
from .martin_continue_a import required_fields
from .martin_continue_bn import classify
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, name_score, u1_entries


def main():
    root = Path(__file__).resolve().parents[2]
    p = root / 'studies/trader_replication/reports/gap_review'
    bn = json.loads((p / 'strong_continue_bn.json').read_text())
    bh = json.loads((p / 'strong_continue_bh.json').read_text())
    D = Data()
    if D.A['digest'] != bn['dataset_digest'] or D.A['digest'] != bh['dataset_digest']:
        raise ValueError('frozen datasets differ')
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    entries = u1_entries(D, F, H, score)
    del F, M, score, H
    rules = f1_rules(D, 6, (1, 3))
    px, ema = D.base.px(D.A), D.base.ema_inputs(D.A, D.pool, rules)
    curve, dates, trades = system.simulate(px, ema, rules, entries, *panels.WINDOW)
    years = system.stats(curve, dates, trades)['by_year']
    if any(abs(years[y] - bh['results']['U1']['metrics']['by_year'][y]) > 1e-10 for y in years):
        raise AssertionError('U1 path differs from BH')
    closed = defaultdict(list)
    for t in trades:
        if t['kind'] == 'list' and t['why'] != 'end':
            closed[(t['code'], t['exit'])].append(t)
    close_reasons = {'trail', 'signal', 'rotate', 'gross', 'time', 'no_follow'}
    before_close_reasons = {'gap_stop', 'stop', 'stop_day0'}
    records = []
    for category, t in classify(trades, D.di):
        if category != 'same_day_exit':
            continue
        prev = [p for p in closed[(t['code'], t['entry'])] if p['entry'] < t['entry']]
        if not prev:
            raise AssertionError('classified same-day exit lacks a prior position')
        previous = max(prev, key=lambda p: p['entry'])
        why = previous['why']
        timing = 'close' if why in close_reasons else 'before_close' if why in before_close_reasons else 'unknown'
        records.append({'date': t['entry'], 'code': t['code'], 'prior_entry': previous['entry'],
                        'prior_exit_reason': why, 'prior_exit_timing': timing, 'open_at_end': t['why'] == 'end'})
    summary = {}
    for year in ('2024', '2025', '2026', 'all'):
        rows = [r for r in records if year == 'all' or r['date'].startswith(year)]
        if year != 'all':
            x = bn['by_entry_year'][year]['same_day_exit']['initial_basis']
            if len(rows) != x['n'] + x['open_at_end']:
                raise AssertionError(f'{year}: same-day count differs from BN')
        summary[year] = {'n': len(rows), 'timing': dict(Counter(r['prior_exit_timing'] for r in rows)),
                         'reasons': dict(Counter(r['prior_exit_reason'] for r in rows))}
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_bn.py',
             'studies/trader_replication/martin_continue_bo.py', 'studies/trader_replication/martin_strong.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), summary=summary, records=records,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = p / 'strong_continue_bo.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
