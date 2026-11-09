"""Continuation AJ: cap U1's close signals before the account can backfill."""
import hashlib
import json
from pathlib import Path

import numpy as np

from . import compare, panels
from .martin_continue_a import required_fields
from .martin_strong import Data
from .martin_strong_scan import HOLD, account, active, f1_rules, forward_close, hold_sim, name_score, u1_entries


def fixed_six(book):
    return [[e for e in row if e[5] != 'list'] + sorted((e for e in row if e[5] == 'list'), key=lambda e: e[0])[:6]
            for row in book]


def main():
    D = Data()
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    entries = fixed_six(u1_entries(D, F, H, score))
    del F, M, score, H
    forward_close(D)
    rules = f1_rules(D, 6, (1, 3))
    fidelity = account(D, entries, rules, 'AJ1')
    st, trades = D.base.run(D.A, entries, panels.WINDOW, D.pool, rules, placebo=0, audit=True)
    i0 = int(np.searchsorted(D.A['days'], panels.WINDOW[0]))
    i1 = int(np.searchsorted(D.A['days'], panels.WINDOW[1], side='right'))
    metrics = compare.metrics(st['_curve'], D.A['days'][i0:i1], trades, entries, i0, i1)
    metrics['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in trades) for y in ('2024', '2025', '2026')}
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_aj.py',
             'studies/trader_replication/martin_strong.py', 'studies/trader_replication/martin_strong_scan.py',
             'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), metrics=metrics, fidelity=fidelity,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_aj.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
