"""Continuation AQ: prior-close portfolio state for AO's trade groups."""
import hashlib
import json
from pathlib import Path

import numpy as np

from . import panels, system
from .martin_continue_a import required_fields
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, name_score, u1_entries


def main():
    D = Data()
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    original = u1_entries(D, F, H, score)
    satellite = [[e for e in row if e[5] == 'list'] for row in original]
    del F, M, score, H
    rules = f1_rules(D, 6, (1, 3))
    px, ema = D.base.px(D.A), D.base.ema_inputs(D.A, D.pool, rules)
    keyed, histories = {}, {}
    for name, book in (('U1', original), ('SAT', satellite)):
        track = {}
        _, dates, tr = system.simulate(px, ema, rules, book, *panels.WINDOW, track=track)
        selected = [t for t in tr if t['kind'] == 'list']
        keyed[name] = {(t['entry'], t['code'], t['kind']) for t in selected}
        if len(keyed[name]) != len(selected):
            raise ValueError(f'duplicate signal in {name}')
        histories[name] = (dates, track)
    u, s = keyed['U1'], keyed['SAT']
    result = {}
    for year in ('2025', '2026'):
        result[year] = {}
        for group, members in (('common', u & s), ('u1_only', u - s), ('sat_only', s - u)):
            keys = sorted(k for k in members if k[0].startswith(year))
            result[year][group] = {'trades': len(keys)}
            for name, (dates, track) in histories.items():
                indexes = [int(np.searchsorted(dates, k[0])) - 1 for k in keys]
                indexes = [i for i in indexes if i >= 0]
                gross = [track['gross'][i] for i in indexes]
                opened = [track['open'][i] for i in indexes]
                result[year][group][name] = {'n': len(indexes), 'missing': len(keys) - len(indexes),
                    'median_gross': float(np.median(gross)) if gross else None,
                    'median_open': float(np.median(opened)) if opened else None,
                    'at_95pct_cap': float(np.mean(np.asarray(gross) >= .95 * rules.max_gross)) if gross else None}
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_aq.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), gross_cap=rules.max_gross,
               by_entry_year=result, code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_aq.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
