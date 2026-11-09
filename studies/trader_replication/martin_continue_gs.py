"""GS: independent opening versus prior-high-stop entry opportunity bounds."""
from collections import Counter, defaultdict
from itertools import groupby
import json
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trader_replication import panels
from studies.trader_replication import martin_continue_fj as fj
from studies.trader_replication import martin_continue_gc as gc
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_continue_du import REPORTS


def valid_bar(o, h, l, c):
    return all(np.isfinite(v) and v > 0 for v in (o, h, l, c)) and l <= min(o, c) and h >= max(o, c)


def same_price(a, b):
    return np.float32(a) == np.float32(b)


def target_bounds(arrays, entry, stop, fill, target, intraday):
    """Bounds for a single independent order, with no assumptions about ambiguous daily sequencing."""
    o, h, l, c = arrays
    lo = hi = None
    first_ambiguous = False
    for d in range(entry, min(entry + fj.HORIZON, len(o))):
        opening, high, low, close = map(float, (o[d], h[d], l[d], c[d]))
        if not valid_bar(opening, high, low, close):
            return lo, hi, 'invalid_bar', first_ambiguous
        if d > entry:
            if same_price(opening, stop) or same_price(opening, target):
                return lo, hi, 'open_precision', first_ambiguous
            if opening < stop:
                return False if lo is None else lo, False if hi is None else hi, 'gap_stop', first_ambiguous
            if opening > target:
                return True if lo is None else lo, True if hi is None else hi, 'gap_target', first_ambiguous
        if same_price(low, stop) or same_price(high, target):
            return lo, hi, 'intraday_precision', first_ambiguous
        stopped, reached = low < stop, high > target
        if d == entry and intraday and stopped:
            first_ambiguous = True
            lo = False
            if reached:
                return False, True, 'entry_order_unknown', first_ambiguous
            continue
        if stopped and reached:
            return False if lo is None else lo, True if hi is None else hi, 'same_day_both', first_ambiguous
        if stopped:
            return False if lo is None else lo, False if hi is None else hi, 'stop', first_ambiguous
        if reached:
            return True if lo is None else lo, True if hi is None else hi, 'target', first_ambiguous
    if min(entry + fj.HORIZON, len(o)) - entry == fj.HORIZON:
        return False if lo is None else lo, False if hi is None else hi, 'horizon', first_ambiguous
    return lo, hi, 'end_unmatured', first_ambiguous


def opportunity(arrays, entry, stop, mode):
    o, h, l, c = arrays
    opening, high, low, close = map(float, (o[entry], h[entry], l[entry], c[entry]))
    unknown = {'status': 'unknown', 'fill': None, 'width': None, 'outcomes': {}}
    if not valid_bar(opening, high, low, close) or not np.isfinite(stop) or stop <= 0:
        return {**unknown, 'reason': 'invalid_open_bar_or_stop'}
    intraday = False
    if mode == 'open':
        if same_price(opening, stop):
            return {**unknown, 'reason': 'open_stop_precision'}
        if opening < stop:
            return {'status': 'cancel', 'reason': 'open_below_stop', 'fill': None, 'width': None, 'outcomes': {}}
        fill = opening
    elif mode == 'break':
        trigger = float(h[entry - 1])
        if not np.isfinite(trigger) or trigger <= 0 or trigger <= stop or same_price(trigger, stop):
            return {**unknown, 'reason': 'invalid_trigger_or_stop'}
        if same_price(opening, trigger):
            return {**unknown, 'reason': 'open_trigger_precision'}
        if opening > trigger:
            fill = opening
        else:
            if same_price(high, trigger):
                return {**unknown, 'reason': 'high_trigger_precision'}
            if high < trigger:
                return {'status': 'not_triggered', 'reason': 'high_below_trigger', 'fill': None, 'width': None,
                        'outcomes': {}}
            fill, intraday = trigger, True
        if same_price(fill, stop) or fill < stop:
            return {**unknown, 'reason': 'fill_stop_precision_or_invalid'}
    else:
        raise ValueError('unknown order mode')
    net_risk = fill * (1 + fj.COST) - stop * (1 - fj.COST)
    target5 = (fill * (1 + fj.COST) + 5 * net_risk) / (1 - fj.COST)
    target30 = fill * (1 + fj.COST) * 1.30 / (1 - fj.COST)
    outcomes = {}
    for name, target in (('hit5', target5), ('hit30', target30)):
        lower, upper, reason, first_ambiguous = target_bounds(arrays, entry, stop, fill, target, intraday)
        outcomes[name] = {'lower': lower, 'upper': upper, 'reason': reason,
                          'entry_order_unknown': first_ambiguous}
    return {'status': 'filled', 'reason': 'intraday_trigger' if intraday else 'opening',
            'fill': fill, 'width': (fill - stop) / fill, 'outcomes': outcomes}


