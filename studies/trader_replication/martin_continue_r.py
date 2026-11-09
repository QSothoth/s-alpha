"""Continuation R: B2 opportunity funnel in the preregistered post-entry diagnostic window."""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import numpy as np

from . import panels
from .martin_continue_a import required_fields
from .martin_continue_b import support_book
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, hold_sim, merge, name_score, nl_rules, pool_book2, pool_book3


def main():
    D = Data()
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    d1 = pool_book3(D, F, H, score, 8.0, False, .03)
    broad = pool_book2(D, F, H, score, True, 8.0, None, False)
    limits, _ = support_book(D, broad, d1)
    book = merge(d1, limits)
    del F, M, score
    ru = nl_rules(D, 6, trail='e9')
    ru = replace(ru, intraday_kinds=tuple(ru.intraday_kinds) + ('lim',))
    _, trades = D.base.run(D.A, book, panels.WINDOW, D.pool, ru, placebo=0, audit=True)
    root = Path(__file__).resolve().parents[2]
    prior_path = root / 'studies/trader_replication/reports/gap_review/strong_continue_q.json'
    prior = json.loads(prior_path.read_text(encoding='utf-8'))
    if prior['dataset_digest'] != D.A['digest']:
        raise ValueError('Q has a different dataset digest')
    codes = {str(c): j for j,c in enumerate(D.A['codes'])}
    raw = []
    for p in prior['rows']:
        d, peak, code = D.di[p['day']], D.di[p['peak_day']], 'US.' + p['ticker']
        j = codes[code]
        end = min(d + 10, peak - 1)
        days = range(d, end + 1)
        h3 = any(H[s, j] and np.isfinite(D.c[s,j]) and D.c[s,j] > 0 for s in days)
        if h3 != (p['h3'] is not None):
            raise ValueError('H3 coverage differs from the saved Q observation')
        setup = any(any(e[1] == j for e in broad[s]) for s in days)
        narrow = any(any(e[1] == j for e in d1[s]) for s in days)
        touch = any(any(e[1] == j for e in limits[s]) for s in days)
        same = [t for t in trades if t['code'] == code]
        entered = any(p['day'] <= t['entry'] <= D.days[end] for t in same)
        held = any(t['entry'] <= D.days[end] and t['exit'] >= p['day'] for t in same)
        gap = ('held' if held else 'no_shape' if not setup else 'no_narrow' if not narrow else 'narrow_no_holding') if h3 else 'no_h3'
        raw.append(dict(day=p['day'], ticker=p['ticker'], peak_day=p['peak_day'], h3=h3,
                        setup=setup, narrow=narrow, limit_touch=touch, entry=entered, held_overlap=held, first_gap=gap))
    years = {}
    for year in ('2024','2025','2026','all'):
        rows = raw if year == 'all' else [r for r in raw if r['day'].startswith(year)]
        eligible = [r for r in rows if r['h3']]
        years[year] = dict(n=len(rows), counts={k: sum(r[k] for r in rows) for k in ('h3','setup','narrow','limit_touch','entry','held_overlap')},
                           first_gap_among_h3=dict(Counter(r['first_gap'] for r in eligible)))
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_b.py',
             'studies/trader_replication/martin_continue_r.py', 'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), years=years, rows=raw,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths},
               prior_report_sha256=hashlib.sha256(prior_path.read_bytes()).hexdigest())
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_r.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in out.items() if k != 'rows'}, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
