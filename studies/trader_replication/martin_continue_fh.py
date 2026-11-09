"""FH: compare FC1 under complete and raw-row-truncated inputs."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys

from studies import trader_data
from studies.trader_replication import martin_continue_dg as dg
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ea as ea
from studies.trader_replication import martin_continue_eh as eh
from studies.trader_replication import martin_continue_fc as fc
from studies.trader_replication import martin_continue_fe as fe
from studies.trader_replication import panels, system
from studies.trader_replication.martin_continue_b_check import digest
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import longs, nl_rules

CUTS = ('2025-09-30', '2026-06-30')


def snapshot(d, book, rules, cutoff, unknown):
    px, em = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules)
    curve, dates, trades = system.simulate(px, em, rules, book, '2024-01-02', cutoff, audit=True)
    return {'signals': eh.normalized(book, d, cutoff), 'pending': {},
            'trade_keys': [[t['code'], int(t['side']), t['kind'], t['entry'], t['exit'], t['why']] for t in trades],
            'trail_pending': sorted([[t['code'], t['trail_signal']] for t in trades
                                     if t['why'] == 'end' and t['state'].get('trail_pending')]),
            'precision_unknown': [x for x in unknown if panels.WINDOW[0] <= x[0] <= cutoff],
            'curve': curve.tolist(), 'dates': [str(x) for x in dates],
            'curve_sha256': hashlib.sha256(curve.tobytes()).hexdigest()}


def main(mode):
    if mode != 'full' and mode not in CUTS:
        raise ValueError('expected full or a registered cutoff')
    root = du.REPORTS
    reference = root / 'strong_continue_fc.json'
    ref = json.loads(reference.read_text())
    if ref['script_sha256'] != sha(Path(fc.__file__)) or ref['system_sha256'] != sha(Path(system.__file__)):
        raise ValueError('FC source differs')
    dataset = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if dataset.digest() != ref['dataset_digest']:
        raise ValueError('dataset differs')
    if mode != 'full':
        dataset = ea.LimitedDataset(dataset, mode)
    d = du.make_data(dataset)
    if (mode == 'full' and d.days[-1] <= CUTS[-1]) or (mode != 'full' and d.days[-1] != mode):
        raise AssertionError('wrong dataset ending')
    reg = [[((1.0,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:6])
            for e in row] for row in longs(d.reg)]
    book, counts = dg.next_open(reg, d.A['open'], d.A['low'], d.days)
    if mode == 'full' and counts != ref['candidates']:
        raise AssertionError('FC candidates differ')
    _, unknown = fe.remove_precision_unknown(book, d.days, d.A['codes'])
    kinds = sorted({e[5] for row in book for e in row})
    rules = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True)
    rules = replace(rules, intraday_kinds=tuple(sorted(set(rules.intraday_kinds) | set(kinds))))
    if mode == 'full':
        px, em = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules)
        _, _, trades = system.simulate(px, em, rules, book, *panels.WINDOW, audit=True)
        if digest(trades) != ref['results']['FC1']['trades_digest']:
            raise AssertionError('FC trades differ')
    snapshots = {}
    for cut in CUTS if mode == 'full' else (mode,):
        print('snapshot', mode, cut, flush=True)
        snapshots[cut] = snapshot(d, book, rules, cut, unknown)
    out = {'mode': mode, 'dataset_digest': ref['dataset_digest'], 'actual_last': d.days[-1],
           'fc_sha256': sha(reference), 'system_sha256': sha(Path(system.__file__)),
           'script_sha256': sha(Path(__file__)), 'snapshots': snapshots}
    target = root / f'strong_continue_fh_{mode}.json'
    with target.open('w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        f.write('\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main(sys.argv[1])
