"""FV: compare original and doubled core stop distance."""
from collections import Counter
from dataclasses import replace
import gc
import json
from pathlib import Path
import sys

import numpy as np
from studies import trader_data
from studies.trader_replication import martin_continue_ah as ah
from studies.trader_replication import martin_continue_dg as dg
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ep as ep
from studies.trader_replication import martin_continue_er as er
from studies.trader_replication import martin_continue_fe as fe
from studies.trader_replication import martin_continue_fc as fc
from studies.trader_replication import martin_continue_fq as fq
from studies.trader_replication import martin_continue_fn as fn
from studies.trader_replication import martin_continue_fo as fo
from studies.trader_replication import martin_continue_fp as fp
from studies.trader_replication import panels, system
from studies.trader_replication.martin_continue_ar import condition_lines
from studies.trader_replication.martin_continue_b_check import digest
from studies.trader_replication.martin_continue_bv import daily_name_score
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import HOLD, f1_rules, hold_sim, u1_entries


def trace_orders(d, book, rules, expected_digest):
    targets = [(d.days[i], e[5], str(d.A['codes'][e[1]])) for i, row in enumerate(book)
               if panels.WINDOW[0] <= d.days[i] <= panels.WINDOW[1] for e in row]
    if len(targets) != len(set(targets)):
        raise AssertionError('duplicate kind / code / day')
    targets = set(targets)
    conditions, records = condition_lines(Path(system.__file__).resolve()), {}
    source = Path(system.__file__).resolve()
    px, em = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules)

    def local(frame, event, arg):
        name, loc = frame.f_code.co_name, frame.f_locals
        relevant = name == 'take' and event == 'line' and (name, frame.f_lineno) in conditions
        relevant |= name == 'open_pos' and event == 'return'
        if not relevant or loc.get('kind') not in ('n1', 'list') or 'd' not in loc or 'j' not in loc:
            return local
        key = (d.days[loc['d']], loc['kind'], str(d.A['codes'][loc['j']]))
        if key not in targets:
            return local
        if name == 'take':
            records[key] = {'reason': 'take: ' + conditions[(name, frame.f_lineno)]}
        elif arg is None:
            condition = conditions.get((name, frame.f_lineno), f'unknown return line {frame.f_lineno}')
            pos = loc.get('pos', {})
            held = pos.get(loc['j'])
            rec = {'reason': 'open_pos: ' + condition, 'open_positions': len(pos)}
            if held is not None:
                rec.update(held_kind=held.kind, held_entry=d.days[held.d0], held_side=int(held.side))
            if condition == 'val <= 0.001 * equity' and loc.get('equity', 0) > 0:
                limits = {'risk_budget': loc['frac'] / loc['width'], 'position_cap': loc['cap'],
                          'gross_room': loc['room'] / loc['equity']}
                smallest = min(limits.values())
                rec['limiting'] = [k for k, v in limits.items() if abs(v - smallest) < 1e-12]
            records[key] = rec
        else:
            records[key] = {'reason': 'opened', 'open_positions': len(loc.get('pos', {}))}
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
    if digest(trades) != expected_digest:
        raise AssertionError('trace changed account')
    opened = {k for k, v in records.items() if v['reason'] == 'opened'}
    if opened != {(t['entry'], t['kind'], t['code']) for t in trades}:
        raise AssertionError('traced opens differ from trades')
    rows = [{'day': day, 'kind': kind, 'code': code, **records.get((day, kind, code), {'reason': 'not_reached'})}
            for day, kind, code in sorted(targets)]
    by_year = {}
    for year in ('2024', '2025', '2026'):
        sample = [r for r in rows if r['day'].startswith(year)]
        by_year[year] = {'fillable_candidates': len(sample), 'reasons': dict(Counter(r['reason'] for r in sample)),
                         'limiting': dict(Counter(k for r in sample for k in r.get('limiting', []))),
                         'max_positions_after_open': max((r['open_positions'] for r in sample
                                                          if r['reason'] == 'opened'), default=0)}
    return {'years': by_year, 'orders': rows}


def list_ema9(rules):
    management = {k: dict(v) for k, v in rules.management_by_kind.items()}
    management['list'] = {**management.get('list', {}), 'trail': 'e9'}
    return replace(rules, management_by_kind=management)


def wide_book(book, d, ambiguous_hit):
    result, counts = [], Counter()
    for day, row in enumerate(book):
        updated = []
        for e in row:
            if e[5] != 'n1' or e[2] <= 0:
                updated.append(e)
                continue
            opening, old_stop = float(e[3]), float(e[4])
            stop = opening - 2 * (opening - old_stop)
            low = float(d.A['low'][day, e[1]])
            if not (np.isfinite(stop) and stop > 0 and np.isfinite(low) and low > 0):
                raise ValueError('invalid wide stop or low')
            if np.float32(stop) == np.float32(opening):
                raise ValueError('wide stop indistinguishable from opening')
            ambiguous = np.float32(low) == np.float32(stop)
            hit = ambiguous_hit if ambiguous else low < stop
            if panels.WINDOW[0] <= d.days[day] <= panels.WINDOW[1]:
                year = d.days[day][:4]
                counts[year + ':orders'] += 1
                counts[year + ':unknown'] += int(ambiguous)
                counts[year + ':stop_day0'] += int(hit)
            updated.append(tuple(e[:4]) + (stop, e[5], stop if hit else None) + tuple(e[7:]))
        result.append(updated)
    return result, dict(sorted(counts.items()))


