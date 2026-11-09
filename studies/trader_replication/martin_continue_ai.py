"""Continuation AI: remove one H3 factor group at a time in the U1 account."""
import hashlib
import json
from pathlib import Path

import numpy as np

from . import compare, panels
from .martin_continue_a import required_fields
from .martin_strong import Data
from .martin_strong_scan import HOLD, account, active, f1_rules, forward_close, hold_sim, name_score, u1_entries


def main():
    D = Data()
    F = required_fields(D)
    M = active(D, F)
    full = name_score(D, F, M, HOLD['H3'])
    forward_close(D)
    rules = f1_rules(D, 6, (1, 3))
    i0 = int(np.searchsorted(D.A['days'], panels.WINDOW[0]))
    i1 = int(np.searchsorted(D.A['days'], panels.WINDOW[1], side='right'))
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_ai.py',
             'studies/trader_replication/martin_strong.py', 'studies/trader_replication/martin_strong_scan.py',
             'studies/trader_replication/system.py')
    out = {'dataset_digest': D.A['digest'], 'window': list(panels.WINDOW), 'results': {},
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}}
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_ai.json'
    groups = HOLD['H3']
    for name, index in (('U1', None), ('no_activity', 0), ('no_strength', 1), ('no_fast', 2), ('no_structure', 3), ('no_peer', 4)):
        S = full if index is None else name_score(D, F, M, groups[:index] + groups[index + 1:])
        H = hold_sim(S, 12, 36)
        entries = u1_entries(D, F, H, S)
        fidelity = account(D, entries, rules, name)
        st, trades = D.base.run(D.A, entries, panels.WINDOW, D.pool, rules, placebo=0, audit=True)
        metrics = compare.metrics(st['_curve'], D.A['days'][i0:i1], trades, entries, i0, i1)
        metrics['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in trades) for y in ('2024', '2025', '2026')}
        out['results'][name] = {'metrics': metrics, 'fidelity': fidelity}
        target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(name, metrics['by_year'], flush=True)
        del H, entries, st, trades, metrics, fidelity
        if index is not None:
            del S


if __name__ == '__main__':
    main()
