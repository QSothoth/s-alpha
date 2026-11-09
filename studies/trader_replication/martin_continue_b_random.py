"""Continuation B: random prior-close name within the same missed-signal pool."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import numpy as np

from . import panels, system
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
    original, _ = support_book(D, broad, d1)
    del F, M, score, H
    ru = nl_rules(D, 6, trail='e9')
    ru = replace(ru, intraday_kinds=tuple(ru.intraday_kinds) + ('lim',))
    px, ema = D.base.px(D.A), D.base.ema_inputs(D.A, D.pool, ru)

    def simulate(book):
        curve, dates, _ = system.simulate(px, ema, ru, book, *panels.WINDOW)
        out = {'total': float(curve[-1] - 1)}
        for year in ('2024', '2025', '2026'):
            ix = np.flatnonzero(np.char.startswith(dates.astype(str), year))
            out[year] = float(curve[ix[-1]] / (curve[ix[0] - 1] if ix[0] else 1) - 1)
        return out

    real = simulate(merge(d1, original))
    rng = np.random.default_rng(1)
    runs = []
    for draw in range(100):
        random_broad = [[((float(rng.random()),),) + e[1:] for e in row] for row in broad]
        limits, _ = support_book(D, random_broad, d1)
        runs.append(simulate(merge(d1, limits)))
        if (draw + 1) % 10 == 0:
            print(f'draw {draw + 1}/100', flush=True)
    summary = {}
    for key in real:
        a = np.array([r[key] for r in runs])
        summary[key] = dict(real=real[key], median=float(np.median(a)), p10=float(np.percentile(a, 10)),
                            p90=float(np.percentile(a, 90)), rank=float(np.mean(a < real[key])))
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_b.py',
             'studies/trader_replication/martin_continue_b_random.py', 'studies/trader_replication/system.py')
    result = dict(dataset_digest=D.A['digest'], seed=1, draws=100,
                  code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths},
                  summary=summary, runs=runs)
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_b_random.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
