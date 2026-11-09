"""HB: freeze the entire prior-close long order stream before opening filters."""
from collections import Counter, defaultdict
import gc
import json
from pathlib import Path

import numpy as np

from studies import trader_data
from studies.trader_replication import panels, system
from studies.trader_replication import martin_continue_ah as ah
from studies.trader_replication import martin_continue_dg as dg
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ep as ep
from studies.trader_replication import martin_continue_er as er
from studies.trader_replication import martin_continue_fe as fe
from studies.trader_replication import martin_continue_fn as fn
from studies.trader_replication import martin_continue_gi as gi
from studies.trader_replication import martin_continue_gu as gu
from studies.trader_replication import martin_continue_gz as gz
from studies.trader_replication.martin_continue_bv import daily_name_score
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import HOLD, hold_sim, u1_entries


def priority(value):
    if isinstance(value, (tuple, list)):
        return [priority(v) for v in value]
    value = float(value)
    if not np.isfinite(value):
        raise ValueError('non-finite preselected priority')
    return value


def freeze_orders(days, codes, book, close, window=panels.WINDOW):
    """Read the signal row only, retaining orders regardless of next-day prices."""
    output = []
    for d in range(len(days) - 1):
        if not window[0] <= days[d + 1] <= window[1]:
            continue
        row = book[d]
        core = [e for e in row if e[2] > 0 and e[5] != 'list']
        trial = sorted((e for e in row if e[2] > 0 and e[5] == 'list'), key=lambda e: e[0])[:6]
        for e in core + trial:
            signal_close = float(close[d, e[1]])
            if not np.isfinite(signal_close) or signal_close <= 0 or signal_close != float(e[3]):
                raise AssertionError('entry price is not the signal-day close')
            stop = float(e[4])
            if not np.isfinite(stop) or not 0 < stop < signal_close:
                raise AssertionError('invalid prior-close initial stop')
            output.append({'signal_day': str(days[d]), 'day': str(days[d + 1]), 'code': str(codes[e[1]]),
                           'kind': e[5], 'priority': priority(e[0]), 'close': signal_close, 'stop': stop,
                           'size_risk': float(e[7]) if len(e) > 7 and e[7] is not None else None,
                           'max_position': float(e[8]) if len(e) > 8 and e[8] is not None else None,
                           'risk_mult': float(e[9]) if len(e) > 9 and e[9] is not None else None,
                           'add_mult': float(e[10]) if len(e) > 10 and e[10] is not None else None})
    keys = [(r['day'], r['code'], r['kind']) for r in output]
    if len(keys) != len(set(keys)):
        raise AssertionError('duplicate prior order')
    return output


def observe(order, opening, low):
    """Classify later observations without changing the submitted prior order."""
    stop = order['stop']
    valid_open = np.isfinite(opening) and opening > 0
    valid_low = np.isfinite(low) and low > 0
    same_open = bool(valid_open and np.float32(opening) == np.float32(stop))
    same_low = bool(valid_low and np.float32(low) == np.float32(stop))
    if not valid_open or (order['kind'] == 'list' and not valid_low):
        status = 'missing'
    elif opening <= stop:
        status = 'open_at_or_below_stop'
    elif not valid_low:
        status = 'missing_low'
    elif order['kind'] != 'list' and same_open:
        status = 'old_precision_removed'
    else:
        status = 'old_accepted'
    return {'status': status, 'opening': float(opening) if valid_open else None,
            'low': float(low) if valid_low else None, 'open_stop_float32_equal': same_open,
            'low_stop_float32_equal': same_low}


