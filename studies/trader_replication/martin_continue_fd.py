"""FD: audit paired trail exits and a fixed double-cost sensitivity."""
from collections import Counter
from dataclasses import replace
import gc
import hashlib
import json
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trader_replication import compare, panels, system
from studies.trader_replication import martin_continue_dg as dg
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_fc as fc_module
from studies.trader_replication.martin_continue_b_check import digest
from studies.trader_replication.martin_continue_bm import describe
from studies.trader_replication.martin_continue_bt import fidelity
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import longs, nl_rules


def signal_audit(d, trades):
    codes = {str(code): j for j, code in enumerate(d.A['codes'])}
    counts, missing, queued = Counter(), [], []
    for t in trades:
        if 'trail_signal' not in t:
            continue
        start, end, j = d.di[t['trail_signal']], d.di[t['exit']], codes[t['code']]
        if t['why'] not in ('trail_open', 'gap_stop', 'end'):
            raise AssertionError('unexpected post-signal exit')
        for i in range(start + 1, end):
            op = d.A['open'][i, j]
            if np.isfinite(op) and op > 0:
                raise AssertionError('valid open skipped')
            missing.append([d.days[i], t['code']])
        if t['why'] == 'end':
            op = d.A['open'][end, j]
            if end > start and np.isfinite(op) and op > 0:
                raise AssertionError('pending position had valid final open')
            if not t['state'].get('trail_pending'):
                raise AssertionError('pending state missing')
            queued.append([t['code'], t['trail_signal']])
        else:
            if end <= start:
                raise AssertionError('exit precedes next session')
            opening = float(d.A['open'][end, j])
            if not np.isfinite(opening) or opening <= 0 or t['executions'][-1]['price'] != opening:
                raise AssertionError('exit was not at valid open')
        counts[t['why']] += 1
    return {'events': dict(counts), 'missing_open_stock_days': missing, 'pending_end': queued}


def main():
    root = du.REPORTS
    reference = root / 'strong_continue_ez.json'
    ref = json.loads(reference.read_text())
    fc_path = root / 'strong_continue_fc.json'
    fc = json.loads(fc_path.read_text())
    if fc['script_sha256'] != sha(Path(fc_module.__file__)) or fc['system_sha256'] != sha(Path(system.__file__)):
        raise ValueError('FC source differs')
    old_system = root / 'source_pins/system_pre_fc.py.txt'
    if ref['code_sha256']['studies/trader_replication/system.py'] != sha(old_system):
        raise ValueError('EZ engine source differs')
    dataset = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if dataset.digest() != ref['dataset_digest']:
        raise ValueError('frozen dataset differs')
    d = du.make_data(dataset)
    reg = [[((1.0,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:6])
            for e in row] for row in longs(d.reg)]
    book, counts = dg.next_open(reg, d.A['open'], d.A['low'], d.days)
    if counts != ref['candidates']:
        raise AssertionError('EZ candidate counts differ')
    kinds = sorted({e[5] for row in book for e in row})
    rules = replace(nl_rules(d, 6), gross_cost=True)
    rules = replace(rules, intraday_kinds=tuple(sorted(set(rules.intraday_kinds) | set(kinds))))
    del d.fp, d.fwd, d.raw
    for k in ('pr21', 'pr63', 'pr126', 'rank_pool', 'stack', 'tight'):
        d.A.pop(k, None)
    d.rk = d.rk.astype(np.int32)
    gc.collect()
    px, em = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules)
    lo = int(np.searchsorted(d.A['days'], panels.WINDOW[0]))
    hi = int(np.searchsorted(d.A['days'], panels.WINDOW[1], side='right'))
    results = {}
    trail = replace(rules, trail_next_open=True)
    for name, ru in (('DG1_cash', rules), ('FC1', trail),
                     ('DG1_x2', replace(rules, buy_cost=2 * rules.buy_cost, sell_cost=2 * rules.sell_cost)),
                     ('FC1_x2', replace(trail, buy_cost=2 * trail.buy_cost, sell_cost=2 * trail.sell_cost))):
        track = {}
        curve, dates, trades = system.simulate(px, em, ru, book, *panels.WINDOW, audit=True, track=track)
        metrics = compare.metrics(curve, dates, trades, book, lo, hi)
        metrics['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in trades) for y in ('2024', '2025', '2026')}
        metrics['invested_basis'] = describe([t for t in trades if t['why'] != 'end'], 'ret_invested')
        metrics['max_close_gross'] = float(max(track['gross']))
        metrics['close_days_gross_over_one'] = int(sum(g > 1 + 1e-9 for g in track['gross']))
        metrics['max_close_positions'] = max(track['open'])
        if name == 'DG1_cash':
            expected = ref['results'][name]
            if digest(trades) != expected['trades_digest'] or fidelity(d, trades) != expected['fidelity']:
                raise AssertionError('EZ baseline trades or fidelity differ')
            for year in ('2024', '2025', '2026'):
                if (abs(metrics['by_year'][year] - expected['metrics']['by_year'][year]) > 1e-10 or
                        metrics['entries_by_year'][year] != expected['metrics']['entries_by_year'][year]):
                    raise AssertionError('EZ baseline differs ' + year)
        if name in ('DG1_cash', 'FC1') and (digest(trades) != fc['results'][name]['trades_digest'] or
                                                fidelity(d, trades) != fc['results'][name]['fidelity']):
            raise AssertionError('FC reference differs ' + name)
        reasons = {y: dict(Counter(t['why'] for t in trades if t['exit'].startswith(y)))
                   for y in ('2024', '2025', '2026')}
        results[name] = {'metrics': metrics, 'fidelity': fidelity(d, trades), 'trades_digest': digest(trades),
                         'trade_keys': [[t['code'], t['side'], t['entry'], t['exit'], t['why']] for t in trades],
                         'exit_reasons': reasons, 'trail_audit': signal_audit(d, trades),
                         'trades': [{k: t.get(k) for k in ('code', 'side', 'entry', 'exit', 'why', 'fill', 'ret', 'pnl', 'trail_signal', 'executions')}
                                    for t in trades]}
    out = {'dataset_digest': ref['dataset_digest'], 'reference_sha256': sha(reference),
           'old_system_sha256': sha(old_system), 'system_sha256': sha(Path(system.__file__)),
           'script_sha256': sha(Path(__file__)), 'fc_sha256': sha(fc_path), 'candidates': counts, 'results': results}
    target = root / 'strong_continue_fd.json'
    with target.open('w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        f.write('\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
