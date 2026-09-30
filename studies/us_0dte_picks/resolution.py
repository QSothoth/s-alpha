"""Measure 5m versus aggregated 30m exits for the already-used P4 A4 sample.

Offline only; this is a resolution audit, not another validation or rule search.
Run from the repository root with --out <new.json>.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path

from . import daily_k, p3, p4

NAME = 'A4_THRUST_FOLLOW'
ORIGINAL = p3.HERE / 'reports' / 'p4_validate.json'


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def aggregate30(bars):
    """A full 78-bar close-stamped RTH day becomes 13 aligned OHLCV bars."""
    if tuple(bar[0] for bar in bars) != p3.GRID:
        raise ValueError('expected a complete 78-bar RTH session')
    return [(bars[i + 5][0], *p3.daily_bar(bars[i:i + 6])) for i in range(0, 78, 6)]


def coarse_outcome(bars, entry, sigma_rem, side):
    result = p4.first_touch_from(aggregate30(bars), 0, entry, sigma_rem, side)
    # Preserve the original 5m exit-index convention for timestamps and row_of.
    return (*result[:4], (result[4] + 1) * 6 - 1, result[5])


def build():
    """Stream calendar dates first, then retain bars for only one symbol at a time."""
    items = p3.universe('validate', 'a')
    reference = [str(Path(folder) / 'AAPL.csv') for folder in p3.SELECT_K5['core']]
    calendar = set()
    inputs = set(reference)
    for _, paths in items:
        inputs.update(paths)
    for path in sorted(inputs):
        with open(path, newline='', encoding='utf-8') as handle:
            calendar.update(row['time_key'][:10] for row in csv.DictReader(handle)
                            if row['time_key'][:10] >= '2023-03-01')
    calendar = sorted(calendar)
    records, name_days, names = [], 0, 0
    for symbol, paths in items:
        for folder in p3.SIDE_DIRS:
            inputs.update(str(Path(folder) / table / (symbol + '.csv'))
                          for table in ('daily_none', 'option_stats', 'iv'))
        inputs.update(str(daily_k.EVENTS / table / (symbol + '.json')) for table in ('expiry', 'earnings'))
        bars, _ = p3.sessions(paths)
        weekly, mon_wed = daily_k.schedule(symbol)
        features = p3.features(symbol, bars, calendar, p3.side_tables(symbol), weekly, mon_wed,
                               daily_k.reaction_days(symbol, calendar), None, p4.WINDOW)
        name_days += len(features)
        names += bool(features)
        for record in features:
            if p3.signal(record, NAME):
                for side in (1, -1):
                    record['coarse', side] = coarse_outcome(bars[record['day']], record['p10'],
                                                            record['sigma_rem'], side)
                records.append(record)
        del bars, features
    return p3.picks(records, NAME), name_days, names, inputs


def summarize(picks, coarse=False, reverse=False):
    rows = {}
    for day, items in picks.items():
        rows[day] = []
        for side, record in items:
            if coarse:
                record = dict(record)
                for direction in (1, -1):
                    record['outcome', direction] = record['coarse', direction]
            row = p3.row_of(-side if reverse else side, record)
            if coarse or reverse:
                row['option'] = None  # This audit measures stock exits, not option returns.
            rows[day].append(row)
    return p4.summarize(rows, p4.HALF)


def outcome_record(outcome):
    return {'payoff': outcome[0], 'target': outcome[1], 'stop': outcome[2],
            'best_sigma': outcome[3], 'chop': outcome[3] < p3.CHOP,
            'exit_bar_close': p3.GRID[outcome[4]], 'exit_price': outcome[5]}


def status(outcome):
    return 'target' if outcome[1] else 'stop' if outcome[2] else 'close'


def run():
    for path, expected in ((p3.PREREG, p3.PREREG_SHA256), (p4.PREREG, p4.PREREG_SHA256)):
        if sha256(path) != expected:
            raise ValueError(str(path) + ' changed after registration')
    manifest = Path(p3.VALIDATION_K5).parent / 'CHECKSUMS.sha256'
    checks = manifest.read_text(encoding='utf-8').splitlines()
    for line in checks:
        expected, relative = line.split(maxsplit=1)
        if sha256(manifest.parent / relative) != expected:
            raise ValueError('raw data checksum mismatch: ' + relative)
    picks, name_days, names, inputs = build()
    baseline = summarize(picks)
    old = json.loads(ORIGINAL.read_text(encoding='utf-8'))
    differences = {key: [old['results'][NAME].get(key), value] for key, value in baseline.items()
                   if old['results'][NAME].get(key) != value}
    if name_days != old['name_days'] or names != old['names'] or differences:
        raise ValueError('P4 reproduction mismatch: ' + repr((name_days, names, differences)))
    print('P4 reproduced: %d name-days, %d names, %d picks, %d dates; all original summary fields match'
          % (name_days, names, baseline['picks'], baseline['dates']), flush=True)
    results = {'5m': baseline, '30m': summarize(picks, coarse=True),
               'reverse_5m': summarize(picks, reverse=True),
               'reverse_30m': summarize(picks, coarse=True, reverse=True)}
    for result in results.values():
        for key in list(result):
            if key.startswith('option_'):
                del result[key]
        result['p4_a4_gates'] = p4.validate_gates(result, False)
        result['p4_a4_pass'] = all(result['p4_a4_gates'].values())
        result['target_rate>=30%'] = result['target_rate'] >= .30
    transitions = {'forward': Counter(), 'reverse': Counter()}
    rows = []
    for day, items in sorted(picks.items()):
        for rank, (side, record) in enumerate(items, 1):
            row = {'day': day, 'symbol': record['symbol'], 'rank': rank, 'side': side,
                   'rvol30': record['rvol30'], 'entry': record['p10'], 'sigma_rem': record['sigma_rem']}
            for label, direction in (('forward', side), ('reverse', -side)):
                fine, coarse = record['outcome', direction], record['coarse', direction]
                transitions[label][status(fine) + '->' + status(coarse)] += 1
                row[label + '_5m'] = outcome_record(fine)
                row[label + '_30m'] = outcome_record(coarse)
            rows.append(row)
    paths = [ORIGINAL, p3.HERE / 'notes' / 'p3_validation_names.json', p3.PREREG, p4.PREREG,
             manifest, Path(__file__), Path(p3.__file__), Path(p4.__file__), Path(daily_k.__file__)]
    inputs.update(str(path.resolve().relative_to(Path.cwd())) for path in paths)
    hashes = {path: sha256(path) if Path(path).exists() else None for path in sorted(inputs)}
    return {'study': 'P4_A4_resolution_audit', 'new_validation': False, 'window': p4.WINDOW,
            'method': 'Frozen P4 A4 signals and daily top-5; 10:00 entry; aligned 6x5m bars; same-bar stop first',
            'bootstrap': {'draws': p3.DRAWS, 'seed': p3.SEED, 'unit': 'date', 'lo90_quantile': .05},
            'raw_checksum_entries_verified': len(checks), 'input_sha256': hashes,
            'reproduction': {'all_original_summary_fields_equal': True, 'name_days': name_days,
                             'names': names, 'picks': baseline['picks'], 'dates': baseline['dates']},
            'results': results, 'transitions': transitions, 'rows': rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error('refusing to overwrite ' + str(args.out))
    report = run()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=1)
        handle.write('\n')
    print(json.dumps({'results': report['results'], 'transitions': report['transitions']}, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
