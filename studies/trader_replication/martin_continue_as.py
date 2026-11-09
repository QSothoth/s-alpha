"""Continuation AS: trace the limiting amount in AR's tiny-entry rejections."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

from . import panels, system
from .martin_continue_a import required_fields
from .martin_continue_ar import condition_lines
from .martin_continue_b_check import digest
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, name_score, u1_entries


def main():
    root = Path(__file__).resolve().parents[2]
    prior = json.loads((root / 'studies/trader_replication/reports/gap_review/strong_continue_ar.json').read_text())
    D = Data()
    if D.A['digest'] != prior['dataset_digest']:
        raise ValueError('frozen dataset differs from the AR audit')
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    original = u1_entries(D, F, H, score)
    satellite = [[e for e in row if e[5] == 'list'] for row in original]
    del F, M, score, H
    rules = f1_rules(D, 6, (1, 3))
    px, ema = D.base.px(D.A), D.base.ema_inputs(D.A, D.pool, rules)
    source = Path(system.__file__).resolve()
    conditions = condition_lines(source)
    line = next(n for (fn, n), condition in conditions.items()
                if fn == 'open_pos' and condition == 'val <= 0.001 * equity')
    result = {}
    for name, book in (('U1', original), ('SAT', satellite)):
        target = {(r['date'], r['code']) for r in prior['results'][name]['records']
                  if r['reason'] == 'open_pos: val <= 0.001 * equity'}
        records = {}

        def local_trace(frame, event, arg):
            if event != 'return' or frame.f_lineno != line:
                return local_trace
            loc = frame.f_locals
            key = (D.days[loc['d']], str(D.A['codes'][loc['j']]))
            if key not in target:
                return local_trace
            equity = loc['equity']
            if equity <= 0:
                records[key] = {'nonpositive_equity': True}
            else:
                values = {'risk_budget': float(loc['frac'] / loc['width']),
                          'position_cap': float(loc['cap']), 'gross_room': float(loc['room'] / equity)}
                minimum = min(values.values())
                records[key] = {'components': values,
                                'limiting': [k for k, v in values.items() if abs(v - minimum) < 1e-12]}
            return local_trace

        def dispatch(frame, event, arg):
            if event == 'call' and frame.f_code.co_name == 'open_pos' and Path(frame.f_code.co_filename).resolve() == source:
                return local_trace
            return None

        try:
            sys.settrace(dispatch)
            _, _, trades = system.simulate(px, ema, rules, book, *panels.WINDOW)
        finally:
            sys.settrace(None)
        if digest(trades) != prior['results'][name]['trades_digest'] or set(records) != target:
            raise AssertionError(f'{name}: trade path or traced target mismatch')
        years = {}
        for year in ('2025', '2026'):
            rows = [v for k, v in records.items() if k[0].startswith(year)]
            valid = [r for r in rows if 'components' in r]
            limited = Counter(k for r in valid for k in r['limiting'])
            medians = {k: float(np.median([r['components'][k] for r in valid])) if valid else None
                       for k in ('risk_budget', 'position_cap', 'gross_room')}
            small = {k: sum(r['components'][k] <= .001 for r in valid) for k in ('risk_budget', 'position_cap', 'gross_room')}
            years[year] = {'targets': len(rows), 'nonpositive_equity': len(rows)-len(valid),
                           'limiting': dict(limited), 'median_fraction_of_equity': medians, 'at_most_point_one_pct': small}
        result[name] = {'by_year': years, 'trades_digest': digest(trades),
                        'records': [{'date': k[0], 'code': k[1], **v} for k, v in sorted(records.items())]}
        print(name, years, flush=True)
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_ar.py',
             'studies/trader_replication/martin_continue_as.py', 'studies/trader_replication/martin_strong_scan.py',
             'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), results=result,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target_path = root / 'studies/trader_replication/reports/gap_review/strong_continue_as.json'
    target_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
