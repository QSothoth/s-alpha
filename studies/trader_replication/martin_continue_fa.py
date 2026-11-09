"""FA: audit DG1 using complete or genuinely raw-row-truncated frozen data."""
from dataclasses import replace
import json
from pathlib import Path
import sys

from studies import trader_data
from studies.trader_replication import martin_continue_dg as dg
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ea as ea
from studies.trader_replication import martin_continue_eh as eh
from studies.trader_replication import panels, system
from studies.trader_replication.martin_continue_b_check import digest
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import longs, nl_rules

CUTS = ('2025-09-30', '2026-06-30')


def main(mode):
    if mode != 'full' and mode not in CUTS:
        raise ValueError('expected full or a registered cutoff')
    root = du.REPORTS
    reference = root / 'strong_continue_ez.json'
    ref = json.loads(reference.read_text())
    system_path = 'studies/trader_replication/system.py'
    if ref['code_sha256'][system_path] != sha(Path(system.__file__)):
        raise ValueError('system differs from EZ')
    dataset = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if dataset.digest() != ref['dataset_digest']:
        raise ValueError('dataset differs from EZ')
    if mode != 'full':
        dataset = ea.LimitedDataset(dataset, mode)
    d = du.make_data(dataset)
    if (mode == 'full' and d.days[-1] <= CUTS[-1]) or (mode != 'full' and d.days[-1] != mode):
        raise AssertionError('wrong dataset ending')
    reg = [[((1.0,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:6])
            for e in row] for row in longs(d.reg)]
    book, counts = dg.next_open(reg, d.A['open'], d.A['low'], d.days)
    kinds = sorted({e[5] for row in book for e in row})
    base_rules = nl_rules(d, 6)
    base_rules = replace(base_rules, intraday_kinds=tuple(sorted(set(base_rules.intraday_kinds) | set(kinds))))
    rules = replace(base_rules, gross_cost=True)
    if mode == 'full':
        if counts != ref['candidates']:
            raise AssertionError('EZ candidates differ')
        px, em = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules)
        for name, ru in (('DG1', base_rules), ('DG1_cash', rules)):
            _, _, trades = system.simulate(px, em, ru, book, *panels.WINDOW, audit=True)
            if digest(trades) != ref['results'][name]['trades_digest']:
                raise AssertionError('EZ trades differ ' + name)
    snapshots = {}
    for cut in CUTS if mode == 'full' else (mode,):
        print('snapshot', mode, cut, flush=True)
        snapshots[cut] = eh.snapshot(d, 'DG1', book, rules, cut, {})
    out = {'mode': mode, 'dataset_digest': ref['dataset_digest'], 'actual_last': d.days[-1],
           'script_sha256': sha(Path(__file__)), 'system_sha256': sha(Path(system.__file__)),
           'ez_sha256': sha(reference), 'snapshots': snapshots}
    target = root / f'strong_continue_fa_{mode}.json'
    with target.open('w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        f.write('\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main(sys.argv[1])
