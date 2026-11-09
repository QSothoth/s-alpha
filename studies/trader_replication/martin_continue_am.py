"""Continuation AM: apply AB's historical gap group only to U1 list entries."""
import hashlib
import json
from pathlib import Path

import numpy as np

from . import compare, panels
from .martin_continue_a import required_fields
from .martin_continue_ac import filter_book
from .martin_strong import Data
from .martin_strong_scan import HOLD, account, active, f1_rules, forward_close, hold_sim, merge, name_score, u1_entries


def main():
    D = Data()
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    original = u1_entries(D, F, H, score)
    core = [[e for e in row if e[5] != 'list'] for row in original]
    satellite = [[e for e in row if e[5] == 'list'] for row in original]
    filtered, counts = filter_book(D, satellite)
    entries = merge(core, filtered)
    del F, M, score, H, original, core, satellite, filtered
    forward_close(D)
    rules = f1_rules(D, 6, (1, 3))
    fidelity = account(D, entries, rules, 'AM1')
    st, trades = D.base.run(D.A, entries, panels.WINDOW, D.pool, rules, placebo=0, audit=True)
    i0 = int(np.searchsorted(D.A['days'], panels.WINDOW[0]))
    i1 = int(np.searchsorted(D.A['days'], panels.WINDOW[1], side='right'))
    metrics = compare.metrics(st['_curve'], D.A['days'][i0:i1], trades, entries, i0, i1)
    metrics['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in trades) for y in ('2024', '2025', '2026')}
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_ab.py',
             'studies/trader_replication/martin_continue_ac.py', 'studies/trader_replication/martin_continue_am.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), candidate_counts=counts,
               metrics=metrics, fidelity=fidelity,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_am.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
