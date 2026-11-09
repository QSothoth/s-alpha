"""FW: test the fixed doubled core stop in the existing cash account."""
from dataclasses import replace
import gc
import json
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trader_replication import panels, system
from studies.trader_replication import martin_continue_dg as dg
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_fo as fo
from studies.trader_replication import martin_continue_fv as fv
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import longs, nl_rules


def main():
    root = du.REPORTS
    ref_path = root / 'strong_continue_fc.json'
    ref = json.loads(ref_path.read_text())
    dataset = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if dataset.digest() != ref['dataset_digest']:
        raise ValueError('dataset differs')
    d = du.make_data(dataset)
    reg = [[((1.0,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:6])
            for e in row] for row in longs(d.reg)]
    book, counts = dg.next_open(reg, d.A['open'], d.A['low'], d.days)
    if counts != ref['candidates']:
        raise AssertionError('FC candidate counts differ')
    kinds = {e[5] for row in book for e in row}
    rules = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True)
    rules = replace(rules, intraday_kinds=tuple(sorted(set(rules.intraday_kinds) | kinds)))
    del d.fp, d.fwd, d.raw
    for key in ('pr21', 'pr63', 'pr126', 'rank_pool', 'stack', 'tight'):
        d.A.pop(key, None)
    d.rk = d.rk.astype(np.int32)
    gc.collect()
    hit_book, hit_counts = fv.wide_book(book, d, True)
    nohit_book, nohit_counts = fv.wide_book(book, d, False)
    results, traces = {}, {}
    for name, active in (('FC1', book), ('FW_hit', hit_book), ('FW_nohit', nohit_book)):
        print('account', name, flush=True)
        result = fo.account(d, active, rules)
        results[name] = result
        if name == 'FC1':
            expected = ref['results']['FC1']
            if result['trades_digest'] != expected['trades_digest'] or result['fidelity'] != expected['fidelity']:
                raise AssertionError('FC trade / fidelity differs')
            for key in ('by_year', 'maxdd', 'win', 'payoff', 'entries_by_year', 'invested_basis',
                        'max_close_positions', 'max_close_gross'):
                if result['metrics'][key] != expected['metrics'][key]:
                    raise AssertionError('FC metric differs ' + key)
        traces[name] = fv.trace_orders(d, active, rules, result['trades_digest'])
        if any(year['max_positions_after_open'] > 6 for year in traces[name]['years'].values()):
            raise AssertionError('six positions exceeded after opening')
        if result['metrics']['max_close_gross'] > 1 + 1e-7:
            raise AssertionError('cash gross exceeds one at close')
    out = {'dataset_digest': dataset.digest(), 'fc_sha256': sha(ref_path), 'fv_sha256': sha(Path(fv.__file__)),
           'system_sha256': sha(Path(system.__file__)), 'script_sha256': sha(Path(__file__)),
           'candidates': counts, 'wide_hit_counts': hit_counts, 'wide_nohit_counts': nohit_counts,
           'results': results, 'traces': traces}
    target = root / 'strong_continue_fw.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
