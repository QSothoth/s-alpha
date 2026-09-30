"""Offline audit of saved OpenD 30-minute bars against six 5-minute bars.

Run: python3 -m studies.us_0dte_picks.parity --out <new.json>
Only one symbol's two files are held in memory. Decimal preserves source precision.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from .p3 import GRID, daily_bar

FIELDS = ('open', 'high', 'low', 'close', 'volume', 'turnover')
GRID30 = GRID[5::6]


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()


def verified_files(root):
    expected = {}
    for line in (root / 'CHECKSUMS.sha256').read_text(encoding='utf-8').splitlines():
        digest, name = line.split()
        if name in expected or Path(name).name != name:
            raise ValueError('Duplicate or invalid checksum name: ' + name)
        expected[name] = digest
    actual = {path.name for path in root.glob('*.json')}
    if actual != set(expected):
        raise ValueError('JSON files and checksum inventory differ')
    for name, digest in expected.items():
        if sha256(root / name) != digest:
            raise ValueError('Checksum mismatch: ' + name)
    symbols = sorted(name.removesuffix('.K_30M.json') for name in actual if name.endswith('.K_30M.json'))
    if not symbols or actual != {s + '.' + k + '.json' for s in symbols for k in ('K_5M', 'K_30M')}:
        raise ValueError('Expected one 5-minute and one 30-minute file per symbol')
    return symbols, expected


def sessions(path, symbol, grid):
    rows = json.loads(path.read_text(encoding='utf-8'), parse_float=Decimal, parse_int=Decimal)
    days, stamps = defaultdict(list), set()
    for row in rows:
        stamp = row['time_key']
        if stamp in stamps or row['code'] != 'US.' + symbol:
            raise ValueError('Duplicate timestamp or wrong symbol in ' + str(path))
        stamps.add(stamp)
        if any(not row[f].is_finite() for f in FIELDS):
            raise ValueError('Non-finite OHLCV/turnover in ' + str(path))
        if not 0 < row['low'] <= min(row['open'], row['close']) <= max(row['open'], row['close']) <= row['high']:
            raise ValueError('Invalid OHLC in ' + str(path))
        if row['volume'] < 0 or row['turnover'] < 0:
            raise ValueError('Negative volume or turnover in ' + str(path))
        days[stamp[:10]].append(row)
    for bars in days.values():
        bars.sort(key=lambda r: r['time_key'])
    full = {day: bars for day, bars in sorted(days.items()) if tuple(r['time_key'][11:] for r in bars) == grid}
    excluded = [{'day': day, 'bars': len(bars), 'first': bars[0]['time_key'], 'last': bars[-1]['time_key']}
                for day, bars in sorted(days.items()) if day not in full]
    return days, full, {'rows': len(rows), 'complete_days': list(full), 'excluded_days': excluded}


def aggregate(rows):
    bars = [(r['time_key'][11:], r['open'], r['high'], r['low'], r['close'], r['volume']) for r in rows]
    return dict(zip(FIELDS, (*daily_bar(bars), sum(r['turnover'] for r in rows))))


def compare(left, right, label):
    """Signed deltas are native 30-minute value minus 5-minute aggregation."""
    return {'label': label, 'k5': left, 'k30': right,
            'delta': {f: right[f] - left[f] for f in FIELDS}}


def summary(comparisons):
    fields = {}
    for field in FIELDS:
        different = [r for r in comparisons if r['delta'][field]]
        worst = max(different, key=lambda r: abs(r['delta'][field]), default=None)
        relative = [(abs(r['delta'][field] / r['k5'][field]), r['label'])
                    for r in different if r['k5'][field]]
        max_relative, relative_label = max(relative, default=(Decimal(0), None))
        fields[field] = {'different': len(different),
                         'max_absolute_delta': abs(worst['delta'][field]) if worst else Decimal(0),
                         'worst_absolute': None if worst is None else {
                             'label': worst['label'], 'k5': worst['k5'][field], 'k30': worst['k30'][field],
                             'delta': worst['delta'][field]},
                         'max_relative_delta': max_relative, 'worst_relative_label': relative_label}
    return {'comparisons': len(comparisons), 'fields': fields}


def audit(root):
    symbols, inventory = verified_files(root)
    opening, daily, blocks, names, anomalies = [], [], [], {}, []
    for symbol in symbols:
        days5, full5, coverage5 = sessions(root / (symbol + '.K_5M.json'), symbol, GRID)
        days30, full30, coverage30 = sessions(root / (symbol + '.K_30M.json'), symbol, GRID30)
        shared = sorted(full5.keys() & full30.keys())
        name_opening, name_daily, name_blocks = [], [], []
        for day in shared:
            label = symbol + ' ' + day
            name_opening.append(compare(aggregate(full5[day][:6]), aggregate(full30[day][:1]), label))
            name_daily.append(compare(aggregate(full5[day]), aggregate(full30[day]), label))
        for day, bars30 in sorted(days30.items()):
            by_clock = {r['time_key'][11:]: r for r in days5.get(day, ())}
            for row30 in bars30:
                clock = row30['time_key'][11:]
                if clock not in GRID30:
                    continue
                end = GRID.index(clock) + 1
                clocks = GRID[end - 6:end]
                if not all(c in by_clock for c in clocks):
                    continue
                record = compare(aggregate([by_clock[c] for c in clocks]), aggregate([row30]),
                                 symbol + ' ' + row30['time_key'])
                name_blocks.append(record)
                # These arithmetic envelopes diagnose differences; they do not certify rounding as the cause.
                if (any(record['delta'][f] for f in FIELDS[:4]) or not 0 <= record['delta']['volume'] <= 5
                        or abs(record['delta']['turnover']) > Decimal('.006')):
                    anomalies.append(record)
        if not shared:
            raise ValueError('No common complete session: ' + symbol)
        names[symbol] = {'k5': coverage5, 'k30': coverage30, 'common_complete_days': shared,
                         'opening': summary(name_opening), 'daily': summary(name_daily), 'blocks': summary(name_blocks)}
        opening.extend(name_opening)
        daily.extend(name_daily)
        blocks.extend(name_blocks)
    return {'study': 'P5 input parity, not a strategy validation', 'input_root': str(root),
            'code_sha256': sha256(Path(__file__)), 'checksums_sha256': sha256(root / 'CHECKSUMS.sha256'),
            'verified_files': inventory, 'source_manifest_present': (root / 'manifest.json').exists(),
            'timestamp_convention': 'RTH bar close: 5m 09:35..16:00, 30m 10:00..16:00',
            'numeric_comparison': 'Exact Decimal; relative delta denominator is the 5-minute aggregation',
            'strict_parity': all(not r['delta'][f] for r in blocks + daily for f in FIELDS),
            'opening': summary(opening), 'daily': summary(daily), 'blocks': summary(blocks),
            'block_volume_delta_counts': dict(sorted(Counter(str(r['delta']['volume']) for r in blocks).items())),
            'block_anomalies': anomalies, 'symbols': names}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw', type=Path, default=Path('data/p5-parity-raw'))
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.raw)
    with args.out.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, default=str)
        handle.write('\n')
    print('Strict parity:', report['strict_parity'], '| symbols:', len(report['symbols']),
          '| opening/day pairs:', report['daily']['comparisons'], '| 30m blocks:', report['blocks']['comparisons'])


if __name__ == '__main__':
    main()
