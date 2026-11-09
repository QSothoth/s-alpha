"""DT: audit a research-only Dataset with cached early raw bars."""
import csv
import hashlib
from itertools import groupby
import json
import math
import os
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trader_data.dataset import Dataset
from studies.trader_data import panel
from studies.trader_replication.martin_continue_dq import ROOT, NAMES, sha, verify_files
from studies.trader_replication.martin_continue_dr import read_rows

START, CUT = '2022-09-29', '2023-01-01'


def early_rows(path):
    for day, values in sorted(read_rows(path).items()):
        if START <= day < CUT:
            yield day, values


class EarlyHistory(Dataset):
    """Research adapter using the existing raw-bar/actions Dataset contract."""
    market = 'us'

    def __init__(self, base, paths, digest):
        self.base, self.paths, self._digest = base, paths, digest

    @property
    def id(self):
        return 'research-early-v1-options-sample'

    def stocks(self):
        return [s for s in self.base.stocks() if s['code'] in self.paths]

    def rule(self):
        return {'purpose': 'historical-interface-audit', 'source': list(NAMES[:2])}

    def rows(self):
        seen = set()
        for code, group in groupby(self.base.rows(), key=lambda r: r[0]):
            if code not in self.paths:
                continue
            if code in seen:
                raise ValueError('ungrouped frozen code ' + code)
            seen.add(code)
            path = self.paths[code] / 'daily_none' / (code.removeprefix('US.') + '.csv')
            for day, values in early_rows(path):
                yield code, day, values
            for _, day, values in group:
                if day < CUT:
                    raise ValueError('base contains rows before splice date')
                yield code, day, values
        for code in sorted(self.paths.keys() - seen):
            path = self.paths[code] / 'daily_none' / (code.removeprefix('US.') + '.csv')
            for day, values in early_rows(path):
                yield code, day, values

    def actions(self):
        return self.base.actions()

    def digest(self):
        return self._digest


def main():
    if os.environ.get('TRADER_DATA_MODE') != 'frozen' or os.environ.get('TRADER_DATA_TAG') != 'trader-data-v1':
        raise ValueError('explicitly select frozen v1')
    prior_path = ROOT / 'studies/trader_replication/reports/gap_review/strong_continue_dr.json'
    prior = json.loads(prior_path.read_text())
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if ds.digest() != prior['v1_digest']:
        raise ValueError('v1 changed since DR')
    available = {s['code'] for s in ds.stocks()}
    paths, inputs = {}, {}
    for name in NAMES[:2]:
        folder = ROOT / 'data' / name
        verify_files(folder)
        inputs[name] = sha(folder / 'CHECKSUMS.sha256')
        if inputs[name] != prior['inputs'][name]:
            raise ValueError('source changed since DR')
        for path in (folder / 'daily').glob('*.csv'):
            code = 'US.' + path.stem
            if code in paths:
                raise ValueError('duplicate source ' + code)
            if code in available:
                paths[code] = folder
    if len(paths) != prior['expected_symbols']:
        raise ValueError('source universe changed since DR')
    qqq_path = ROOT / 'data/martin-luk-benchmarks-v1/US.QQQ.csv'
    with qqq_path.open(newline='') as f:
        calendar = {r['time_key'][:10] for r in csv.DictReader(f) if START <= r['time_key'][:10] < CUT
                    and math.isfinite(float(r['close'])) and float(r['close']) > 0}
    early_info = {'rows': 0, 'zero_volume': 0, 'nonpositive_prices': 0, 'nonfinite': 0,
                  'non_benchmark_days': set(), 'symbols_with_rows': 0, 'symbols_without_rows': []}
    for code, folder in sorted(paths.items()):
        early = list(early_rows(folder / 'daily_none' / (code.removeprefix('US.') + '.csv')))
        if not early:
            early_info['symbols_without_rows'].append(code)
        else:
            early_info['symbols_with_rows'] += 1
        for day, values in early:
            early_info['rows'] += 1
            early_info['non_benchmark_days'].update([day] if day not in calendar else [])
            early_info['zero_volume'] += values[4] == 0
            early_info['nonpositive_prices'] += any(v <= 0 for v in values[:4])
            early_info['nonfinite'] += any(not math.isfinite(v) for v in values)
    early_info['non_benchmark_days'] = sorted(early_info['non_benchmark_days'])
    fp = {'v1': ds.digest(), 'sources': inputs, 'script': sha(Path(__file__)),
          'panel': sha(ROOT / 'studies/trader_data/panel.py')}
    adapter = EarlyHistory(ds, paths, hashlib.sha256(json.dumps(fp, sort_keys=True).encode()).hexdigest())
    old = trader_data.load('us', mode='frozen', version='trader-data-v1')
    new = panel.build(adapter, cache=False, write_cache=False)
    old_dates, new_dates = list(map(str, old['days'])), list(map(str, new['days']))
    later = [d for d in new_dates if d >= CUT]
    date_issues = {'missing_in_new': sorted(set(old_dates) - set(later)), 'extra_in_new': sorted(set(later) - set(old_dates))}
    oi, ni = {d: i for i, d in enumerate(old_dates)}, {d: i for i, d in enumerate(new_dates)}
    oc, nc = {str(c): i for i, c in enumerate(old['codes'])}, {str(c): i for i, c in enumerate(new['codes'])}
    common_dates = sorted(set(old_dates) & set(later))
    x = np.array([oi[d] for d in common_dates]); y = np.array([ni[d] for d in common_dates])
    checks = {}
    for field in panel.FIELDS:
        count, missing, symbols, max_delta, first = 0, 0, 0, 0., None
        for code in sorted(paths):
            a, b = old[field][x, oc[code]], new[field][y, nc[code]]
            mask_diff = np.isnan(a) != np.isnan(b)
            bad = (a != b) & ~(np.isnan(a) & np.isnan(b))
            n = int(np.count_nonzero(bad))
            missing += int(np.count_nonzero(mask_diff)); count += n; symbols += n > 0
            finite = bad & np.isfinite(a) & np.isfinite(b)
            if finite.any():
                max_delta = max(max_delta, float(np.max(np.abs(a[finite].astype(float) - b[finite].astype(float)))))
            if n and first is None:
                i = int(np.flatnonzero(bad)[0]); first = {'code': code, 'day': common_dates[i]}
        checks[field] = {'different': count, 'missing_mask_different': missing, 'symbols_different': symbols,
                         'max_finite_abs_difference': max_delta, 'first': first}
    out = {'inputs': fp, 'dr_report_sha256': sha(prior_path), 'qqq_sha256': sha(qqq_path),
           'adapter_digest': adapter.digest(), 'stocks': len(paths), 'days_old': len(old_dates),
           'days_new': len(new_dates), 'date_issues': date_issues, 'early': early_info, 'fields': checks}
    out['overlap_gate'] = not any(date_issues.values()) and not early_info['non_benchmark_days'] and all(v['different'] == 0 for v in checks.values())
    target = ROOT / 'studies/trader_replication/reports/gap_review/strong_continue_dt.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print('wrote', target, 'overlap_gate', out['overlap_gate'], flush=True)


if __name__ == '__main__':
    main()