def main():
    root = du.REPORTS
    ref_path, fn_path, ep_path = (root / 'strong_continue_fp.json', root / 'strong_continue_fn.json',
                                  root / 'strong_continue_ep_full.json')
    ref, original = json.loads(ref_path.read_text()), json.loads(fn_path.read_text())
    ep_ref = json.loads(ep_path.read_text())
    if (ref['script_sha256'] != sha(Path(fp.__file__)) or ref['system_sha256'] != sha(Path(system.__file__)) or
            original['script_sha256'] != sha(Path(fn.__file__)) or not ep_ref['original_peer_replayed']):
        raise ValueError('FP / FN / EP source differs')
    expected = ref['results']['FO1']
    core_counts, list_counts, precision = original['core_counts'], original['list_counts'], original['core_precision_unknown']
    data_digest = ref['dataset_digest']
    fq_path = root / 'strong_continue_fq.json'
    fq_ref = json.loads(fq_path.read_text())
    if (fq_ref['script_sha256'] != sha(Path(fq.__file__)) or fq_ref['system_sha256'] != sha(Path(system.__file__)) or
            fq_ref['dataset_digest'] != data_digest):
        raise ValueError('FQ source differs')
    expected_fq = fq_ref['results']['FQ1']
    del fq_ref, ref, original, ep_ref
    gc.collect()
    dataset = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if dataset.digest() != data_digest:
        raise ValueError('dataset differs')
    d = du.make_data(dataset)
    fields, mask, unused_holding = du.compute_fields(d)
    del unused_holding
    gc.collect()
    original_eligible = ep.original_eligibility(d)
    replay, old_pot = ep.peer_potential(d, original_eligible)
    for i, day in enumerate(d.days):
        if not np.array_equal(replay[i], fields['peer_pot'][i], equal_nan=True):
            raise AssertionError('original peer_pot mismatch ' + day)
    del original_eligible, replay, old_pot
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
    u1 = u1_entries(d, fields, holding, score)
    del score, holding
    u1_open, found_list = ah.delayed_list(d, u1)
    if found_list != list_counts or er.ambiguous_orders(d, u1):
        raise AssertionError('list candidates differ or precision unknown')
    core = [[e for e in row if e[2] > 0 and e[5] != 'list'] for row in u1]
    core_open, found_core = dg.next_open(core, d.A['open'], d.A['low'], d.days)
    core_open, unknown = fe.remove_precision_unknown(core_open, d.days, d.A['codes'])
    unknown = [x for x in unknown if panels.WINDOW[0] <= x[0] <= panels.WINDOW[1]]
    if found_core != core_counts or unknown != precision:
        raise AssertionError('core candidates differ')
    _, book = fn.build_books(u1_open, core_open)
    del fields, mask, u1, core, u1_open, core_open
    gc.collect()
    base = f1_rules(d, 6, (1, 3))
    base = replace(base, intraday_kinds=tuple(base.intraday_kinds) + ('list', 'n1'),
                   trail_next_open=True, add_next_open=True)
    wide_hit, hit_counts = wide_book(book, d, True)
    wide_nohit, nohit_counts = wide_book(book, d, False)
    cases = [('FO1', book, base), ('FQ1', book, replace(base, max_open=11)),
             ('FV0_hit', wide_hit, base), ('FV0_nohit', wide_nohit, base),
             ('FV1_hit', wide_hit, replace(base, max_open=11)),
             ('FV1_nohit', wide_nohit, replace(base, max_open=11))]
    results, trails, traces = {}, {}, {}
    for name, active_book, rules in cases:
        print('account', name, flush=True)
        results[name] = fo.account(d, active_book, rules)
        if name == 'FO1' and results[name] != expected:
            raise AssertionError('FP baseline differs')
        if name == 'FQ1' and results[name] != expected_fq:
            raise AssertionError('FQ baseline differs')
        px, em = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules)
        _, _, trades = system.simulate(px, em, rules, active_book, *panels.WINDOW, audit=True)
        if digest(trades) != results[name]['trades_digest']:
            raise AssertionError('trail audit changed account')
        trails[name] = fc.signal_audit(d, trades)
        if name.startswith('FV1'):
            traces[name] = trace_orders(d, active_book, rules, results[name]['trades_digest'])
            if any(x['max_positions_after_open'] > 11 for x in traces[name]['years'].values()):
                raise AssertionError('eleven positions exceeded after open')
    out = {'dataset_digest': data_digest, 'fp_sha256': sha(ref_path), 'fq_sha256': sha(fq_path),
           'system_sha256': sha(Path(system.__file__)), 'script_sha256': sha(Path(__file__)),
           'core_counts': core_counts, 'list_counts': list_counts, 'core_precision_unknown': precision,
           'results': results, 'trail_audits': trails, 'traces': traces,
           'wide_hit_counts': hit_counts, 'wide_nohit_counts': nohit_counts}
    target = root / 'strong_continue_fv.json'
    with target.open('w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        f.write('\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
