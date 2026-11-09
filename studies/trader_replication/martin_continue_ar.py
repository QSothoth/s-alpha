"""Continuation AR: trace why the opposite account skipped actual list entries."""
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

from . import panels, system
from .martin_continue_a import required_fields
from .martin_continue_b_check import digest
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, name_score, u1_entries


def condition_lines(path):
    tree = ast.parse(path.read_text())
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in ('take', 'open_pos'):
            for branch in ast.walk(node):
                if isinstance(branch, ast.If):
                    for action in branch.body:
                        if isinstance(action, (ast.Return, ast.Continue, ast.Break)):
                            found[(node.name, action.lineno)] = ast.unparse(branch.test)
    return found


def main():
    D = Data()
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    original = u1_entries(D, F, H, score)
    satellite = [[e for e in row if e[5] == 'list'] for row in original]
    del F, M, score, H
    rules = f1_rules(D, 6, (1, 3))
    px, ema = D.base.px(D.A), D.base.ema_inputs(D.A, D.pool, rules)
    books = {'U1': original, 'SAT': satellite}
    baseline, keys = {}, {}
    for name, book in books.items():
        _, _, baseline[name] = system.simulate(px, ema, rules, book, *panels.WINDOW)
        selected = [t for t in baseline[name] if t['kind'] == 'list' and t['entry'][:4] in ('2025', '2026')]
        keys[name] = {(t['entry'], t['code']) for t in selected}
        if len(keys[name]) != len(selected):
            raise ValueError(f'duplicate list entry in {name}')
    target = {'U1': keys['SAT'] - keys['U1'], 'SAT': keys['U1'] - keys['SAT']}
    source = Path(system.__file__).resolve()
    conditions = condition_lines(source)
    codes = D.A['codes']
    results = {}
    for name, book in books.items():
        records = {}

        def local_trace(frame, event, arg):
            fn, loc = frame.f_code.co_name, frame.f_locals
            relevant = (fn == 'take' and event == 'line' and (fn, frame.f_lineno) in conditions)
            relevant |= fn == 'open_pos' and event == 'return'
            if not relevant or loc.get('kind') != 'list':
                return local_trace
            if 'd' not in loc or 'j' not in loc:
                return local_trace
            key = (D.days[loc['d']], str(codes[loc['j']]))
            if key not in target[name]:
                return local_trace
            if fn == 'take':
                reason = conditions[(fn, frame.f_lineno)]
                records[key] = {'reason': 'take: ' + reason}
            elif arg is None:
                reason = conditions.get((fn, frame.f_lineno), f'unknown return line {frame.f_lineno}')
                rec = {'reason': 'open_pos: ' + reason}
                held = loc.get('pos', {}).get(loc['j'])
                if held is not None:
                    rec.update(held_kind=held.kind, held_entry=D.days[held.d0], held_side=held.side)
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
            _, _, traced = system.simulate(px, ema, rules, book, *panels.WINDOW)
        finally:
            sys.settrace(None)
        if digest(traced) != digest(baseline[name]):
            raise AssertionError(f'tracing changed {name} trade records')
        by_year = {}
        for year in ('2025', '2026'):
            subset = sorted(k for k in target[name] if k[0].startswith(year))
            reasons = Counter(records.get(k, {'reason': 'not_reached'})['reason'] for k in subset)
            held = [records[k] for k in subset if k in records and 'held_kind' in records[k]]
            by_year[year] = {'targets': len(subset), 'reasons': dict(reasons),
                             'held_by_kind': dict(Counter(r['held_kind'] for r in held)),
                             'held_earlier': sum(r['held_entry'] < k[0] for k in subset
                                                 if k in records and (r := records[k]).get('held_entry'))}
        results[name] = {'checked_account': name, 'by_year': by_year,
                         'records': [{'date': k[0], 'code': k[1], **records.get(k, {'reason': 'not_reached'})}
                                     for k in sorted(target[name])], 'trades_digest': digest(traced)}
        print(name, by_year, flush=True)
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_ar.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), results=results,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    out_path = root / 'studies/trader_replication/reports/gap_review/strong_continue_ar.json'
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
