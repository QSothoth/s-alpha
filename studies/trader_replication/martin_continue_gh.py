"""GH: compare core-only and core-plus-H3 preselected reentry signals."""
from collections import defaultdict
from dataclasses import replace
import gc
import json
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trader_replication import panels, system
from studies.trader_replication import martin_continue_ah as ah
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ep as ep
from studies.trader_replication import martin_continue_er as er
from studies.trader_replication import martin_continue_fj as fj
from studies.trader_replication import martin_continue_ft as ft
from studies.trader_replication import martin_continue_gg as gg
from studies.trader_replication.martin_continue_bv import daily_name_score
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import HOLD, hold_sim, nl_rules, u1_entries


def preselected_list(d, book):
    result = defaultdict(list)
    seen = set()
    for day in range(len(book) - 1):
        for e in sorted((e for e in book[day] if e[5] == 'list'), key=lambda e: e[0])[:6]:
            code, opening_day = str(d.A['codes'][e[1]]), d.days[day + 1]
            key = opening_day, code
            if key in seen:
                raise ValueError('duplicate list preselection')
            seen.add(key)
            result[code].append((d.days[day], opening_day))
    return result


def comparison(rows, name):
    status = defaultdict(int)
    paired = []
    for row in rows:
        current = row['union'][name]
        status[current['status']] += 1
        core = row['core'][name]
        if core['status'] == current['status'] == 'closed':
            paired.append((row, core, current))
    delta = [current['sum_pnl'] - core['sum_pnl'] for _, core, current in paired]
    new_entries = 0
    for row, _, current in paired:
        only = set(row['list_only_days'])
        new_entries += sum(t['entry'] in only for t in current['trades'][1:])
    return {'status': dict(status), 'paired_closed': len(paired),
            'up': sum(v > 1e-12 for v in delta), 'down': sum(v < -1e-12 for v in delta),
            'equal': sum(abs(v) <= 1e-12 for v in delta),
            'mean_delta': float(np.mean(delta)) if delta else None,
            'median_delta': float(np.median(delta)) if delta else None,
            'core_additional_entries': sum(core['additional_entries'] for _, core, _ in paired),
            'union_additional_entries': sum(current['additional_entries'] for _, _, current in paired),
            'union_list_only_entries': new_entries}