def bounds_summary(rows, mode):
    samples = [row[mode] for row in rows]
    out = {'orders': len(samples), 'status': dict(Counter(x['status'] for x in samples)),
           'reasons': dict(Counter(x['reason'] for x in samples))}
    widths = [x['width'] for x in samples if x['width'] is not None]
    out['median_width'] = float(np.median(widths)) if widths else None
    for metric in ('hit5', 'hit30'):
        lower_hits = upper_hits = unknown = sequence = 0
        for item in samples:
            if item['status'] in ('cancel', 'not_triggered'):
                continue
            if item['status'] == 'unknown':
                upper_hits += 1
                unknown += 1
                continue
            event = item['outcomes'][metric]
            lo, hi = event['lower'], event['upper']
            lower_hits += lo is True
            upper_hits += hi is not False
            unknown += lo is None or hi is None
            sequence += lo is False and hi is True
        out[metric] = {'lower_hits': lower_hits, 'upper_hits_including_unknown': upper_hits,
                       'unresolved_price_or_tail': unknown, 'sequence_ambiguous': sequence,
                       'lower_rate': lower_hits / len(samples) if samples else None,
                       'upper_rate': upper_hits / len(samples) if samples else None}
    return out


def main():
    fp, cp = REPORTS / 'strong_continue_fj.json', REPORTS / 'strong_continue_gc.json'
    a, b = json.loads(fp.read_text()), json.loads(cp.read_text())
    if (a['script_sha256'] != sha(Path(fj.__file__)) or b['script_sha256'] != sha(Path(gc.__file__)) or
            b['fj_sha256'] != sha(fp)):
        raise ValueError('FJ / GC source differs')
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    dataset_digest = ds.digest()
    if a['dataset_digest'] != dataset_digest or b['dataset_digest'] != dataset_digest:
        raise ValueError('dataset differs')
    if len(a['rows']) != len(b['rows']) or len(a['rows']) != 57269:
        raise ValueError('candidate count differs')
    by_code = defaultdict(list)
    for original, price in zip(a['rows'], b['rows']):
        if (original['signal_day'], original['code']) != (price['signal_day'], price['code']):
            raise ValueError('candidate keys differ')
        if original['selected']:
            by_code[original['code']].append({**original, 'gc_hit30': price['hit30']})
    if sum(map(len, by_code.values())) != 2036:
        raise AssertionError('selected candidate count differs')
    del a, b
    stocks = {s['code'] for s in ds.stocks()}
    calendar = sorted({day for code, day, _ in ds.rows() if code in stocks})
    index = {day: i for i, day in enumerate(calendar)}
    actions, seen = ds.actions(), set()
    for code, group in groupby(ds.rows(), key=lambda r: r[0]):
        if code not in by_code:
            continue
        seen.add(code)
        records = [(day, values) for _, day, values in group]
        arrays = gc.adjusted_arrays(index, calendar, records, actions.get(code, []))
        for row in by_code[code]:
            entry = index[row['entry_day']]
            if index[row['signal_day']] != entry - 1 or row['day_index'] != entry - 1:
                raise AssertionError('calendar mismatch')
            row['open'] = opportunity(arrays, entry, row['stop'], 'open')
            row['break'] = opportunity(arrays, entry, row['stop'], 'break')
            actual = row['open']
            if actual['status'] == 'filled':
                for metric, saved in (('hit5', row['hit5']), ('hit30', row['gc_hit30'])):
                    event = actual['outcomes'][metric]
                    if saved is not None and event['lower'] is not None and event['upper'] is not None:
                        if not (int(event['lower']) <= int(saved) <= int(event['upper'])):
                            raise AssertionError('saved opportunity outside bounds ' + row['entry_day'] + ' ' + code)
            elif actual['status'] == 'cancel' and (row['status'] != 'cancel' or row['gc_hit30'] is not False):
                raise AssertionError('original cancellation differs')
    if seen != set(by_code):
        raise ValueError('missing candidate symbol')
    rows = [r for group in by_code.values() for r in group]
    yearly = {}
    for year in ('2024', '2025', '2026'):
        sample = [r for r in rows if r['year'] == year]
        yearly[year] = {mode: bounds_summary(sample, mode) for mode in ('open', 'break')}
    result = {'dataset_digest': dataset_digest, 'fj_sha256': sha(fp), 'gc_sha256': sha(cp),
              'script_sha256': sha(Path(__file__)), 'results': yearly, 'rows': rows}
    target = REPORTS / 'strong_continue_gs.json'
    target.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
