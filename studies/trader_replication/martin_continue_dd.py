"""DD: qualify locally cached GLD/SLV bars for the existing Dataset interface."""
import csv
import hashlib
import json
from pathlib import Path

import numpy as np

from studies import trader_data
from studies.trader_data import panel
from studies.trader_data.dataset import Dataset

ROOT = Path(__file__).resolve().parents[2]
SYMBOLS = ('GLD', 'SLV')
FIELDS = ('open', 'high', 'low', 'close', 'volume', 'turnover')
START, END = '2023-01-03', '2026-09-23'
CHECKSUM_PIN = '0584d9361b77b9870cb78ffb10de73264407ddf3358931fa46b73635b106691f'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_daily(path):
    out = {}
    with path.open(newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            day = row['date']
            if out and day <= next(reversed(out)):
                raise ValueError(f'duplicate or unordered date in {path.name}: {day}')
            try:
                values = tuple(float(row[k]) for k in FIELDS)
            except (KeyError, ValueError, TypeError):
                values = None
            out[day] = values
    return out


def valid(values):
    if values is None or not all(np.isfinite(x) and x > 0 for x in values):
        return False
    o, h, l, c, _, _ = values
    return l <= min(o, c) and h >= max(o, c)


def quality(adjusted, raw, sessions):
    common = sorted(adjusted.keys() & raw.keys())
    differences, invalid = [], []
    for day in common:
        a, r = adjusted[day], raw[day]
        if not valid(a) or not valid(r):
            invalid.append(day)
        elif not np.allclose(a, r, rtol=1e-8, atol=0):
            differences.append(day)
    missing = [day for day in sessions if day not in adjusted or day not in raw]
    unusable = [day for day in sessions if day in adjusted and day in raw and
                (not valid(adjusted[day]) or not valid(raw[day]))]
    eligible = len(common) >= 500 and not missing and not unusable and not differences and not invalid
    return {'adjusted_count': len(adjusted), 'raw_count': len(raw), 'common_count': len(common),
            'first_common': common[0] if common else None, 'last_common': common[-1] if common else None,
            'expected_market_sessions': len(sessions), 'missing_market_dates': missing,
            'invalid_market_dates': unusable, 'invalid_common_dates': invalid,
            'mismatched_common_dates': differences, 'eligible': eligible}


class VerifiedPair(Dataset):
    """Read only proven identical raw/QFQ slices, through the standard panel builder."""
    market = 'us'

    def __init__(self, raws, adjusted, sessions, sources):
        if any(not quality(adjusted[s], raws[s], sessions)['eligible'] for s in SYMBOLS):
            raise ValueError('ETF source pair has not passed the fixed quality checks')
        self._raws = raws
        self._sources = sources

    @property
    def id(self):
        return 'research-verified-gld-slv-2023-20260923'

    def stocks(self):
        return [{'code': 'US.' + s, 'name': s} for s in SYMBOLS]

    def rule(self):
        return {'purpose': 'historical-data-quality-only', 'symbols': list(SYMBOLS)}

    def rows(self):
        for symbol in SYMBOLS:
            for day, values in self._raws[symbol].items():
                if START <= day <= END:
                    yield 'US.' + symbol, day, values

    def actions(self):
        return {}

    def digest(self):
        payload = {'source_sha256': self._sources, 'panel_version': panel.VERSION,
                   'script_sha256': sha(Path(__file__))}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def main():
    xsec = ROOT / 'data/preopen-us-xsec-v1'
    source_raw = ROOT / 'data/preopen-s23-raw/daily_none'
    checksums = xsec / 'CHECKSUMS.sha256'
    if sha(checksums) != CHECKSUM_PIN:
        raise ValueError('published xsec checksum manifest differs')
    registered = {}
    for line in checksums.read_text().splitlines():
        value, name = line.split(maxsplit=1)
        registered[name.strip().lstrip('*')] = value
    if registered.get('manifest.json') != sha(xsec / 'manifest.json'):
        raise ValueError('published xsec metadata hash differs')
    meta = json.loads((xsec / 'manifest.json').read_text())
    if 'QFQ' not in meta['source'] or meta['window'] != ['2022-09-28', END]:
        raise ValueError('xsec provenance differs')
    raw, adjusted, hashes = {}, {}, {'CHECKSUMS.sha256': sha(checksums), 'manifest.json': sha(xsec / 'manifest.json')}
    for sym in SYMBOLS:
        a, r = xsec / f'daily/{sym}.csv', source_raw / f'{sym}.csv'
        if registered[f'daily/{sym}.csv'] != sha(a):
            raise ValueError('published QFQ file hash differs: ' + sym)
        hashes[f'xsec/daily/{sym}.csv'], hashes[f's23-raw/daily_none/{sym}.csv'] = sha(a), sha(r)
        adjusted[sym], raw[sym] = read_daily(a), read_daily(r)
    frozen = trader_data.load('us', mode='frozen', version='trader-data-v1')
    pin = json.loads((ROOT / 'studies/trader_replication/DATA_PIN.json').read_text())['trader-data-v1']['us']
    if frozen['digest'] != pin:
        raise ValueError('frozen market panel digest differs')
    sessions = [str(d) for d in frozen['days'] if START <= str(d) <= END]
    del frozen
    audit = {s: quality(adjusted[s], raw[s], sessions) for s in SYMBOLS}
    dc_path = ROOT / 'studies/trader_replication/reports/gap_review/strong_continue_dc.json'
    dc = json.loads(dc_path.read_text())
    if dc['dataset_digest'] != pin:
        raise ValueError('DC source digest differs')
    targets = [r for r in dc['years']['all']['missing_details'] if r['ticker'] in SYMBOLS]
    target_check = [{'id': r['id'], 'ticker': r['ticker'], 'day': r['entry_date'],
                     'covered': r['entry_date'] in raw[r['ticker']] and r['entry_date'] in adjusted[r['ticker']]
                     and valid(raw[r['ticker']][r['entry_date']]) and valid(adjusted[r['ticker']][r['entry_date']])}
                    for r in targets]
    result = {'dataset_digest': pin, 'window': [START, END], 'files_sha256': hashes, 'quality': audit,
              'dc_targets': target_check, 'dataset_adapter': {'built': False},
              'dc_report_sha256': sha(dc_path), 'script_sha256': sha(Path(__file__)),
              'panel_sha256': sha(ROOT / 'studies/trader_data/panel.py'),
              'dataset_interface_sha256': sha(ROOT / 'studies/trader_data/dataset.py')}
    if all(audit[s]['eligible'] for s in SYMBOLS):
        ds = VerifiedPair(raw, adjusted, sessions, hashes)
        built = panel.build(ds, cache=False, write_cache=False)
        if list(map(str, built['days'])) != sessions:
            raise AssertionError('adapter does not reproduce market sessions')
        for j, sym in enumerate(SYMBOLS):
            for i, day in enumerate(sessions):
                vals = raw[sym][day]
                for k, expected in zip(FIELDS, vals):
                    if built[k][i, j] != np.float32(expected):
                        raise AssertionError('adapter differs from source: ' + sym + ' ' + day + ' ' + k)
                if built['raw_close'][i, j] != np.float32(vals[3]):
                    raise AssertionError('raw close differs')
        result['dataset_adapter'] = {'built': True, 'id': ds.id, 'digest': ds.digest(),
                                     'days': len(sessions), 'symbols': ['US.' + s for s in SYMBOLS],
                                     'live_supported': False}
    target = dc_path.with_name('strong_continue_dd.json')
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
