"""GF: matched forced-entry simulations with a fixed 2.5% initial stop."""
from collections import Counter, defaultdict
from dataclasses import replace
import gc
import json
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trader_replication import panels, system
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_fc as fc
from studies.trader_replication import martin_continue_gd as gd
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import nl_rules

STOP_PCT = .025


def same_day_stop(low, stop, ambiguous_hit):
    if not np.isfinite(low) or low <= 0 or not np.isfinite(stop) or stop <= 0:
        raise ValueError('invalid daily stop data')
    ambiguous = np.float32(low) == np.float32(stop)
    return (ambiguous_hit if ambiguous else low < stop), bool(ambiguous)


def summary(rows, scenario):
    models = [r['models'][scenario] for r in rows]
    closed = [t for t in models if t['why'] != 'end']
    return {'events': len(models), 'closed': len(closed), 'end_unclosed': len(models) - len(closed),
            'exit_reasons': dict(Counter(t['why'] for t in closed)),
            'win': sum(t['r'] > 0 for t in closed), 'loss_or_flat': sum(t['r'] <= 0 for t in closed),
            'ge5r': sum(t['r'] >= 5 for t in closed), 'ge10r': sum(t['r'] >= 10 for t in closed),
            'median_ret': float(np.median([t['ret'] for t in closed])) if closed else None,
            'median_r': float(np.median([t['r'] for t in closed])) if closed else None,
            'median_initial_risk': float(np.median([t['risk_pct'] for t in closed])) if closed else None}


def paired(rows, scenario):
    pairs = [(r['models']['original'], r['models'][scenario]) for r in rows
             if r['models']['original']['why'] != 'end' and r['models'][scenario]['why'] != 'end']
    return {'both_closed': len(pairs),
            'positive_to_negative': sum(a['r'] > 0 and b['r'] <= 0 for a, b in pairs),
            'negative_to_positive': sum(a['r'] <= 0 and b['r'] > 0 for a, b in pairs),
            'return_delta_median': float(np.median([b['ret'] - a['ret'] for a, b in pairs])) if pairs else None,
            'return_delta_mean': float(np.mean([b['ret'] - a['ret'] for a, b in pairs])) if pairs else None,
            'return_up': sum(b['ret'] > a['ret'] for a, b in pairs),
            'return_down': sum(b['ret'] < a['ret'] for a, b in pairs),
            'return_equal': sum(b['ret'] == a['ret'] for a, b in pairs)}


def main():
    reference = du.REPORTS / 'strong_continue_gd.json'
    ref = json.loads(reference.read_text())
    if (ref['script_sha256'] != sha(Path(gd.__file__)) or ref['ledger_sha256'] != sha(gd.LEDGER) or
            ref['system_sha256'] != sha(Path(system.__file__))):
        raise ValueError('GD source, ledger, or engine differs')
    dataset = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if dataset.digest() != ref['dataset_digest']:
        raise ValueError('dataset differs')
    unique = {}
    for row in ref['rows']:
        if row['model'] is None:
            continue
        t = row['ledger']
        key = t['ticker'], t['entry_date']
        if key in unique:
            if unique[key]['original'] != row['model']:
                raise AssertionError('duplicate baseline differs')
            unique[key]['originals'].append(t)
        else:
            unique[key] = {'ticker': t['ticker'], 'signal_day': t['entry_date'],
                           'original': row['model'], 'originals': [t]}
    if len(unique) != 74:
        raise AssertionError('GD opened-event count differs')
    d = du.make_data(dataset)
    rules = replace(nl_rules(d, 6), gross_cost=True, trail_next_open=True)
    rules = replace(rules, intraday_kinds=tuple(sorted(set(rules.intraday_kinds) | {'n1'})))
    del d.fp, d.fwd, d.raw
    for key in ('pr21', 'pr63', 'pr126', 'rank_pool', 'stack', 'tight'):
        d.A.pop(key, None)
    d.rk = d.rk.astype(np.int32)
    gc.collect()
    px, ema = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules)
    codes = {str(code): i for i, code in enumerate(d.A['codes'])}
    rows = []
    for row in sorted(unique.values(), key=lambda r: (r['signal_day'], r['ticker'])):
        j = codes['US.' + row['ticker']]
        signal = d.di[row['signal_day']]
        entry = signal + 1
        opening, low, prior_stop = (float(d.A[k][i, j]) for k, i in
                                    (('open', entry), ('low', entry), ('low', signal)))
        original_state = gd.order_state(opening, low, prior_stop)
        if original_state not in ('day0_stop', 'fillable'):
            raise AssertionError('GD order not reproducible')
        new_stop = opening * (1 - STOP_PCT)
        hit, unknown = same_day_stop(low, new_stop, True)
        nohit, unknown_again = same_day_stop(low, new_stop, False)
        if unknown != unknown_again:
            raise AssertionError('precision status differs')
        models = {}
        cases = (('original', prior_stop, original_state == 'day0_stop'),
                 ('stop25_hit', new_stop, hit), ('stop25_nohit', new_stop, nohit))
        for name, stop, stopped in cases:
            book = [[] for _ in d.days]
            book[entry] = [((1.,), j, 1, opening, stop, 'n1', stop if stopped else None)]
            _, _, trades = system.simulate(px, ema, rules, book, d.days[entry], panels.WINDOW[1], audit=True)
            if len(trades) != 1:
                raise AssertionError('expected one isolated trade')
            model = trades[0]
            if model['entry'] != d.days[entry] or model['fill'] != opening or model['stop'] != stop:
                raise AssertionError('entry or stop differs')
            if stopped and model['why'] != 'stop_day0':
                raise AssertionError('same-day stop differs')
            fc.signal_audit(d, trades)
            if name == 'original' and model != row['original']:
                raise AssertionError('GD baseline trade differs')
            models[name] = model
        rows.append({'ticker': row['ticker'], 'signal_day': row['signal_day'], 'originals': row['originals'],
                     'precision_unknown_day0': unknown, 'models': models})
    groups = defaultdict(list)
    for row in rows:
        precisions = {t['precision'] for t in row['originals']}
        if len(precisions) != 1:
            raise ValueError('duplicate precision differs')
        groups[(row['signal_day'][:4], precisions.pop())].append(row)
    scenarios = ('original', 'stop25_hit', 'stop25_nohit')
    def report(sample):
        return {'scenarios': {s: summary(sample, s) for s in scenarios},
                'paired': {s: paired(sample, s) for s in scenarios[1:]},
                'precision_unknown_day0': sum(r['precision_unknown_day0'] for r in sample)}
    lookup = {(r['ticker'], r['signal_day']): r for r in rows}
    disclosed = []
    for original in ref['disclosed_r']:
        trade = original['ledger']
        pair = lookup.get((trade['ticker'], trade['entry_date']))
        disclosed.append({'ledger': trade, 'gd_status': original['status'],
                          'scenario_status': 'evaluated' if pair else 'not_evaluated',
                          'models': pair['models'] if pair else None})
    out = {'dataset_digest': dataset.digest(), 'gd_sha256': sha(reference), 'system_sha256': sha(Path(system.__file__)),
           'script_sha256': sha(Path(__file__)), 'stop_pct': STOP_PCT,
           'all': report(rows),
           'groups': {year + ':' + precision: report(group) for (year, precision), group in sorted(groups.items())},
           'disclosed_r': disclosed, 'rows': rows}
    target = du.REPORTS / 'strong_continue_gf.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False,
                                 default=json_default) + '\n')
    print('wrote', target, 'events', len(rows), flush=True)


if __name__ == '__main__':
    main()
