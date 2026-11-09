"""Continuation BG: eligibility ceiling for the existing stale-position rotation."""
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
    bf = json.loads((root / 'studies/trader_replication/reports/gap_review/strong_continue_bf.json').read_text())
    D = Data()
    if D.A['digest'] != prior['dataset_digest'] or D.A['digest'] != bf['dataset_digest']:
        raise ValueError('frozen datasets differ')
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    entries = u1_entries(D, F, H, score)
    del F, M, score, H
    rules = f1_rules(D, 6, (1, 3))
    px, ema = D.base.px(D.A), D.base.ema_inputs(D.A, D.pool, rules)
    targets = {(r['date'], r['code']): r['windows'] for r in bf['records']}
    source = Path(system.__file__).resolve()
    conditions = condition_lines(source)
    line = next(n for (fn, n), condition in conditions.items()
                if fn == 'open_pos' and condition == 'val <= 0.001 * equity')
    records = {}

    def local_trace(frame, event, arg):
        if event != 'return' or frame.f_lineno != line:
            return local_trace
        loc = frame.f_locals
        d, j = loc['d'], loc['j']
        key = (D.days[d], str(D.A['codes'][j]))
        if key not in targets:
            return local_trace
        candidates = []
        for q in loc['pos'].values():
            price = D.A['close'][d, q.j]
            if q.side > 0 and d - q.d0 >= 3 and np.isfinite(price) and price / q.fill - 1 < .02:
                candidates.append((float(price / q.fill - 1), q))
        if candidates:
            ret, q = min(candidates, key=lambda x: x[0])
            records[key] = {'eligible_positions': len(candidates), 'weakest_kind': q.kind,
                            'weakest_code': str(D.A['codes'][q.j]), 'weakest_price_return': ret,
                            'weakest_age': d - q.d0}
        else:
            records[key] = {'eligible_positions': 0}
        return local_trace

    def dispatch(frame, event, arg):
        if event == 'call' and frame.f_code.co_name == 'open_pos' and Path(frame.f_code.co_filename).resolve() == source:
            return local_trace
        return None

    try:
        sys.settrace(dispatch)
        _, _, trades = system.simulate(px, ema, rules, entries, *panels.WINDOW)
    finally:
        sys.settrace(None)
    if digest(trades) != prior['results']['U1']['trades_digest'] or set(records) != set(targets):
        raise AssertionError('trade path or traced targets do not match the original audit')
    covered = {tuple(w) for k, r in records.items() if r['eligible_positions'] for w in targets[k]}
    rows = [{'date': k[0], 'code': k[1], 'windows': targets[k], **r} for k, r in sorted(records.items())]
    kinds = {}
    for r in rows:
        if r['eligible_positions']:
            kinds[r['weakest_kind']] = kinds.get(r['weakest_kind'], 0) + 1
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_ar.py',
             'studies/trader_replication/martin_continue_bg.py', 'studies/trader_replication/martin_strong_scan.py',
             'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], candidates=len(rows), eligible_candidates=sum(r['eligible_positions'] > 0 for r in rows),
               covered_windows=len(covered), weakest_by_kind=kinds, records=rows,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_bg.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print({k: out[k] for k in ('candidates', 'eligible_candidates', 'covered_windows', 'weakest_by_kind')}, flush=True)


if __name__ == '__main__':
    main()
