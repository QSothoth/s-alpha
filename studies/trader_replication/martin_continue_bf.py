"""Continuation BF: trace every U1 candidate in BE's unheld big-move windows."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

from . import panels, system
from .martin_continue_a import required_fields
from .martin_continue_ar import condition_lines
from .martin_continue_b_check import digest
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, name_score, u1_entries


def main():
    root = Path(__file__).resolve().parents[2]
    prior = json.loads((root / 'studies/trader_replication/reports/gap_review/strong_continue_ar.json').read_text())
    funnel = json.loads((root / 'studies/trader_replication/reports/gap_review/strong_continue_be.json').read_text())
    D = Data()
    if D.A['digest'] != prior['dataset_digest'] or D.A['digest'] != funnel['dataset_digest']:
        raise ValueError('frozen datasets differ')
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    entries = u1_entries(D, F, H, score)
    del F, M, score, H
    windows = [w for w in funnel['windows'] if w['stage'] == 'candidate_no_hold']
    locations = {(date, ticker): j for _, j, ticker, _, date in D.big}
    targets = {}
    for w in windows:
        j = locations[(w['date'], w['ticker'])]
        code = str(D.A['codes'][j])
        for day in range(D.di[w['date']], D.di[w['end']] + 1):
            for e in entries[day]:
                if e[1] == j and e[2] > 0 and e[5] == 'list':
                    targets.setdefault((D.days[day], code), []).append((w['date'], w['ticker']))
    rules = f1_rules(D, 6, (1, 3))
    px, ema = D.base.px(D.A), D.base.ema_inputs(D.A, D.pool, rules)
    source = Path(system.__file__).resolve()
    conditions = condition_lines(source)
    records = {}

    def local_trace(frame, event, arg):
        fn, loc = frame.f_code.co_name, frame.f_locals
        relevant = fn == 'take' and event == 'line' and (fn, frame.f_lineno) in conditions
        relevant |= fn == 'open_pos' and event == 'return'
        if not relevant or loc.get('kind') != 'list' or 'd' not in loc or 'j' not in loc:
            return local_trace
        key = (D.days[loc['d']], str(D.A['codes'][loc['j']]))
        if key not in targets:
            return local_trace
        if fn == 'take':
            records[key] = {'reason': 'take: ' + conditions[(fn, frame.f_lineno)]}
        elif arg is None:
            condition = conditions.get((fn, frame.f_lineno), f'unknown return line {frame.f_lineno}')
            rec = {'reason': 'open_pos: ' + condition}
            held = loc.get('pos', {}).get(loc['j'])
            if held is not None:
                rec.update(held_side=held.side, held_kind=held.kind, held_entry=D.days[held.d0])
            if condition == 'val <= 0.001 * equity' and loc['equity'] > 0:
                values = {'risk_budget': loc['frac'] / loc['width'], 'position_cap': loc['cap'],
                          'gross_room': loc['room'] / loc['equity']}
                smallest = min(values.values())
                rec['limiting'] = [k for k, v in values.items() if abs(v - smallest) < 1e-12]
            records[key] = rec
        else:
            records[key] = {'reason': 'opened'}
        return local_trace

    def dispatch(frame, event, arg):
        if event == 'call' and frame.f_code.co_name in ('take', 'open_pos') and Path(frame.f_code.co_filename).resolve() == source:
            return local_trace
        return None

    try:
        sys.settrace(dispatch)
        _, _, trades = system.simulate(px, ema, rules, entries, *panels.WINDOW)
    finally:
        sys.settrace(None)
    if digest(trades) != prior['results']['U1']['trades_digest']:
        raise AssertionError('tracing changed U1 trade records')
    if any(r['reason'] == 'opened' for r in records.values()):
        raise AssertionError('BE says unheld but an original list candidate opened')
    rows = [{'date': k[0], 'code': k[1], 'windows': targets[k], **records.get(k, {'reason': 'not_reached'})}
            for k in sorted(targets)]
    reasons = Counter(r['reason'] for r in rows)
    limiting = Counter(k for r in rows for k in r.get('limiting', []))
    coverage = {}
    for reason in reasons:
        matched = {tuple(w) for r in rows if r['reason'] == reason for w in r['windows']}
        coverage[reason] = len(matched)
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_ar.py',
             'studies/trader_replication/martin_continue_bf.py', 'studies/trader_replication/martin_strong_scan.py',
             'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], window_count=len(windows), candidate_count=len(targets),
               reasons=dict(reasons), limiting=dict(limiting), window_coverage=coverage, records=rows,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_bf.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: out[k] for k in ('window_count', 'candidate_count', 'reasons', 'limiting', 'window_coverage')}, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
