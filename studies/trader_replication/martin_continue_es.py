"""ES: trace the corrected next-open accounts through fixed public winner windows."""
from collections import Counter
from dataclasses import replace
import gc
import json
from pathlib import Path
import sys

import numpy as np
from studies import trader_data
from studies.trader_replication import martin_continue_ah as ah
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ef as ef
from studies.trader_replication import martin_continue_ep as ep
from studies.trader_replication import martin_continue_er as er
from studies.trader_replication import system
from studies.trader_replication.martin_continue_ar import condition_lines
from studies.trader_replication.martin_continue_bv import daily_name_score
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import HOLD, f1_rules, hold_sim, nl_rules


def order_state(opening, low, stop):
    if not (np.isfinite(opening) and np.isfinite(low)) or opening <= 0:
        return 'missing'
    if opening <= stop:
        return 'cancel_gap'
    if np.float32(opening) == np.float32(stop):
        return 'precision_unknown'
    return 'stop_day0' if low <= stop else 'survives'


def run_trace(d, book, rules, targets, expected):
    source, conditions, records = Path(system.__file__).resolve(), condition_lines(Path(system.__file__).resolve()), {}
    px, em = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules)

    def local(frame, event, arg):
        fn, loc = frame.f_code.co_name, frame.f_locals
        relevant = fn == 'take' and event == 'line' and (fn, frame.f_lineno) in conditions
        relevant |= fn == 'open_pos' and event == 'return'
        if not relevant or loc.get('kind') != 'list' or 'd' not in loc or 'j' not in loc:
            return local
        key = (d.days[loc['d']], str(d.A['codes'][loc['j']]))
        if key not in targets:
            return local
        if fn == 'take':
            records[key] = {'reason': 'take: ' + conditions[(fn, frame.f_lineno)]}
        elif arg is None:
            condition = conditions.get((fn, frame.f_lineno), f'unknown return line {frame.f_lineno}')
            rec = {'reason': 'open_pos: ' + condition}
            held = loc.get('pos', {}).get(loc['j'])
            if held is not None:
                rec.update(held_kind=held.kind, held_entry=d.days[held.d0], held_side=held.side)
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
        _, _, trades = system.simulate(px, em, rules, book, '2024-01-02', '2026-10-16')
    finally:
        sys.settrace(None)
    keys = [[t['code'], int(t['side']), t['kind'], t['entry'], t['exit'], t['why']] for t in trades]
    if keys != expected:
        raise AssertionError('trace account differs from ER')
    return trades, records


