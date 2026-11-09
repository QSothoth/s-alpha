"""ER: next-open execution sensitivity for the two precision-corrected accounts."""
from dataclasses import replace
import gc
import json
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trader_replication import martin_continue_ah as ah
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ef as ef
from studies.trader_replication import martin_continue_ep as ep
from studies.trader_replication import panels
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import f1_rules, nl_rules


def ambiguous_orders(d, book):
    rows = []
    for day in range(1, len(book)):
        if not panels.WINDOW[0] <= d.days[day] <= panels.WINDOW[1]:
            continue
        selected = sorted((e for e in book[day - 1] if e[5] == 'list'), key=lambda e: e[0])[:6]
        for e in selected:
            j, stop = e[1], e[4]
            opening = d.A['open'][day, j]
            if np.isfinite(opening) and opening > stop > 0 and np.float32(opening) == np.float32(stop):
                rows.append({'signal_day': d.days[day - 1], 'day': d.days[day], 'code': str(d.A['codes'][j]),
                             'opening': float(opening), 'stop': float(stop)})
    return rows


def main():
    cc_path, ep_path = du.REPORTS / 'strong_continue_cc.json', du.REPORTS / 'strong_continue_ep_full.json'
    cc, ref = json.loads(cc_path.read_text()), json.loads(ep_path.read_text())
    if ref['script_sha256'] != sha(Path(ep.__file__)) or not ref['original_peer_replayed']:
        raise ValueError('EP source differs')
    digest, old_counts = ref['dataset_digest'], cc['candidate_counts']
    expected_old = cc['results']['AH1_fixed']['metrics']
    expected = {name: {'keys': ref['results'][name + '_raw_adr']['trade_keys'],
                       'by_year': ref['results'][name + '_raw_adr']['metrics']['by_year'],
                       'entries': ref['results'][name + '_raw_adr']['metrics']['entries_by_year']}
                for name in ('U1', 'SAT6')}
    del cc, ref
    gc.collect()
    dataset = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if dataset.digest() != digest:
        raise ValueError('v1 dataset differs')
    d = du.make_data(dataset)
    fields, mask, _ = du.compute_fields(d)
    old_u1, _ = ef.books(d, fields, mask)
    old_open, old_actual_counts = ah.delayed_list(d, old_u1)
    if old_actual_counts != old_counts:
        raise AssertionError('CC candidate counts differ')
    del old_u1
    original_eligible = ep.original_eligibility(d)
    replay, old_pot = ep.peer_potential(d, original_eligible)
    for i in range(len(d.days)):
        if not np.array_equal(replay[i], fields['peer_pot'][i], equal_nan=True):
            raise AssertionError('original peer_pot mismatch ' + d.days[i])
    del replay, old_pot, original_eligible
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
    u1, sat = ef.books(d, fields, mask)
    u1_open, u1_counts = ah.delayed_list(d, u1)
    sat_open, sat_counts = ah.delayed_list(d, sat)
    unknown = {'U1': ambiguous_orders(d, u1), 'SAT6': ambiguous_orders(d, sat)}
    for old, new in zip(u1, u1_open):
        if [e for e in old if e[5] != 'list'] != [e for e in new if e[5] != 'list']:
            raise AssertionError('core or short order changed')
    del fields, mask
    gc.collect()
    lever, unlevered = f1_rules(d, 6, (1, 3)), nl_rules(d, 6)
    if 'list' in lever.intraday_kinds or 'list' in unlevered.intraday_kinds:
        raise ValueError('registered list execution timing changed')
    lever_open = replace(lever, intraday_kinds=tuple(lever.intraday_kinds) + ('list',))
    unlevered_open = replace(unlevered, intraday_kinds=tuple(unlevered.intraday_kinds) + ('list',))
    cases = [('AH1_original_fixed', old_open, lever_open), ('U1', u1, lever), ('U1_open', u1_open, lever_open),
             ('SAT6', sat, unlevered), ('SAT6_open', sat_open, unlevered_open)]
    result = {}
    for name, book, rules in cases:
        print('account', name, flush=True)
        result[name] = ef.account(d, book, rules)
    for year in ('2024', '2025', '2026'):
        z = result['AH1_original_fixed']['metrics']
        if abs(z['by_year'][year] - expected_old['by_year'][year]) > 1e-10 or z['entries_by_year'][year] != expected_old['entries_by_year'][year]:
            raise AssertionError('CC baseline differs ' + year)
        for name in ('U1', 'SAT6'):
            z = result[name]['metrics']
            if (abs(z['by_year'][year] - expected[name]['by_year'][year]) > 1e-10 or
                    z['entries_by_year'][year] != expected[name]['entries'][year]):
                raise AssertionError('EP baseline differs ' + name + ' ' + year)
    for name in ('U1', 'SAT6'):
        if result[name]['trade_keys'] != expected[name]['keys']:
            raise AssertionError('EP trade identities differ ' + name)
    out = {'dataset_digest': digest, 'cc_sha256': sha(cc_path), 'ep_sha256': sha(ep_path),
           'script_sha256': sha(Path(__file__)), 'original_counts': old_actual_counts,
           'candidate_counts': {'U1': u1_counts, 'SAT6': sat_counts}, 'precision_unknown': unknown,
           'results': result, 'trade_differences': {name: ef.differences(result[name]['trade_keys'], result[name + '_open']['trade_keys'])
                                                     for name in ('U1', 'SAT6')}}
    target = du.REPORTS / 'strong_continue_er.json'
    with target.open('w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        f.write('\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
