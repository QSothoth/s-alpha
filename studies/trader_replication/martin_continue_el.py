"""EL: trace the ORCL cutoff divergence and its account rejection reason."""
import gc
import json
from pathlib import Path
import sys

import numpy as np
from studies import trader_data
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ea as ea
from studies.trader_replication import martin_continue_ee as ee
from studies.trader_replication import martin_continue_ef as ef
from studies.trader_replication import martin_continue_ej as ej
from studies.trader_replication import system
from studies.trader_replication.martin_continue_ar import condition_lines
from studies.trader_replication.martin_continue_bv import daily_name_score
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import HOLD, f1_rules, hold_sim, nl_rules

DAY, CODE, CUT = '2026-05-13', 'US.ORCL', '2026-06-30'


def trace(d, book, rules, expected):
    source, conditions, records = Path(system.__file__).resolve(), condition_lines(Path(system.__file__).resolve()), []
    px, em = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules)

    def local(frame, event, arg):
        fn, loc = frame.f_code.co_name, frame.f_locals
        relevant = fn == 'take' and event == 'line' and (fn, frame.f_lineno) in conditions
        relevant |= fn == 'open_pos' and event == 'return'
        if not relevant or loc.get('kind') != 'list' or 'd' not in loc or 'j' not in loc:
            return local
        if (d.days[loc['d']], str(d.A['codes'][loc['j']])) != (DAY, CODE):
            return local
        if fn == 'take':
            records.append({'reason': 'take: ' + conditions[(fn, frame.f_lineno)]})
        elif arg is None:
            reason = conditions.get((fn, frame.f_lineno), f'unknown return line {frame.f_lineno}')
            row = {'reason': 'open_pos: ' + reason}
            held = loc.get('pos', {}).get(loc['j'])
            if held is not None:
                row.update(held_kind=held.kind, held_entry=d.days[held.d0], held_side=held.side)
            records.append(row)
        else:
            records.append({'reason': 'opened'})
        return local

    def dispatch(frame, event, arg):
        if event == 'call' and frame.f_code.co_name in ('take', 'open_pos') and Path(frame.f_code.co_filename).resolve() == source:
            return local
        return None

    try:
        sys.settrace(dispatch)
        _, _, trades = system.simulate(px, em, rules, book, '2024-01-02', CUT)
    finally:
        sys.settrace(None)
    keys = [[t['code'], int(t['side']), t['kind'], t['entry'], t['exit'], t['why']] for t in trades]
    if keys != expected:
        raise AssertionError('traced account differs from EJ')
    return records or [{'reason': 'not_reached'}]


def main(mode):
    if mode not in ('full', 'cut'):
        raise ValueError('expected full or cut')
    root = du.REPORTS
    full_path, cut_path = root / 'strong_continue_ej_full.json', root / f'strong_continue_ej_{CUT}.json'
    full, cut = json.loads(full_path.read_text()), json.loads(cut_path.read_text())
    if (full['script_sha256'] != sha(Path(ej.__file__)) or cut['script_sha256'] != full['script_sha256']
            or cut['dataset_digest'] != full['dataset_digest']):
        raise ValueError('EJ source inputs differ')
    source = full if mode == 'full' else cut
    expected = {name: source['snapshots'][name][CUT]['trade_keys'] for name in ('U1', 'SAT6')}
    expected_signal = {name: [r for r in source['snapshots'][name][CUT]['signals'][DAY] if r['code'] == CODE and r['kind'] == 'list']
                       for name in ('U1', 'SAT6')}
    digest = full['dataset_digest']
    del source, full, cut
    gc.collect()
    base = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if base.digest() != digest:
        raise ValueError('dataset differs')
    dataset = base if mode == 'full' else ea.LimitedDataset(base, CUT)
    raw = {}
    for code, day, values in dataset.rows():
        if code == CODE and day in ('2026-05-12', DAY):
            raw[day] = values[:4]
            if len(raw) == 2:
                break
    if len(raw) != 2:
        raise ValueError('raw ORCL bars missing')
    actions = [row for row in dataset.actions().get(CODE, []) if CUT < row[0] <= '2026-10-16']
    d = du.make_data(dataset)
    fields, mask, _ = du.compute_fields(d)
    events, positions = ee.source_inputs(dataset, d.days, list(map(str, d.A['codes'])))
    fast = np.empty(events.shape, dtype=np.float32)
    for start in range(0, events.shape[1], 64):
        sl = slice(start, start + 64)
        fast[:, sl] = du._ROLL_MEAN(events[:, sl].astype(np.float32), 250)
    fields['fast250'] = fast
    del events, fast
    score = daily_name_score(fields, mask, HOLD['H3'])
    holding = hold_sim(score, 12, 36)
    i, j = d.di[DAY], list(map(str, d.A['codes'])).index(CODE)
    order = np.argsort(-np.nan_to_num(score[i], nan=-1e9))
    rank = int(np.flatnonzero(order == j)[0])
    c, low, high, prev_high, e9 = (float(d.c[i, j]), float(d.l[i, j]), float(d.h[i, j]),
                                    float(d.h[i - 1, j]), float(d.e9[i, j]))
    info = {'active': bool(mask[i, j]), 'h3': bool(holding[i, j]), 'rank': rank,
            'close': c, 'low': low, 'high': high, 'prev_high': prev_high, 'ema9': e9,
            'lowe9': float(fields['lowe9'][i, j]), 'cpos': float(fields['cpos'][i, j]),
            'raw_cpos': float(positions[i, j]), 'ext21': float(fields['ext21'][i, j]),
            'pull': bool(fields['lowe9'][i, j] <= .1 and c > e9),
            'breakout': bool(c > prev_high and fields['cpos'][i, j] >= .5),
            'c_above_e9': bool(c > e9), 'close_over_ema9': c / e9}
    del score, holding
    gc.collect()
    u1, sat = ef.books(d, fields, mask)
    actual_signal = {name: [e for e in book[i] if str(d.A['codes'][e[1]]) == CODE and e[5] == 'list']
                     for name, book in (('U1', u1), ('SAT6', sat))}
    for name in actual_signal:
        if len(actual_signal[name]) != len(expected_signal[name]):
            raise AssertionError('EJ ORCL candidate mismatch ' + name)
    del positions, fields, mask
    gc.collect()
    records = {name: trace(d, book, rules, expected[name]) for name, book, rules in
               (('U1', u1, f1_rules(d, 6, (1, 3))), ('SAT6', sat, nl_rules(d, 6)))}
    out = {'mode': mode, 'ej_full_sha256': sha(full_path), 'ej_cut_sha256': sha(cut_path),
           'script_sha256': sha(Path(__file__)), 'raw_ohlc': raw, 'later_actions': actions,
           'signal': info, 'account_trace': records}
    target = root / f'strong_continue_el_{mode}.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main(sys.argv[1])
