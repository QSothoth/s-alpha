"""GG: retry documented names only on existing preselected core signals."""
from collections import Counter, defaultdict
from dataclasses import replace
import gc
import json
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trader_replication import panels, system
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_fj as fj
from studies.trader_replication import martin_continue_ft as ft
from studies.trader_replication import martin_continue_gf as gf
from studies.trader_replication.martin_continue_b_check import digest
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import nl_rules

HORIZON = 20


def valid_bar(d, i, j):
    o, h, l, c = (float(d.A[k][i, j]) for k in ('open', 'high', 'low', 'close'))
    return all(np.isfinite(v) and v > 0 for v in (o, h, l, c)) and l <= min(o, c) and h >= max(o, c)


def holding_missing(d, j, trades):
    return [d.days[i] for t in trades for i in range(d.di[t['entry']], d.di[t['exit']] + 1)
            if not valid_bar(d, i, j)]


def run(d, j, entry, candidate_indices, rules, px, ema, ambiguous_hit):
    book = [[] for _ in d.days]
    ambiguous = []
    for i in [entry, *candidate_indices]:
        opening = float(d.A['open'][i, j])
        low = float(d.A['low'][i, j])
        stop = opening * (1 - gf.STOP_PCT)
        hit, unknown = gf.same_day_stop(low, stop, ambiguous_hit)
        if unknown:
            ambiguous.append(d.days[i])
        book[i] = [((1.,), j, 1, opening, stop, 'n1', stop if hit else None)]
    _, _, trades = system.simulate(px, ema, rules, book, d.days[entry], panels.WINDOW[1], audit=True)
    if not trades or trades[0]['entry'] != d.days[entry]:
        raise AssertionError('original entry missing')
    if any(a['exit'] >= b['entry'] for a, b in zip(trades, trades[1:])):
        raise AssertionError('same-day exit and repurchase')
    trace = ft.trace_orders(d, book, rules, digest(trades))
    held_missing = holding_missing(d, j, trades)
    status = 'holding_data_unknown' if held_missing else ('end_unclosed' if any(t['why'] == 'end' for t in trades) else 'closed')
    return {'status': status, 'trades': trades, 'sum_pnl': sum(t['pnl'] for t in trades) if status == 'closed' else None,
            'additional_entries': len(trades) - 1, 'ambiguous_order_days': ambiguous,
            'holding_missing_days': held_missing, 'order_trace': trace['orders']}


def report(rows, name):
    status = Counter(r['scenarios'][name]['status'] for r in rows)
    valid = [r for r in rows if r['baseline_status'] == 'closed' and r['scenarios'][name]['status'] == 'closed']
    changes = [r['scenarios'][name]['sum_pnl'] - r['baseline']['pnl'] for r in valid]
    return {'events': len(rows), 'scenario_status': dict(status), 'paired_closed': len(valid),
            'paired_positive': sum(x > 1e-12 for x in changes),
            'paired_negative': sum(x < -1e-12 for x in changes),
            'paired_equal': sum(abs(x) <= 1e-12 for x in changes),
            'paired_mean_delta': float(np.mean(changes)) if changes else None,
            'paired_median_delta': float(np.median(changes)) if changes else None,
            'additional_entries': sum(r['scenarios'][name].get('additional_entries', 0) for r in valid),
            'events_with_reentry': sum(r['scenarios'][name].get('additional_entries', 0) > 0 for r in valid)}


