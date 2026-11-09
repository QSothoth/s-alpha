"""GE: decompose forced-trade risk denominators and observed price space."""
from collections import Counter, defaultdict
from itertools import groupby
import json
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trader_replication import panels
from studies.trader_replication import martin_continue_fl as fl
from studies.trader_replication import martin_continue_gc as gc_module
from studies.trader_replication import martin_continue_gd as gd
from studies.trader_replication.martin_continue_du import REPORTS
from studies.trader_replication.martin_continue_dq import sha

COST, HORIZON = .0005, 20


def post_exit_event(high, start, target):
    """Did a clear daily high reach target during the next 20 sessions?"""
    missing = precision = False
    window = high[start:start + HORIZON]
    for value in window:
        v = float(value)
        if not np.isfinite(v) or v <= 0:
            missing = True
        elif np.float32(v) == np.float32(target):
            precision = True
        elif v > target:
            return True, 'observed'
    if missing:
        return None, 'missing_high'
    if precision:
        return None, 'target_precision'
    if len(window) < HORIZON:
        return None, 'unmatured'
    return False, 'not_reached'


def describe(rows):
    closed = [r for r in rows if r['status'] == 'closed']
    winners = [r for r in closed if r['model']['ret'] > 0]
    captured = [r['capture'] for r in winners if r['capture'] is not None]
    result = {'events': len(rows), 'closed': len(closed), 'end_unclosed': len(rows) - len(closed),
              'exit_reasons': dict(Counter(r['model']['why'] for r in closed)),
              'winning_closed': len(winners), 'capture_known': len(captured),
              'capture_unknown': len(winners) - len(captured)}
    for key in ('width', 'overnight_component', 'prior_intraday_component'):
        values = [r[key] for r in closed]
        result['median_' + key] = float(np.median(values)) if values else None
    for key in ('upper', 'realized', 'capture'):
        values = [r[key] for r in captured]
        result['median_winner_' + key] = float(np.median(values)) if values else None
        result['mean_winner_' + key] = float(np.mean(values)) if values else None
    for metric in ('after30', 'after5r'):
        result[metric] = {'hit': sum(r[metric] is True for r in closed),
                          'not_hit': sum(r[metric] is False for r in closed),
                          'unknown': sum(r[metric] is None for r in closed),
                          'reasons': dict(Counter(r[metric + '_reason'] for r in closed))}
    return result


def main():
    gd_path = REPORTS / 'strong_continue_gd.json'
    ref = json.loads(gd_path.read_text())
    if ref['script_sha256'] != sha(Path(gd.__file__)) or ref['ledger_sha256'] != sha(gd.LEDGER):
        raise ValueError('GD source or ledger differs')
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if ds.digest() != ref['dataset_digest']:
        raise ValueError('dataset differs')
    unique = {}
    for row in ref['rows']:
        t = row['ledger']
        if row['model'] is None:
            continue
        key = t['ticker'], t['entry_date']
        if key in unique:
            if unique[key]['model'] != row['model']:
                raise AssertionError('duplicate event differs')
            unique[key]['originals'].append(t)
        else:
            unique[key] = {'ticker': t['ticker'], 'signal_day': t['entry_date'], 'status': row['status'],
                           'model': row['model'], 'originals': [t]}
    stocks = {s['code'] for s in ds.stocks()}
    days = sorted({day for code, day, _ in ds.rows() if code in stocks and day <= panels.WINDOW[1]})
    index = {day: i for i, day in enumerate(days)}
    by_code = defaultdict(list)
    for row in unique.values():
        by_code['US.' + row['ticker']].append(row)
    actions, seen = ds.actions(), set()
    for code, group in groupby(ds.rows(), key=lambda r: r[0]):
        if code not in by_code:
            continue
        seen.add(code)
        records = [(day, values) for _, day, values in group if day <= panels.WINDOW[1]]
        op, high, low, close = gc_module.adjusted_arrays(index, days, records, actions.get(code, []))
        for row in by_code[code]:
            model = row['model']
            signal, entry, exit_day = (index[s] for s in (row['signal_day'], model['entry'], model['exit']))
            if entry != signal + 1 or float(op[entry]) != model['fill'] or float(low[signal]) != model['stop']:
                raise AssertionError('GD entry or stop differs')
            for execution in model['executions']:
                k, price = index[execution['time']], execution['price']
                if not (np.isfinite(low[k]) and np.isfinite(high[k]) and
                        float(low[k]) - 1e-5 <= price <= float(high[k]) + 1e-5):
                    raise AssertionError('execution outside recorded daily bar')
            if model['executions'][-1]['time'] != model['exit']:
                raise AssertionError('exit date differs')
            signal_close = float(close[signal])
            if not np.isfinite(signal_close) or signal_close <= 0:
                raise ValueError('invalid signal close')
            fill, stop = model['fill'], model['stop']
            row['width'] = (fill - stop) / fill
            row['overnight_component'] = (fill - signal_close) / fill
            row['prior_intraday_component'] = (signal_close - stop) / fill
            if abs(row['width'] - row['overnight_component'] - row['prior_intraday_component']) > 1e-12:
                raise AssertionError('risk width decomposition differs')
            if abs(model['r'] - model['ret'] / row['width']) > 1e-8:
                raise AssertionError('model R differs from net return / initial width')
            row['capture'] = None
            if row['status'] == 'closed' and model['ret'] > 0:
                row['capture'] = fl.winner_capture(model, high, entry, exit_day, COST, COST)
            if row['status'] == 'closed':
                targets = {'after30': fill * (1 + COST) * 1.30 / (1 - COST),
                           'after5r': (fill * (1 + COST) + 5 * (fill - stop)) / (1 - COST)}
                for metric, target in targets.items():
                    row[metric], row[metric + '_reason'] = post_exit_event(high, exit_day + 1, target)
            row['reported_stop_views'] = [{'id': t['id'], 'original_stop_pct': t['stop_pct'],
                                            'original_r': t['r_multiple'],
                                            'same_return_over_reported_stop': model['ret'] / (t['stop_pct'] / 100)}
                                           for t in row['originals'] if t['stop_pct'] is not None and t['stop_pct'] > 0
                                           and row['status'] == 'closed']
    if seen != set(by_code):
        raise ValueError('missing symbols')
    rows = sorted(unique.values(), key=lambda r: (r['signal_day'], r['ticker']))
    groups = defaultdict(list)
    for row in rows:
        precisions = {t['precision'] for t in row['originals']}
        if len(precisions) != 1:
            raise ValueError('duplicate precision differs')
        groups[(row['signal_day'][:4], precisions.pop())].append(row)
    out = {'dataset_digest': ds.digest(), 'gd_sha256': sha(gd_path), 'script_sha256': sha(Path(__file__)),
           'all': describe(rows),
           'groups': {year + ':' + precision: describe(group) for (year, precision), group in sorted(groups.items())},
           'rows': rows}
    target = REPORTS / 'strong_continue_ge.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    print('wrote', target, 'events', len(rows), flush=True)


if __name__ == '__main__':
    main()
