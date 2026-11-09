"""DQ: inventory locally cached early daily bars without evaluating strategies."""
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import statistics

from studies import trader_data

ROOT = Path(__file__).resolve().parents[2]
NAMES = ('preopen-s24-select-v1', 'preopen-s27-holdout-v1', 'preopen-us-holdout-2016-v1')


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def verify_files(folder):
    checks = {}
    for line in (folder / 'CHECKSUMS.sha256').read_text().splitlines():
        h, name = line.split(None, 1)
        checks[name.strip().lstrip('*')] = h
    results = {}
    for sub in ('daily', 'daily_none'):
        actual = {p.relative_to(folder).as_posix() for p in (folder / sub).glob('*.csv')}
        declared = {name for name in checks if name.startswith(sub + '/') and name.endswith('.csv')}
        if actual != declared:
            raise ValueError(f'{folder.name}: {sub} file list differs from checksum inventory')
        for name in sorted(actual):
            if sha(folder / name) != checks[name]:
                raise ValueError(f'{folder.name}: checksum mismatch {name}')
        results[sub] = len(actual)
    return results


def read_csv(path):
    """Read at most one ticker's bounded daily file; invalid bars remain absent."""
    valid, all_dates = {}, set()
    with path.open(newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        required = {'date', 'open', 'high', 'low', 'close', 'volume', 'turnover'}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('unexpected columns: ' + str(path))
        for row in reader:
            date = row['date'][:10]
            if date in all_dates:
                raise ValueError('duplicate date: ' + str(path))
            all_dates.add(date)
            try:
                o, h, l, c, v, t = (float(row[k]) for k in ('open', 'high', 'low', 'close', 'volume', 'turnover'))
            except (TypeError, ValueError):
                continue
            if all(math.isfinite(x) for x in (o, h, l, c, v, t)) and min(o, h, l, c) > 0 and v > 0 and t >= 0 and l <= min(o, c) <= max(o, c) <= h:
                valid[date] = (c, t)
    return valid, all_dates


def month_summary(days, daily):
    groups = defaultdict(list)
    for day in days:
        if '2022-01' <= day[:7] <= '2023-12':
            groups[day[:7]].append(int(daily.get(day, 0)))
    return {m: {'sessions': len(a), 'min': min(a), 'median': float(statistics.median(a)), 'max': max(a)}
            for m, a in sorted(groups.items())}


def scan(folder):
    names = sorted(p.stem for p in (folder / 'daily').glob('*.csv'))
    days, info = set(), {}
    for name in names:
        data, all_dates = read_csv(folder / 'daily' / (name + '.csv'))
        days.update(all_dates)
        info[name] = {'first_valid': min(data) if data else None, 'last_valid': max(data) if data else None,
                      'valid_rows': len(data), 'all_rows': len(all_dates)}
    return names, sorted(days), info


def coverage(folder_by_symbol, calendar):
    daily = {key: Counter() for key in ('valid_qfq', 'paired_valid', 'prior250_complete', 'prior250_75pct', 'liquid_warm')}
    for symbol, folder in sorted(folder_by_symbol.items()):
        q, _ = read_csv(folder / 'daily' / (symbol + '.csv'))
        raw_path = folder / 'daily_none' / (symbol + '.csv')
        raw, _ = read_csv(raw_path) if raw_path.exists() else ({}, set())
        mask = [d in q for d in calendar]
        raw_mask = [d in raw for d in calendar]
        for i, day in enumerate(calendar):
            if day[:4] not in ('2022', '2023'):
                continue
            if mask[i]:
                daily['valid_qfq'][day] += 1
            if mask[i] and raw_mask[i]:
                daily['paired_valid'][day] += 1
            if i < 251:
                continue
            n = sum(mask[i - 250:i])
            if n == 250:
                daily['prior250_complete'][day] += 1
            if n < 188:
                continue
            daily['prior250_75pct'][day] += 1
            # A conservative coverage proxy for the existing prior-close U universe.
            if not raw_mask[i - 1]:
                continue
            turn = [raw[calendar[k]][1] for k in range(i - 20, i) if raw_mask[k]]
            if len(turn) >= 15 and raw[calendar[i - 1]][0] >= 2 and sum(turn) / len(turn) >= 1e7:
                daily['liquid_warm'][day] += 1
    return {name: month_summary(calendar, values) for name, values in daily.items()}, daily


def main():
    if os.environ.get('TRADER_DATA_MODE') != 'frozen' or os.environ.get('TRADER_DATA_TAG') != 'trader-data-v1':
        raise ValueError('explicitly select frozen v1')
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    v1 = {s['code'].removeprefix('US.') for s in ds.stocks()}
    qqq = set()
    with (ROOT / 'data/martin-luk-benchmarks-v1/US.QQQ.csv').open(newline='') as f:
        for r in csv.DictReader(f):
            try:
                if math.isfinite(float(r['close'])) and float(r['close']) > 0:
                    qqq.add(r['time_key'][:10])
            except (TypeError, ValueError):
                pass
    result, source = {}, {}
    for name in NAMES:
        folder = ROOT / 'data' / name
        counts = verify_files(folder)
        symbols, calendar, info = scan(folder)
        source[name] = (folder, symbols, calendar)
        result[name] = {'file_counts': counts, 'symbols': len(symbols), 'v1_overlap': len(set(symbols) & v1),
                        'calendar_sessions': len(calendar), 'calendar_first': min(calendar) if calendar else None,
                        'calendar_last': max(calendar) if calendar else None,
                        'benchmark_missing_2022_23': sum(d not in qqq for d in calendar if d[:4] in ('2022', '2023')),
                        'symbols_with_raw': sum((folder / 'daily_none' / (s + '.csv')).exists() for s in symbols),
                        'by_symbol': info, 'manifest_sha256': sha(folder / 'manifest.json'),
                        'checksums_sha256': sha(folder / 'CHECKSUMS.sha256')}
    s24, s27 = (source[n] for n in NAMES[:2])
    duplicates = sorted(set(s24[1]) & set(s27[1]))
    if duplicates:
        raise ValueError('S24/S27 advertised disjoint but duplicate codes exist')
    mapping = {s: folder for folder, names, _ in (s24, s27) for s in names}
    stock_calendar = sorted(set(s24[2]) | set(s27[2]))
    calendar = sorted(d for d in qqq if '2022-09-29' <= d <= '2023-12-31')
    if not calendar:
        raise ValueError('benchmark calendar empty in the registered inventory period')
    monthly, daily = coverage(mapping, calendar)
    after = [d for d in calendar if d.startswith('2023') and daily['liquid_warm'][d] > 300]
    v1_first = min(str(day) for day in trader_data.load('us', mode='frozen', version='trader-data-v1')['days'])
    combined = {'symbols': len(mapping), 'v1_overlap': len(set(mapping) & v1),
                'stock_calendar_first': stock_calendar[0], 'stock_calendar_last': stock_calendar[-1],
                'inventory_calendar_first': calendar[0], 'inventory_calendar_last': calendar[-1],
                'stock_calendar_missing_benchmark_sessions': [d for d in calendar if d not in set(stock_calendar)],
                'v1_first': v1_first,
                'first_2023_more_than_300_warm_liquid_proxy': after[0] if after else None,
                'monthly': monthly}
    target = ROOT / 'studies/trader_replication/reports/gap_review/strong_continue_dq.json'
    out = {'sources': result, 'combined_s24_s27': combined, 'v1_dataset_digest': ds.digest(),
           'qqq_sha256': sha(ROOT / 'data/martin-luk-benchmarks-v1/US.QQQ.csv'),
           'script_sha256': sha(Path(__file__))}
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