def main():
    gf_path, fj_path = du.REPORTS / 'strong_continue_gf.json', du.REPORTS / 'strong_continue_fj.json'
    ref, candidates = json.loads(gf_path.read_text()), json.loads(fj_path.read_text())
    if (ref['script_sha256'] != sha(Path(gf.__file__)) or candidates['script_sha256'] != sha(Path(fj.__file__))
            or ref['system_sha256'] != sha(Path(system.__file__))):
        raise ValueError('source differs')
    dataset = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if dataset.digest() != ref['dataset_digest'] or dataset.digest() != candidates['dataset_digest']:
        raise ValueError('dataset differs')
    selected = defaultdict(list)
    seen = set()
    for c in candidates['rows']:
        if c['selected']:
            key = c['entry_day'], c['code']
            if key in seen:
                raise ValueError('duplicate preselected order')
            seen.add(key)
            selected[c['code']].append((c['signal_day'], c['entry_day']))
    del candidates
    gc.collect()
    if len(ref['rows']) != 74:
        raise ValueError('GF event count differs')
    d = du.make_data(dataset)
    rules = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True, no_rebuy_day=True)
    rules = replace(rules, intraday_kinds=tuple(sorted(set(rules.intraday_kinds) | {'n1'})))
    del d.fp, d.fwd, d.raw
    for key in ('pr21', 'pr63', 'pr126', 'rank_pool', 'stack', 'tight'):
        d.A.pop(key, None)
    d.rk = d.rk.astype(np.int32)
    gc.collect()
    px, ema = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules)
    codes = {str(code): i for i, code in enumerate(d.A['codes'])}
    rows = []
    end_index = d.di[panels.WINDOW[1]]
    for ref_row in ref['rows']:
        code = 'US.' + ref_row['ticker']
        j = codes[code]
        first = d.di[ref_row['models']['stop25_hit']['entry']]
        baseline = run(d, j, first, [], rules, px, ema, True)
        if len(baseline['trades']) != 1 or baseline['trades'][0] != ref_row['models']['stop25_hit']:
            raise AssertionError('GF baseline differs')
        row = {'ticker': ref_row['ticker'], 'signal_day': ref_row['signal_day'], 'originals': ref_row['originals'],
               'baseline': baseline['trades'][0], 'baseline_status': baseline['status'], 'scenarios': {}}
        if first + HORIZON > end_index:
            row['candidate_days'] = []
            row['scenarios'] = {s: {'status': 'unmatured_entry_window'} for s in ('hit', 'nohit')}
        else:
            indices = []
            for sig_day, open_day in selected[code]:
                i = d.di[open_day]
                if first < i <= first + HORIZON:
                    if d.days[i - 1] != sig_day:
                        raise AssertionError('signal not before opening')
                    indices.append(i)
            indices.sort()
            if len(indices) != len(set(indices)):
                raise AssertionError('duplicate candidate day')
            row['candidate_days'] = [d.days[i] for i in indices]
            bad = [d.days[i] for i in indices if not valid_bar(d, i, j)]
            if bad:
                row['scenarios'] = {s: {'status': 'order_data_unknown', 'missing_days': bad} for s in ('hit', 'nohit')}
            elif not indices:
                row['scenarios'] = {s: baseline for s in ('hit', 'nohit')}
            else:
                row['scenarios'] = {'hit': run(d, j, first, indices, rules, px, ema, True),
                                    'nohit': run(d, j, first, indices, rules, px, ema, False)}
        rows.append(row)
    groups = defaultdict(list)
    for row in rows:
        precisions = {t['precision'] for t in row['originals']}
        if len(precisions) != 1:
            raise ValueError('duplicate precision differs')
        groups[(row['signal_day'][:4], precisions.pop())].append(row)
    def results(sample):
        return {'events': len(sample), 'events_with_presignal': sum(bool(r['candidate_days']) for r in sample),
                'presignals': sum(len(r['candidate_days']) for r in sample),
                'scenarios': {name: report(sample, name) for name in ('hit', 'nohit')}}
    out = {'dataset_digest': dataset.digest(), 'gf_sha256': sha(gf_path), 'fj_sha256': sha(fj_path),
           'system_sha256': sha(Path(system.__file__)), 'script_sha256': sha(Path(__file__)),
           'horizon': HORIZON, 'all': results(rows),
           'groups': {y + ':' + p: results(group) for (y, p), group in sorted(groups.items())}, 'rows': rows}
    target = du.REPORTS / 'strong_continue_gg.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False,
                                 default=json_default) + '\n')
    print('wrote', target, 'events', len(rows), flush=True)


if __name__ == '__main__':
    main()
