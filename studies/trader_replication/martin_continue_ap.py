"""Continuation AP: decompose U1 and SAT's common and unique list trades."""
import hashlib
import json
from pathlib import Path

from . import panels, system
from .martin_continue_a import required_fields
from .martin_continue_ao import summarize
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, f1_rules, hold_sim, name_score, u1_entries


def group(rows):
    closed = [t for t in rows if t['why'] != 'end']
    weighted = [t for t in closed if t['ret'] != 0]
    capital = sum(t['pnl'] / t['ret'] for t in weighted)
    out = summarize(rows)
    out.update(zero_return=len(closed) - len(weighted),
               weighted_ret=sum(t['pnl'] for t in weighted) / capital if capital else None,
               initial_capital_sum=float(capital))
    return out


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
    keyed = {}
    for name, book in (('U1', original), ('SAT', satellite)):
        _, _, tr = system.simulate(px, ema, rules, book, *panels.WINDOW)
        selected = [t for t in tr if t['kind'] == 'list']
        keyed[name] = {(t['entry'], t['code'], t['kind']): t for t in selected}
        if len(keyed[name]) != len(selected):
            raise ValueError(f'duplicate signal in {name}')
    u, s = set(keyed['U1']), set(keyed['SAT'])
    result = {}
    for year in ('2024', '2025', '2026'):
        keys = lambda x: sorted(k for k in x if k[0].startswith(year))
        result[year] = {name: group([keyed[book][k] for k in keys(items)])
                        for name, book, items in (('u1_common', 'U1', u & s), ('sat_common', 'SAT', u & s),
                                                  ('u1_only', 'U1', u - s), ('sat_only', 'SAT', s - u))}
    root = Path(__file__).resolve().parents[2]
    paths = ('studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_ao.py',
             'studies/trader_replication/martin_continue_ap.py', 'studies/trader_replication/martin_strong_scan.py',
             'studies/trader_replication/system.py')
    out = dict(dataset_digest=D.A['digest'], window=list(panels.WINDOW), by_entry_year=result,
               code_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_ap.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
