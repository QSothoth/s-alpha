"""DS: audit the source-volume adjustment convention without running a strategy."""
from collections import Counter
import json
import os
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trend_breakout.panel import factors
from studies.trader_replication.martin_continue_dq import ROOT, NAMES, sha, verify_files
from studies.trader_replication.martin_continue_dr import positive, read_rows


def volume_paths(raw, qfq, actions):
    raw = {d: v for d, v in raw.items() if '2022-09-29' <= d <= '2024-12-31'}
    qfq = {d: v for d, v in qfq.items() if '2022-09-29' <= d <= '2024-12-31'}
    days = sorted(raw)
    if not days or any(not positive(raw[d][3]) for d in days):
        return None
    prices = [raw[d][3] for d in days]
    all_factor = factors(prices, np.array(days), actions)
    large = [a for a in actions if a[1] <= .7 or a[1] >= 1.3]
    large_factor = factors(prices, np.array(days), large)
    rows = {d: i for i, d in enumerate(days)}
    common = sorted(raw.keys() & qfq.keys())
    anchor = next((d for d in reversed(common) if all(positive(qfq[d][k]) and positive(raw[d][k]) for k in range(5))
                   and positive(all_factor[rows[d]]) and positive(large_factor[rows[d]])), None)
    if anchor is None:
        return None
    out = {'large_events': len([a for a in large if days[0] <= a[0] <= days[-1]]), 'years': {}}
    for day in common:
        year = day[:4]
        result = out['years'].setdefault(year, {'all': Counter(), 'large': Counter()})
        i, j = rows[day], rows[anchor]
        for name, f in (('all', all_factor), ('large', large_factor)):
            c = result[name]
            c['total'] += 1
            x, y = qfq[day][4], raw[day][4] / f[i]
            xa, ya = qfq[anchor][4], raw[anchor][4] / f[j]
            if not positive(x) or not positive(y):
                c['invalid'] += 1
                c['bad'] += 1
                continue
            deviation = abs((x / xa) / (y / ya) - 1)
            c['bad'] += int(deviation > .005)
            c['max_error'] = max(c.get('max_error', 0), deviation)
    return out


def main():
    if os.environ.get('TRADER_DATA_MODE') != 'frozen' or os.environ.get('TRADER_DATA_TAG') != 'trader-data-v1':
        raise ValueError('explicitly select frozen v1')
    prior = json.loads((ROOT / 'studies/trader_replication/reports/gap_review/strong_continue_dr.json').read_text())
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if ds.digest() != prior['v1_digest']:
        raise ValueError('v1 digest differs from DR')
    paths = {}
    for name in NAMES[:2]:
        folder = ROOT / 'data' / name
        if sha(folder / 'CHECKSUMS.sha256') != prior['inputs'][name]:
            raise ValueError('source checksum list differs from DR')
        verify_files(folder)
        for path in (folder / 'daily').glob('*.csv'):
            paths['US.' + path.stem] = folder
    actions = ds.actions()
    by_symbol = {}
    for code, old in sorted(prior['by_symbol'].items()):
        folder = paths[code]
        name = code.removeprefix('US.') + '.csv'
        info = volume_paths(read_rows(folder / 'daily_none' / name), read_rows(folder / 'daily' / name), actions.get(code, []))
        if info is None:
            if not old['adjusted'].get('no_anchor') and not old['adjusted'].get('invalid_raw_close'):
                raise ValueError('unexpected missing comparison ' + code)
            by_symbol[code] = None
            continue
        for year, result in info['years'].items():
            for key in ('total', 'bad', 'invalid'):
                if result['all'].get(key, 0) != old['adjusted'].get(year + '_volume_' + key, 0):
                    raise ValueError('DR comparison differs: ' + code + ' ' + year + ' ' + key)
        by_symbol[code] = info
    out = {'source_dr_sha256': sha(ROOT / 'studies/trader_replication/reports/gap_review/strong_continue_dr.json'),
           'v1_digest': ds.digest(), 'script_sha256': sha(Path(__file__)),
           'missing_symbols_from_dr': prior['missing_symbols'], 'by_symbol': by_symbol}
    target = ROOT / 'studies/trader_replication/reports/gap_review/strong_continue_ds.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
