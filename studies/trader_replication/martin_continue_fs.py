"""FS: audit preclose-known stale holdings at FQ1's slot rejections."""
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
from studies.trader_replication import martin_continue_fn as fn
from studies.trader_replication import martin_continue_fq as fq
from studies.trader_replication import martin_continue_fr as fr
from studies.trader_replication import panels, system
from studies.trader_replication.martin_continue_b_check import digest
from studies.trader_replication.martin_continue_bv import daily_name_score
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import HOLD, f1_rules, hold_sim, u1_entries


def choose_weak(pos, prior_close, day, codes, pending):
    eligible, unknown = [], []
    for q in pos.values():
        code = str(codes[q.j])
        if q.side <= 0 or day - q.d0 < 3 or code in pending:
            continue
        price = float(prior_close[q.j])
        if not np.isfinite(price) or price <= 0:
            unknown.append(code)
            continue
        change = price / q.fill - 1
        if change < .02:
            eligible.append((float(change), code, q.j))
    if unknown:
        return {'status': 'prior_close_unknown', 'unknown': sorted(unknown), 'eligible_count': len(eligible)}
    if not eligible:
        return {'status': 'no_eligible', 'eligible_count': 0}
    change, code, j = min(eligible)
    return {'status': 'selected', 'eligible_count': len(eligible), 'weak_code': code,
            'weak_index': int(j), 'prior_return': change}


def trace_rejections(d, book, rules, targets, pending):
    source = Path(system.__file__).resolve()
    px, em = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules)
    records = {}

    def local(frame, event, arg):
        if event != 'return' or arg is not None:
            return local
        loc = frame.f_locals
        if loc.get('kind') not in ('n1', 'list') or 'd' not in loc or 'j' not in loc:
            return local
        day, j = loc['d'], loc['j']
        key = (d.days[day], loc['kind'], str(d.A['codes'][j]))
        if key not in targets:
            return local
        pos = loc.get('pos', {})
        if len(pos) != targets[key] or len(pos) != 11 or j in pos:
            raise AssertionError('target is not a slot-limit rejection')
        result = choose_weak(pos, d.A['close'][day - 1], day, d.A['codes'], pending.get(d.days[day], set()))
        if result['status'] == 'selected':
            op = float(d.A['open'][day, result.pop('weak_index')])
            result['status'] = 'possible' if np.isfinite(op) and op > 0 else 'selected_open_unknown'
        result['open_positions'] = len(pos)
        records[key] = result
        return local

    def dispatch(frame, event, arg):
        if event == 'call' and frame.f_code.co_name == 'open_pos' and Path(frame.f_code.co_filename).resolve() == source:
            frame.f_trace_lines = False
            return local
        return None

    track = {}
    try:
        sys.settrace(dispatch)
        _, _, trades = system.simulate(px, em, rules, book, *panels.WINDOW, audit=True, track=track)
    finally:
        sys.settrace(None)
    if set(records) != set(targets):
        raise AssertionError('not all slot rejections traced')
    return trades, records, track.get('add_orders', [])


def main():
    root = du.REPORTS
    fq_path, fr_path, fn_path, ep_path = (root / 'strong_continue_fq.json', root / 'strong_continue_fr.json',
                                          root / 'strong_continue_fn.json', root / 'strong_continue_ep_full.json')
    ref, windows, original, ep_ref = (json.loads(p.read_text()) for p in (fq_path, fr_path, fn_path, ep_path))
    if (ref['script_sha256'] != sha(Path(fq.__file__)) or windows['script_sha256'] != sha(Path(fr.__file__)) or
            windows['fq_sha256'] != sha(fq_path) or ref['system_sha256'] != sha(Path(system.__file__)) or
            original['script_sha256'] != sha(Path(fn.__file__)) or not ep_ref['original_peer_replayed']):
        raise ValueError('FQ / FR / FN / EP source differs')
    slot_reason = 'open_pos: rules.max_open and len(pos) >= rules.max_open'
    originals = [r for r in ref['traces']['FQ1']['orders'] if r['reason'] == slot_reason]
    targets = {(r['day'], r['kind'], r['code']): r['open_positions'] for r in originals}
    if len(targets) != len(originals):
        raise AssertionError('duplicate target')
    del originals
    pending = {}
    for e in ref['results']['FQ1']['add_events']:
        if e['status'] != 'confirmed':
            pending.setdefault(e['day'], set()).add(e['code'])
    expected_digest = ref['results']['FQ1']['trades_digest']
    expected_events = ref['results']['FQ1']['add_events']
    core_counts, list_counts, precision = original['core_counts'], original['list_counts'], original['core_precision_unknown']
    missed = [w for w in windows['windows'] if w['fo_held'] and not w['fq_held']]
    data_digest = ref['dataset_digest']
    del ref, windows, original, ep_ref
    gc.collect()
    dataset = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if dataset.digest() != data_digest:
        raise ValueError('dataset differs')
    d = du.make_data(dataset)
    fields, mask, unused = du.compute_fields(d)
    del unused
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
        raise AssertionError('list candidates differ')
    core = [[e for e in row if e[2] > 0 and e[5] != 'list'] for row in u1]
    core_open, found_core = dg.next_open(core, d.A['open'], d.A['low'], d.days)
    core_open, unknown = fe.remove_precision_unknown(core_open, d.days, d.A['codes'])
    unknown = [x for x in unknown if panels.WINDOW[0] <= x[0] <= panels.WINDOW[1]]
    if found_core != core_counts or unknown != precision:
        raise AssertionError('core candidates differ')
    _, book = fn.build_books(u1_open, core_open)
    del fields, mask, u1, core, u1_open, core_open
    gc.collect()
    rules = f1_rules(d, 6, (1, 3))
    rules = replace(rules, intraday_kinds=tuple(rules.intraday_kinds) + ('list', 'n1'),
                    trail_next_open=True, add_next_open=True, max_open=11)
    trades, records, actual_events = trace_rejections(d, book, rules, targets, pending)
    if digest(trades) != expected_digest or actual_events != expected_events:
        raise AssertionError('FQ trace changed account or add events')
    years = {}
    for y in ('2024', '2025', '2026'):
        group = [v for k, v in records.items() if k[0].startswith(y)]
        years[y] = {'rejections': len(group), 'statuses': dict(Counter(r['status'] for r in group)),
                    'eligible_count_histogram': dict(Counter(str(r['eligible_count']) for r in group))}
    for w in missed:
        w['replacement_options'] = []
        for e in w['fo_only_evidence']:
            key = (e['entry'], e['kind'], w['code'])
            if key not in records:
                raise AssertionError('FR target not traced')
            w['replacement_options'].append({'entry': e['entry'], 'kind': e['kind'], **records[key]})
    out = {'dataset_digest': data_digest, 'fq_sha256': sha(fq_path), 'fr_sha256': sha(fr_path),
           'script_sha256': sha(Path(__file__)), 'system_sha256': sha(Path(system.__file__)),
           'years': years, 'missed_windows': missed,
           'records': [{'day': k[0], 'kind': k[1], 'code': k[2], **v} for k, v in sorted(records.items())]}
    target = root / 'strong_continue_fs.json'
    with target.open('w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        f.write('\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
