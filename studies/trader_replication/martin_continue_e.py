"""Continuation E: conservative limit activation and ex-post top-two replay."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import numpy as np

from . import compare, panels, success
from .martin_continue_a import required_fields
from .martin_continue_b import support_book
from .martin_strong import Data
from .martin_strong_scan import HOLD, account, active, forward_close, hold_sim, merge, name_score, nl_rules, pool_book2, pool_book3


def main():
    D = Data()
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    d1 = pool_book3(D, F, H, score, 8.0, False, .03)
    broad = pool_book2(D, F, H, score, True, 8.0, None, False)
    limits, _ = support_book(D, broad, d1)
    conservative = [[e for e in row if D.o[d, e[1]] > e[4] * 1.025] for d, row in enumerate(limits)]
    base, after_open = merge(d1, limits), merge(d1, conservative)
    del F, M, score, H, broad, d1, limits, conservative
    forward_close(D)
    ru = nl_rules(D, 6, trail='e9')
    ru = replace(ru, intraday_kinds=tuple(ru.intraday_kinds) + ('lim',))
    st, trades = D.base.run(D.A, base, panels.WINDOW, D.pool, ru, placebo=0, audit=True)
    top = sorted((t for t in trades if t['why'] != 'end'), key=lambda t: -t['ret'])[:2]
    dropped = success.drop_top(D.A, base, trades, k=2)
    res = {}
    for name, book in (('B2', base), ('AFTER_OPEN', after_open), ('DROP_TOP2', dropped)):
        fidelity = account(D, book, ru, name)
        s, tr = D.base.run(D.A, book, panels.WINDOW, D.pool, ru, placebo=0, audit=True)
        i0 = int(np.searchsorted(D.A['days'], panels.WINDOW[0]))
        i1 = int(np.searchsorted(D.A['days'], panels.WINDOW[1], side='right'))
        metrics = compare.metrics(s['_curve'], D.A['days'][i0:i1], tr, book, i0, i1)
        metrics['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in tr) for y in ('2024', '2025', '2026')}
        metrics['limit_entries_by_year'] = {y: sum(t['entry'].startswith(y) and t['kind'] == 'lim' for t in tr) for y in ('2024', '2025', '2026')}
        res[name] = dict(metrics=metrics, fidelity=fidelity)
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_b.py',
             'studies/trader_replication/martin_continue_e.py', 'studies/trader_replication/success.py', 'studies/trader_replication/system.py')
    result = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW),
                  removed=[{k: t[k] for k in ('code', 'entry', 'exit', 'kind', 'ret', 'pnl')} for t in top],
                  code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}, results=res)
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_e.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
