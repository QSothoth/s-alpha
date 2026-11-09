"""GN: compare cash-account exits using previously registered daily signals."""
from dataclasses import replace
import gc
import json
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trader_replication import panels, system
from studies.trader_replication import martin_continue_dg as dg
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_fc as fc
from studies.trader_replication import martin_continue_fe as fe
from studies.trader_replication import martin_continue_fo as fo
from studies.trader_replication import martin_continue_ft as ft
from studies.trader_replication import martin_continue_fx as fx
from studies.trader_replication import martin_continue_gi as gi
from studies.trader_replication.martin_continue_b_check import digest
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import longs, nl_rules


def candidates(base):
    return (('C0', base), ('GN9', replace(base, trail='e9')),
            ('GNT', replace(base, trims=(3, 5), trim_frac=.15)),
            ('GNB', replace(base, trail='e9', trims=(3, 5), trim_frac=.15)))


def main():
    root = du.REPORTS
    path = root / 'strong_continue_gi.json'
    ref = json.loads(path.read_text())
    if ref['script_sha256'] != sha(Path(gi.__file__)) or ref['system_sha256'] != sha(Path(system.__file__)):
        raise ValueError('GI source differs')
    dataset = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if dataset.digest() != ref['dataset_digest']:
        raise ValueError('frozen dataset differs')
    ref = {key: ref[key] for key in ('dataset_digest', 'old_core_counts', 'old_core_precision_unknown', 'results')}
    ref['results'] = {'C0': ref['results']['C0']}
    gc.collect()
    d = du.make_data(dataset)
    reg = [[((1.0,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:6])
            for e in row] for row in longs(d.reg)]
    book, counts = dg.next_open(reg, d.A['open'], d.A['low'], d.days)
    book, unknown = fe.remove_precision_unknown(book, d.days, d.A['codes'])
    unknown = [x for x in unknown if panels.WINDOW[0] <= x[0] <= panels.WINDOW[1]]
    if counts != ref['old_core_counts'] or unknown != ref['old_core_precision_unknown']:
        raise AssertionError('original core candidates differ')
    rules = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True, no_rebuy_day=True)
    rules = replace(rules, intraday_kinds=tuple(sorted(set(rules.intraday_kinds) | {'n1'})))
    del d.fp, d.fwd, d.raw
    for key in ('pr21', 'pr63', 'pr126', 'rank_pool', 'stack', 'tight'):
        d.A.pop(key, None)
    d.rk = d.rk.astype(np.int32)
    gc.collect()
    results, audits, traces, cash = {}, {}, {}, {}
    for name, ru in candidates(rules):
        print('account', name, flush=True)
        result = fo.account(d, book, ru)
        if name == 'C0' and result != ref['results']['C0']:
            raise AssertionError('C0 full account differs')
        px, em = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, ru)
        _, _, trades = system.simulate(px, em, ru, book, *panels.WINDOW, audit=True)
        if digest(trades) != result['trades_digest']:
            raise AssertionError('audited trades differ')
        gi.assert_no_same_day_rebuy(trades)
        results[name] = result
        audits[name] = fc.signal_audit(d, trades)
        traces[name] = ft.trace_orders(d, book, ru, result['trades_digest'])
        if any(x['max_positions_after_open'] > 6 for x in traces[name]['years'].values()):
            raise AssertionError('cash position limit exceeded')
        cash[name] = fx.audit_open_cash(d, book, ru, result)
        if cash[name]['negative_cash']:
            raise AssertionError('opening resulted in negative cash')
    out = {'dataset_digest': ref['dataset_digest'], 'gi_sha256': sha(path),
           'system_sha256': sha(Path(system.__file__)), 'script_sha256': sha(Path(__file__)),
           'candidates': counts, 'precision_unknown': unknown,
           'results': results, 'trail_audits': audits, 'traces': traces, 'cash_audits': cash}
    target = root / 'strong_continue_gn.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False,
                                 default=json_default) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
