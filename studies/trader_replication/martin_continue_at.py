"""Continuation AT: SAT outcomes for the opportunities U1 did not reopen."""
import hashlib
import json
from pathlib import Path

from . import panels, system
from .martin_continue_a import required_fields
from .martin_continue_ap import group
from .martin_continue_b_check import digest
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, name_score, u1_entries


def main():
    root = Path(__file__).resolve().parents[2]
    prior = json.loads((root / 'studies/trader_replication/reports/gap_review/strong_continue_ar.json').read_text())
    D = Data()
    if D.A['digest'] != prior['dataset_digest']:
        raise ValueError('frozen dataset differs from AR')
    F = required_fields(D)
    M = active(D, F)
    score = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(score, 12, 36)
    original = u1_entries(D, F, H, score)
    satellite = [[e for e in row if e[5] == 'list'] for row in original]
    del F, M, score, H, original
    rules = f1_rules(D, 6, (1, 3))
    px, ema = D.base.px(D.A), D.base.ema_inputs(D.A, D.pool, rules)
    _, _, trades = system.simulate(px, ema, rules, satellite, *panels.WINDOW)
    if digest(trades) != prior['results']['SAT']['trades_digest']:
        raise AssertionError('SAT path differs from AR')
    selected = [t for t in trades if t['kind'] == 'list']
    keyed = {(t['entry'], t['code']): t for t in selected}
    if len(keyed) != len(selected):
        raise ValueError('duplicate SAT signal')
    categories = {'open_pos: val <= 0.001 * equity': 'gross_room',
                  'open_pos: j in pos or not np.isfinite(fill) or fill <= 0': 'held',
                  'take: own and new_by_kind.get(kind, 0) >= rules.max_new_by_kind[kind]': 'daily_cap'}
    result = {}
    records = prior['results']['U1']['records']
    for year in ('2025', '2026'):
        result[year] = {}
        for raw_reason, name in categories.items():
            keys = [(r['date'], r['code']) for r in records if r['date'].startswith(year) and r['reason'] == raw_reason]
            rows = [keyed[k] for k in keys]
            stats = group(rows)
            stats['ret_at_least_30pct'] = int(sum(t['ret'] >= .3 for t in rows if t['why'] != 'end'))
            result[year][name] = stats
        unmatched = [r for r in records if r['date'].startswith(year) and r['reason'] not in categories]
        if unmatched:
            raise ValueError(f'unclassified target in {year}')
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_ap.py',
             'studies/trader_replication/martin_continue_at.py', 'studies/trader_replication/martin_strong_scan.py',
             'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), by_entry_year=result,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_at.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