def main():
    root = du.REPORTS
    er_path, ep_path = root / 'strong_continue_er.json', root / 'strong_continue_ep_full.json'
    ref, ep_ref = json.loads(er_path.read_text()), json.loads(ep_path.read_text())
    if ref['script_sha256'] != sha(Path(er.__file__)) or ref['ep_sha256'] != sha(ep_path) or not ep_ref['original_peer_replayed']:
        raise ValueError('ER / EP source differs')
    digest = ref['dataset_digest']
    expected = {name: ref['results'][name + '_open']['trade_keys'] for name in ('U1', 'SAT6')}
    expected_fidelity = {name: ref['results'][name + '_open']['fidelity'] for name in ('U1', 'SAT6')}
    expected_counts = ref['candidate_counts']
    del ref, ep_ref
    gc.collect()
    dataset = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if dataset.digest() != digest:
        raise ValueError('dataset differs')
    d = du.make_data(dataset)
    fields, mask, _ = du.compute_fields(d)
    old_eligible = ep.original_eligibility(d)
    replay, old_pot = ep.peer_potential(d, old_eligible)
    for i, day in enumerate(d.days):
        if not np.array_equal(replay[i], fields['peer_pot'][i], equal_nan=True):
            raise AssertionError('original peer_pot mismatch ' + day)
    del replay, old_pot, old_eligible
    gc.collect()
    events, eligible, _ = ep.causal_inputs(dataset, d, list(map(str, d.A['codes'])))
    fast = np.empty(events.shape, np.float32)
    for start in range(0, events.shape[1], 64):
        sl = slice(start, start + 64)
        fast[:, sl] = du._ROLL_MEAN(events[:, sl].astype(np.float32), 250)
    fields['fast250'] = fast
    del events, fast
    peer, pot = ep.peer_potential(d, eligible)
    fields['peer_pot'] = peer
    del peer, pot, eligible
    gc.collect()
    score = daily_name_score(fields, mask, HOLD['H3'])
    holding = hold_sim(score, 12, 36)
    del score
    u1, sat = ef.books(d, fields, mask)
    u1_open, u1_counts = ah.delayed_list(d, u1)
    sat_open, sat_counts = ah.delayed_list(d, sat)
    if {'U1': u1_counts, 'SAT6': sat_counts} != expected_counts:
        raise AssertionError('ER candidate counts differ')
    codes = list(map(str, d.A['codes']))
    windows, targets = [], set()
    for start, j, ticker, _, date in d.big:
        peak = start + 1 + int(np.nanargmax(d.h[start + 1:start + 21, j]))
        end = min(start + 10, peak - 1)
        days = []
        for day in range(start, end + 1):
            if day < 1:
                continue
            candidates = sorted((e for e in u1[day - 1] if e[5] == 'list'), key=lambda e: e[0])
            match = next((e for e in candidates if e[1] == j), None)
            chosen = match is not None and any(e[1] == j for e in candidates[:6])
            state = order_state(d.A['open'][day, j], d.A['low'][day, j], match[4]) if chosen else None
            if state in ('stop_day0', 'survives'):
                targets.add((d.days[day], codes[j]))
            days.append({'day': d.days[day], 'signal_day': d.days[day - 1], 'h3': bool(holding[day - 1, j]),
                         'candidate': match is not None, 'top_six': chosen, 'state': state})
        windows.append({'date': date, 'code': codes[j], 'peak_day': d.days[peak], 'end': d.days[end], 'days': days})
    del fields, mask, holding, u1, sat
    gc.collect()
    lever, unlevered = f1_rules(d, 6, (1, 3)), nl_rules(d, 6)
    cases = [('U1', u1_open, replace(lever, intraday_kinds=tuple(lever.intraday_kinds) + ('list',))),
             ('SAT6', sat_open, replace(unlevered, intraday_kinds=tuple(unlevered.intraday_kinds) + ('list',)))]
    results = {}
    for name, book, rules in cases:
        print('trace', name, flush=True)
        trades, records = run_trace(d, book, rules, targets, expected[name])
        year_counts = {}
        details = []
        for w in windows:
            start, end, code = d.di[w['date']], d.di[w['end']], w['code']
            stages = {'h3': any(x['h3'] for x in w['days']),
                      'candidate': any(x['h3'] and x['candidate'] for x in w['days']),
                      'top_six': any(x['h3'] and x['candidate'] and x['top_six'] for x in w['days']),
                      'fillable': any(x['h3'] and x['candidate'] and x['top_six'] and x['state'] in ('stop_day0', 'survives') for x in w['days']),
                      'survives': any(x['h3'] and x['candidate'] and x['top_six'] and x['state'] == 'survives' for x in w['days'])}
            actual = [t for t in trades if t['code'] == code and t['side'] > 0 and t['kind'] == 'list'
                      and start <= d.di[t['entry']] <= end]
            held = any(t['code'] == code and t['side'] > 0 and d.di[t['entry']] <= end and d.di[t['exit']] >= start for t in trades)
            missed = []
            for item in w['days']:
                key = (item['day'], code)
                if key in targets and not any(t['entry'] == item['day'] for t in actual):
                    missed.append({'day': item['day'], **records.get(key, {'reason': 'not_reached'})})
            details.append({**w, **stages, 'actual_list_entry': bool(actual), 'held_any_long': held, 'missed_orders': missed})
        for year in ('2024', '2025', '2026'):
            rows = [r for r in details if r['date'].startswith(year)]
            keys = ('h3', 'candidate', 'top_six', 'fillable', 'survives', 'actual_list_entry', 'held_any_long')
            year_counts[year] = {'windows': len(rows), **{k: sum(r[k] for r in rows) for k in keys}}
        expected_held = expected_fidelity[name]['prepeak_ten_day']
        if any(year_counts[y]['held_any_long'] != expected_held[y]['held'] for y in year_counts):
            raise AssertionError('ER window holdings differ ' + name)
        reasons = Counter(x['reason'] for w in details for x in w['missed_orders'])
        results[name] = {'years': year_counts, 'reasons': dict(reasons), 'windows': details}
    out = {'dataset_digest': digest, 'er_sha256': sha(er_path), 'ep_sha256': sha(ep_path),
           'script_sha256': sha(Path(__file__)), 'windows': len(windows), 'results': results}
    target = root / 'strong_continue_es.json'
    with target.open('w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        f.write('\n')
    print('wrote', target, 'windows', len(windows), flush=True)


if __name__ == '__main__':
    main()
