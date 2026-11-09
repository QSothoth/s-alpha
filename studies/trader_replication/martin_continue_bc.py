"""Continuation BC: compare full and post-adjustment panel slices for B2 and F1."""
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

from . import gate, system, systems
from .martin_continue_a import required_fields
from .martin_continue_b import support_book
from .martin_continue_b_check import digest
from .martin_continue_bb import data_with_system
from .martin_strong import Data
from .martin_strong_scan import (HOLD, active, f1_rules, hold_sim, merge, name_score,
                                 nl_rules, pool_book2, pool_book3, sized, tilt_core)


def main(cut=None):
    selected = systems.get('martin_luk')
    wrapper, _ = selected.load()
    base = getattr(wrapper, 'base', wrapper)
    if cut:
        arrays = base.arrays
        base.arrays = lambda market: arrays(market, upto=cut)
    D = data_with_system(selected)
    if D.base is not base or (D.days[-1] != cut if cut else D.days[-1] <= max(gate.CUTS)):
        raise AssertionError('actual Data instance has the wrong panel or cutoff')
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    d1 = pool_book3(D, F, H, score, 8.0, False, .03)
    broad = pool_book2(D, F, H, score, True, 8.0, None, False)
    limits, _ = support_book(D, broad, d1)
    b2 = merge(d1, limits)
    f1 = merge(tilt_core(D, H, .5), sized(pool_book2(D, F, H, score), .5))
    pending = [[] for _ in D.days]
    for d in range(1, len(D.days) - 1):
        accepted = {e[1] for e in d1[d]}
        eligible = sorted((e for e in broad[d] if e[1] not in accepted and np.isfinite(D.l[d, e[1]])
                           and D.l[d, e[1]] > 0), key=lambda e: e[0])
        if eligible:
            e = eligible[0]
            pending[d + 1] = [int(e[1]), float(D.l[d, e[1]])]
    del F, M, score, H, broad, d1, limits
    b2_rules = nl_rules(D, 6, trail='e9')
    b2_rules = replace(b2_rules, intraday_kinds=tuple(b2_rules.intraday_kinds) + ('lim',))
    snapshots = {}
    for name, entries, rules in (('B2', b2, b2_rules), ('F1', f1, f1_rules(D))):
        ema = D.base.ema_inputs(D.A, D.pool, rules)
        px = D.base.px(D.A)
        snapshots[name] = {}
        for day in ((cut,) if cut else gate.CUTS):
            k = int(np.searchsorted(D.A['days'], day, side='right'))
            row = {'entries': digest([gate._norm(x) for x in entries[:k]]),
                   'pool': hashlib.sha256(np.ascontiguousarray(D.pool[:k]).tobytes()).hexdigest(),
                   'rules': digest(gate._norm(asdict(rules)))}
            if name == 'B2':
                row['pending'] = digest(pending[:k])
            for key, val in ema.items():
                row['ema:' + key] = hashlib.sha256(np.ascontiguousarray(val[:k]).tobytes()).hexdigest()
            curve, dates, trades = system.simulate(px, ema, rules, entries, '2024-01-02', day)
            row['trade_keys'] = digest([[t['code'], t['side'], t['kind'], t['entry'], t['exit'], t['why']] for t in trades])
            row['curve'] = hashlib.sha256(np.ascontiguousarray(curve).tobytes()).hexdigest()
            row['end_equity'] = float(curve[-1])
            row['trades'] = len(trades)
            snapshots[name][day] = row
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_b.py',
             'studies/trader_replication/martin_continue_bb.py', 'studies/trader_replication/martin_continue_bc.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], input_last=D.days[-1], cut=cut, snapshots=snapshots,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review' / f"strong_continue_bc_{cut or 'full'}.json"
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(cut or 'full', D.days[-1], snapshots, flush=True)


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else None)
