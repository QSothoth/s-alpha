"""EI: compare the saved EH full and as-of cutoff decisions and account curves."""
from collections import Counter
import json
import math
from pathlib import Path

from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_eh as eh
from studies.trader_replication.martin_continue_dq import sha


def near(a, b):
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(a, b, rel_tol=1e-5, abs_tol=0.)


def compare(full, cut):
    if set(full['signals']) != set(cut['signals']) or full['dates'] != cut['dates']:
        raise ValueError('dates differ')
    out = {'identity_days': [], 'price_days': [], 'pending_days': [], 'trade_identity_equal': full['trade_keys'] == cut['trade_keys']}
    for day in sorted(full['signals']):
        a, b = full['signals'][day], cut['signals'][day]
        identities = lambda rows: [(r['code'], r['side'], r['kind'], r['extra']) for r in rows]
        if identities(a) != identities(b):
            out['identity_days'].append(day)
            continue
        if any(not near(x[k], y[k]) for x, y in zip(a, b) for k in ('fill_over_close', 'stop_over_fill', 'dayexit_over_fill')):
            out['price_days'].append(day)
    for day in sorted(full['pending'].keys() | cut['pending'].keys()):
        a, b = full['pending'].get(day), cut['pending'].get(day)
        if a is None or b is None or a[0] != b[0] or not near(a[1], b[1]):
            out['pending_days'].append(day)
    a, b = Counter(map(tuple, full['trade_keys'])), Counter(map(tuple, cut['trade_keys']))
    out['trades_only_full'] = [list(k) for k, n in (a - b).items() for _ in range(n)]
    out['trades_only_cut'] = [list(k) for k, n in (b - a).items() for _ in range(n)]
    out['max_curve_abs_difference'] = max((abs(x - y) for x, y in zip(full['curve'], cut['curve'])), default=0.)
    out['end_equity_full'] = full['curve'][-1] if full['curve'] else None
    out['end_equity_cut'] = cut['curve'][-1] if cut['curve'] else None
    return out


def main():
    full_path = du.REPORTS / 'strong_continue_eh_full.json'
    full = json.loads(full_path.read_text())
    if full['script_sha256'] != sha(Path(eh.__file__)):
        raise ValueError('EH source differs')
    out = {'eh_full_sha256': sha(full_path), 'script_sha256': sha(Path(__file__)), 'cutoffs': {}}
    for cutoff in eh.CUTS:
        cut_path = du.REPORTS / f'strong_continue_eh_{cutoff}.json'
        cut = json.loads(cut_path.read_text())
        if (cut['dataset_digest'] != full['dataset_digest'] or cut['script_sha256'] != full['script_sha256']
                or cut['actual_last'] != cutoff):
            raise ValueError('EH cutoff input differs')
        values = {}
        for variant in ('original', 'asof_fast'):
            values[variant] = {name: compare(full['snapshots'][variant][name][cutoff],
                                              cut['snapshots'][variant][name][cutoff])
                               for name in ('B2', 'F1', 'U1')}
        out['cutoffs'][cutoff] = {'cut_sha256': sha(cut_path), 'systems': values}
    target = du.REPORTS / 'strong_continue_ei.json'
    with target.open('w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