def main():
    root = du.REPORTS
    gi_path, gu_path, gz_path = (root / f'strong_continue_{n}.json' for n in ('gi', 'gu', 'gz'))
    ref, base, latest = (json.loads(p.read_text()) for p in (gi_path, gu_path, gz_path))
    pinned = root / 'source_pins/system_pre_gz.py.txt'
    if (ref['script_sha256'] != sha(Path(gi.__file__)) or ref['system_sha256'] != sha(pinned) or
            base['script_sha256'] != sha(Path(gu.__file__)) or base['gi_sha256'] != sha(gi_path) or
            base['system_sha256'] != sha(pinned) or latest['script_sha256'] != sha(Path(gz.__file__)) or
            latest['system_sha256'] != sha(Path(system.__file__))):
        raise ValueError('reference source differs')
    dataset = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    data_digest = dataset.digest()
    if any(x['dataset_digest'] != data_digest for x in (ref, base, latest)):
        raise ValueError('frozen data differs')
    core_counts, list_counts = ref['old_core_counts'], ref['old_list_counts']
    old_unknown, low_unknown = ref['old_core_precision_unknown'], base['low_precision_unknown']
    open_unknown = [r for r in ref['fixed_hit_orders'] if r.get('old_open_stop_precision_unknown')]
    del ref, base, latest
    gc.collect()
    d = du.make_data(dataset)
    fields, mask, unused = du.compute_fields(d)
    del unused
    gc.collect()
    original = ep.original_eligibility(d)
    replay, old_pot = ep.peer_potential(d, original)
    for i, day in enumerate(d.days):
        if not np.array_equal(replay[i], fields['peer_pot'][i], equal_nan=True):
            raise AssertionError('original peer potential differs: ' + day)
    del original, replay, old_pot
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
    del fields, mask, score, holding
    gc.collect()
    orders = freeze_orders(d.days, d.A['codes'], u1, d.A['close'])
    frozen_digest = sha_bytes(orders)
    list_open, got_list = ah.delayed_list(d, u1)
    if got_list != list_counts or er.ambiguous_orders(d, u1):
        raise AssertionError('existing list candidates differ')
    core = [[e for e in row if e[2] > 0 and e[5] != 'list'] for row in u1]
    core_open, got_core = dg.next_open(core, d.A['open'], d.A['low'], d.days)
    core_open, unknown = fe.remove_precision_unknown(core_open, d.days, d.A['codes'])
    unknown = [r for r in unknown if panels.WINDOW[0] <= r[0] <= panels.WINDOW[1]]
    if got_core != core_counts or unknown != old_unknown:
        raise AssertionError('existing core candidates differ')
    _, actual = fn.build_books(list_open, core_open)
    actual_keys = {(d.days[i], str(d.A['codes'][e[1]]), e[5]) for i, row in enumerate(actual) for e in row
                   if panels.WINDOW[0] <= d.days[i] <= panels.WINDOW[1]}
    ci = {str(c): j for j, c in enumerate(d.A['codes'])}
    audits = []
    for order in orders:
        day, j = d.di[order['day']], ci[order['code']]
        audits.append({'day': order['day'], 'code': order['code'], 'kind': order['kind'],
                       **observe(order, d.A['open'][day, j], d.A['low'][day, j])})
    if sha_bytes(orders) != frozen_digest:
        raise AssertionError('next-day classification mutated prior orders')
    accepted_keys = {(r['day'], r['code'], r['kind']) for r in audits if r['status'] == 'old_accepted'}
    if accepted_keys != actual_keys:
        raise AssertionError('existing opening book differs from frozen classifications')
    observed_low = {(r['day'], r['code'], r['kind']) for r in audits
                    if r['status'] == 'old_accepted' and r['low_stop_float32_equal']}
    if observed_low != {(r['day'], r['code'], r['kind']) for r in low_unknown}:
        raise AssertionError('old low precision list differs')
    open_keys = {(r['day'], r['code'], r['kind']) for r in audits if r['open_stop_float32_equal']}
    expected_open = {(r['day'], r['code'], r['kind']) for r in open_unknown}
    if open_keys != expected_open:
        raise AssertionError('old opening precision list differs')
    summaries = {}
    for y in ('2024', '2025', '2026'):
        year_orders = [r for r in orders if r['day'].startswith(y)]
        year_audits = [r for r in audits if r['day'].startswith(y)]
        core_keys = {(r['day'], r['code']) for r in year_orders if r['kind'] != 'list'}
        list_keys = {(r['day'], r['code']) for r in year_orders if r['kind'] == 'list'}
        summaries[y] = {'same_day_cross_kind': len(core_keys & list_keys), 'kinds': {}}
        for kind in ('n1', 'list'):
            subset = [r for r in year_audits if r['kind'] == kind]
            summaries[y]['kinds'][kind] = {'preselected': len(subset),
                'status': dict(Counter(r['status'] for r in subset)),
                'open_stop_float32_equal': sum(r['open_stop_float32_equal'] for r in subset),
                'low_stop_float32_equal': sum(r['low_stop_float32_equal'] for r in subset)}
    out = {'dataset_digest': data_digest, 'gi_sha256': sha(gi_path), 'gu_sha256': sha(gu_path),
           'gz_sha256': sha(gz_path), 'system_sha256': sha(Path(system.__file__)),
           'script_sha256': sha(Path(__file__)), 'preorders_digest': frozen_digest,
           'summary': summaries, 'orders': orders, 'observations': audits}
    target = root / 'strong_continue_hb.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False,
                                 default=json_default) + '\n')
    print('wrote', target, flush=True)


def sha_bytes(value):
    import hashlib
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


if __name__ == '__main__':
    main()
