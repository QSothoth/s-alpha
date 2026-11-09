"""Continuation AE: U1's full-versus-truncated input audit."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

from . import gate, panels, systems
from .martin_continue_a import required_fields
from .martin_continue_b_check import digest
from .martin_continue_bb import data_with_system
from .martin_strong import Data
from .martin_strong_scan import HOLD, account, active, f1_rules, forward_close, hold_sim, name_score, u1_entries


def main(cut=None):
    selected = systems.get('martin_luk')
    wrapper, _ = selected.load()
    base = getattr(wrapper, 'base', wrapper)
    if cut:
        arrays = base.arrays
        base.arrays = lambda market: arrays(market, upto=cut)
    D = data_with_system(selected)
    if D.base is not base or (cut and D.days[-1] != cut):
        raise AssertionError('actual Data instance has the wrong panel or cutoff')
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    entries = u1_entries(D, F, H, score)
    del F, M, H, score
    rules = f1_rules(D, 6, (1, 3))
    ema = D.base.ema_inputs(D.A, D.pool, rules)
    snapshots = {}
    for day in ((cut,) if cut else gate.CUTS):
        k = int(np.searchsorted(D.A['days'], day, side='right'))
        row = {'entries': digest([gate._norm(x) for x in entries[:k]]),
               'pool': hashlib.sha256(np.ascontiguousarray(D.pool[:k]).tobytes()).hexdigest(),
               'rules': digest(gate._norm(asdict(rules)))}
        for name, val in ema.items():
            row['ema:' + name] = hashlib.sha256(np.ascontiguousarray(val[:k]).tobytes()).hexdigest()
        snapshots[day] = row
    result = {'data_digest': D.A['digest'], 'cut': cut, 'input_last': D.days[-1], 'snapshots': snapshots}
    if not cut:
        forward_close(D)
        result['fidelity'] = account(D, entries, rules, 'AE U1')
        _, trades = D.base.run(D.A, entries, panels.WINDOW, D.pool, rules, placebo=0, audit=True)
        result['fills'] = gate.check_fills(D.A, trades)
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_ae.py',
             'studies/trader_replication/martin_strong.py', 'studies/trader_replication/martin_strong_scan.py',
             'studies/trader_replication/system.py')
    result['code_sha256'] = {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}
    target = root / 'studies/trader_replication/reports/gap_review' / f"strong_continue_ae_fixed_{cut or 'full'}.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else None)
