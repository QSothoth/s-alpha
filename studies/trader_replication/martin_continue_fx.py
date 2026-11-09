"""FX: audit cash immediately after each opening in the FW accounts."""
from dataclasses import replace
import gc
import json
from pathlib import Path
import sys

import numpy as np
from studies import trader_data
from studies.trader_replication import panels, system
from studies.trader_replication import martin_continue_dg as dg
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_fv as fv
from studies.trader_replication.martin_continue_b_check import digest
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import longs, nl_rules


def audit_open_cash(d, book, rules, expected):
    source = Path(system.__file__).resolve()
    records = []

    def trace(frame, event, arg):
        if event == 'return' and arg:
            loc = frame.f_locals
            records.append({'day': d.days[loc['d']], 'code': str(d.A['codes'][loc['j']]),
                            'cash': float(loc['cash'])})
        return trace

    def dispatch(frame, event, arg):
        if event == 'call' and frame.f_code.co_name == 'open_pos' and Path(frame.f_code.co_filename).resolve() == source:
            return trace
        return None

    px, em = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules)
    try:
        sys.settrace(dispatch)
        _, _, trades = system.simulate(px, em, rules, book, *panels.WINDOW, audit=True)
    finally:
        sys.settrace(None)
    if digest(trades) != expected['trades_digest']:
        raise AssertionError('traced account differs from FW')
    keys = [(r['day'], r['code']) for r in records]
    if sorted(keys) != sorted((t['entry'], t['code']) for t in trades):
        raise AssertionError('opening trace differs from trades')
    negatives = [r for r in records if r['cash'] < -1e-10]
    return {'minimum_cash': min((r['cash'] for r in records), default=None),
            'openings': len(records), 'negative_cash': negatives, 'records': records}


def main():
    root = du.REPORTS
    ref_path = root / 'strong_continue_fw.json'
    ref = json.loads(ref_path.read_text())
    if ref['fv_sha256'] != sha(Path(fv.__file__)) or ref['system_sha256'] != sha(Path(system.__file__)):
        raise ValueError('FV or system source differs')
    dataset = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if dataset.digest() != ref['dataset_digest']:
        raise ValueError('dataset differs')
    d = du.make_data(dataset)
    reg = [[((1.0,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:6])
            for e in row] for row in longs(d.reg)]
    book, counts = dg.next_open(reg, d.A['open'], d.A['low'], d.days)
    if counts != ref['candidates']:
        raise AssertionError('candidate counts differ')
    kinds = {e[5] for row in book for e in row}
    rules = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True)
    rules = replace(rules, intraday_kinds=tuple(sorted(set(rules.intraday_kinds) | kinds)))
    del d.fp, d.fwd, d.raw
    for key in ('pr21', 'pr63', 'pr126', 'rank_pool', 'stack', 'tight'):
        d.A.pop(key, None)
    d.rk = d.rk.astype(np.int32)
    gc.collect()
    hit, hit_counts = fv.wide_book(book, d, True)
    nohit, nohit_counts = fv.wide_book(book, d, False)
    if hit_counts != ref['wide_hit_counts'] or nohit_counts != ref['wide_nohit_counts']:
        raise AssertionError('wide-stop counts differ')
    results = {}
    for name, active in (('FC1', book), ('FW_hit', hit), ('FW_nohit', nohit)):
        print('cash audit', name, flush=True)
        results[name] = audit_open_cash(d, active, rules, ref['results'][name])
    out = {'dataset_digest': dataset.digest(), 'fw_sha256': sha(ref_path),
           'system_sha256': sha(Path(system.__file__)), 'script_sha256': sha(Path(__file__)), 'results': results}
    target = root / 'strong_continue_fx.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