def main():
    root = du.REPORTS
    gg_path, fj_path, ft_path = (root / 'strong_continue_gg.json', root / 'strong_continue_fj.json',
                                 root / 'strong_continue_ft.json')
    saved, core_ref, ft_ref = (json.loads(p.read_text()) for p in (gg_path, fj_path, ft_path))
    if (saved['script_sha256'] != sha(Path(gg.__file__)) or core_ref['script_sha256'] != sha(Path(fj.__file__))
            or ft_ref['script_sha256'] != sha(Path(ft.__file__)) or saved['system_sha256'] != sha(Path(system.__file__))
            or ft_ref['system_sha256'] != sha(Path(system.__file__))):
        raise ValueError('source differs')
    dataset = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    dataset_digest = dataset.digest()
    if any(x['dataset_digest'] != dataset_digest for x in (saved, core_ref, ft_ref)):
        raise ValueError('dataset differs')
    core = defaultdict(list)
    for r in core_ref['rows']:
        if r['selected']:
            core[r['code']].append((r['signal_day'], r['entry_day']))
    del core_ref
    expected_list_counts = ft_ref['list_counts']
    expected_list_keys = {(r['day'], r['code']) for r in ft_ref['traces']['FT1']['orders'] if r['kind'] == 'list'}
    del ft_ref
    gc.collect()
    d = du.make_data(dataset)
    fields, mask, unused_holding = du.compute_fields(d)
    del unused_holding
    gc.collect()
    original = ep.original_eligibility(d)
    replay, old_pot = ep.peer_potential(d, original)
    for i, day in enumerate(d.days):
        if not np.array_equal(replay[i], fields['peer_pot'][i], equal_nan=True):
            raise AssertionError('original peer_pot differs ' + day)
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
    book = u1_entries(d, fields, holding, score)
    raw_list = preselected_list(d, book)
    delayed, actual_counts = ah.delayed_list(d, book)
    if actual_counts != expected_list_counts or er.ambiguous_orders(d, book):
        raise AssertionError('FT list counts or precision differ')
    actual_list_keys = {(d.days[i], str(d.A['codes'][e[1]])) for i, entries in enumerate(delayed)
                        if panels.WINDOW[0] <= d.days[i] <= panels.WINDOW[1] for e in entries if e[5] == 'list'}
    if actual_list_keys != expected_list_keys:
        raise AssertionError('FT list candidate keys differ')
    del fields, mask, score, holding, book, delayed
    gc.collect()
    rules = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True, no_rebuy_day=True)
    rules = replace(rules, intraday_kinds=tuple(sorted(set(rules.intraday_kinds) | {'n1'})))
    px, ema = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules)
    codes = {str(code): i for i, code in enumerate(d.A['codes'])}
    end = d.di[panels.WINDOW[1]]
    rows = []
    for old in saved['rows']:
        code, first = 'US.' + old['ticker'], d.di[old['baseline']['entry']]
        row = {'ticker': old['ticker'], 'signal_day': old['signal_day'], 'originals': old['originals'],
               'core': old['scenarios'], 'union': {}}
        if first + gg.HORIZON > end:
            if old['scenarios']['hit']['status'] != 'unmatured_entry_window':
                raise AssertionError('GG maturity differs')
            row['core_days'], row['list_days'], row['overlap_days'], row['list_only_days'] = [], [], [], []
            row['union'] = {s: {'status': 'unmatured_entry_window'} for s in ('hit', 'nohit')}
        else:
            core_days = {opening for signal, opening in core[code]
                         if first < d.di[opening] <= first + gg.HORIZON and d.days[d.di[opening] - 1] == signal}
            list_days = {opening for signal, opening in raw_list[code]
                         if first < d.di[opening] <= first + gg.HORIZON and d.days[d.di[opening] - 1] == signal}
            if sorted(core_days) != old['candidate_days']:
                raise AssertionError('GG core candidates differ')
            row['core_days'], row['list_days'] = sorted(core_days), sorted(list_days)
            row['overlap_days'], row['list_only_days'] = sorted(core_days & list_days), sorted(list_days - core_days)
            union = sorted(d.di[day] for day in core_days | list_days)
            bad = [d.days[i] for i in union if not gg.valid_bar(d, i, codes[code])]
            for s, hit in (('hit', True), ('nohit', False)):
                core_again = gg.run(d, codes[code], first, [d.di[k] for k in row['core_days']], rules, px, ema, hit)
                if core_again != old['scenarios'][s]:
                    raise AssertionError('GG core path differs ' + code + ' ' + s)
                if bad:
                    row['union'][s] = {'status': 'order_data_unknown', 'missing_days': bad}
                elif not row['list_only_days']:
                    row['union'][s] = core_again
                else:
                    row['union'][s] = gg.run(d, codes[code], first, union, rules, px, ema, hit)
        rows.append(row)
    groups = defaultdict(list)
    for row in rows:
        precisions = {t['precision'] for t in row['originals']}
        if len(precisions) != 1:
            raise ValueError('duplicate precision differs')
        groups[(row['signal_day'][:4], precisions.pop())].append(row)
    def result(sample):
        return {'events': len(sample), 'core_orders': sum(len(r['core_days']) for r in sample),
                'list_orders': sum(len(r['list_days']) for r in sample),
                'overlap_orders': sum(len(r['overlap_days']) for r in sample),
                'list_only_orders': sum(len(r['list_only_days']) for r in sample),
                'events_with_list_only': sum(bool(r['list_only_days']) for r in sample),
                'scenarios': {name: comparison(sample, name) for name in ('hit', 'nohit')}}
    out = {'dataset_digest': dataset_digest, 'gg_sha256': sha(gg_path), 'fj_sha256': sha(fj_path),
           'ft_sha256': sha(ft_path), 'system_sha256': sha(Path(system.__file__)),
           'script_sha256': sha(Path(__file__)), 'list_counts': actual_counts,
           'ft_list_keys': len(actual_list_keys), 'all': result(rows),
           'groups': {y + ':' + p: result(group) for (y, p), group in sorted(groups.items())}, 'rows': rows}
    target = root / 'strong_continue_gh.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False,
                                 default=json_default) + '\n')
    print('wrote', target, 'events', len(rows), flush=True)


if __name__ == '__main__':
    main()
