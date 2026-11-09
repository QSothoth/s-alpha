"""FM: trace every FC1 preselected open order through the account's actual guards."""
from collections import Counter
from dataclasses import replace
import gc
import json
from pathlib import Path
import sys

import numpy as np
from studies import trader_data
from studies.trader_replication import martin_continue_dg as dg
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_fc as fc
from studies.trader_replication import panels, system
from studies.trader_replication.martin_continue_ar import condition_lines
from studies.trader_replication.martin_continue_b_check import digest
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import longs, nl_rules


def preselected(d, reg):
    rows = []
    for day in range(1, len(d.days)):
        if not panels.WINDOW[0] <= d.days[day] <= panels.WINDOW[1]:
            continue
        for e in sorted(reg[day - 1], key=lambda x: x[0]):
            j, stop = e[1], float(e[4])
            opening, low = float(d.A['open'][day, j]), float(d.A['low'][day, j])
            if not np.isfinite(opening) or opening <= 0:
                status = 'missing_open'
            elif np.float32(opening) == np.float32(stop):
                status = 'precision_unknown'
            elif opening <= stop:
                status = 'gap_cancel'
            elif not np.isfinite(low):
                status = 'missing_low'
            else:
                status = 'fillable'
            rows.append({'day': d.days[day], 'signal_day': d.days[day - 1], 'code': str(d.A['codes'][j]),
                         'status': status, 'same_day_stop': bool(status == 'fillable' and low <= stop)})
    keys = [(r['day'], r['code']) for r in rows]
    if len(keys) != len(set(keys)):
        raise AssertionError('duplicate order code / day')
    return rows


def trace_account(d, book, rules, targets):
    source = Path(system.__file__).resolve()
    conditions = condition_lines(source)
    records = {}
    px, em = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules)

    def local(frame, event, arg):
        fn, loc = frame.f_code.co_name, frame.f_locals
        relevant = fn == 'take' and event == 'line' and (fn, frame.f_lineno) in conditions
        relevant |= fn == 'open_pos' and event == 'return'
        if not relevant or loc.get('kind') != 'n1' or 'd' not in loc or 'j' not in loc:
            return local
        key = (d.days[loc['d']], str(d.A['codes'][loc['j']]))
        if key not in targets:
            return local
        if fn == 'take':
            records[key] = {'reason': 'take: ' + conditions[(fn, frame.f_lineno)]}
        elif arg is None:
            condition = conditions.get((fn, frame.f_lineno), f'unknown return line {frame.f_lineno}')
            held = loc.get('pos', {}).get(loc['j'])
            rec = {'reason': 'open_pos: ' + condition, 'open_positions': len(loc.get('pos', {}))}
            if held is not None:
                rec.update(held_kind=held.kind, held_entry=d.days[held.d0], held_side=int(held.side))
            if condition == 'val <= 0.001 * equity' and loc.get('equity', 0) > 0:
                limits = {'risk_budget': loc['frac'] / loc['width'], 'position_cap': loc['cap'],
                          'gross_room': loc['room'] / loc['equity']}
                smallest = min(limits.values())
                rec['limiting'] = [k for k, v in limits.items() if abs(v - smallest) < 1e-12]
            records[key] = rec
        else:
            records[key] = {'reason': 'opened'}
        return local

    def dispatch(frame, event, arg):
        if event == 'call' and frame.f_code.co_name in ('take', 'open_pos') and Path(frame.f_code.co_filename).resolve() == source:
            return local
        return None

    try:
        sys.settrace(dispatch)
        _, _, trades = system.simulate(px, em, rules, book, *panels.WINDOW, audit=True)
    finally:
        sys.settrace(None)
    return trades, records


def main():
    root = du.REPORTS
    reference = root / 'strong_continue_fc.json'
    ref = json.loads(reference.read_text())
    if ref['script_sha256'] != sha(Path(fc.__file__)) or ref['system_sha256'] != sha(Path(system.__file__)):
        raise ValueError('FC source differs')
    dataset = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if dataset.digest() != ref['dataset_digest']:
        raise ValueError('dataset differs')
    d = du.make_data(dataset)
    reg = [[((1.0,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:6])
            for e in row] for row in longs(d.reg)]
    book, counts = dg.next_open(reg, d.A['open'], d.A['low'], d.days)
    if counts != ref['candidates']:
        raise AssertionError('FC candidate counts differ')
    rows = preselected(d, reg)
    targets = {(r['day'], r['code']) for r in rows if r['status'] == 'fillable'}
    book_keys = {(d.days[i], str(d.A['codes'][e[1]])) for i, row in enumerate(book)
                 if panels.WINDOW[0] <= d.days[i] <= panels.WINDOW[1] for e in row}
    if targets != book_keys:
        raise AssertionError('fillable set differs from FC')
    kinds = {e[5] for row in book for e in row}
    if kinds != {'n1'}:
        raise ValueError('expected n1-only long book')
    rules = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True)
    rules = replace(rules, intraday_kinds=tuple(sorted(set(rules.intraday_kinds) | kinds)))
    del d.fp, d.fwd, d.raw
    for k in ('pr21', 'pr63', 'pr126', 'rank_pool', 'stack', 'tight'):
        d.A.pop(k, None)
    d.rk = d.rk.astype(np.int32)
    gc.collect()
    trades, records = trace_account(d, book, rules, targets)
    if digest(trades) != ref['results']['FC1']['trades_digest']:
        raise AssertionError('traced trades differ from FC')
    if set(records) != targets:
        raise AssertionError('not every fillable order was traced')
    opened = {key for key, rec in records.items() if rec['reason'] == 'opened'}
    if opened != {(t['entry'], t['code']) for t in trades}:
        raise AssertionError('opened orders differ from FC trades')
    for r in rows:
        key = (r['day'], r['code'])
        if key in records:
            r.update(records[key])
    by_year = {}
    for year in ('2024', '2025', '2026'):
        group = [r for r in rows if r['day'].startswith(year)]
        reasons = Counter(r.get('reason', r['status']) for r in group)
        by_year[year] = {'preselected': len(group), 'status': dict(Counter(r['status'] for r in group)),
                         'same_day_stop_candidates': sum(r['same_day_stop'] for r in group),
                         'reasons': dict(reasons),
                         'held_earlier': sum(bool(r.get('held_entry') and r['held_entry'] < r['day']) for r in group),
                         'limiting': dict(Counter(item for r in group for item in r.get('limiting', [])))}
    out = {'dataset_digest': ref['dataset_digest'], 'fc_sha256': sha(reference),
           'script_sha256': sha(Path(__file__)), 'system_sha256': sha(Path(system.__file__)),
           'candidates': counts, 'by_year': by_year, 'rows': rows}
    target = root / 'strong_continue_fm.json'
    with target.open('w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        f.write('\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
