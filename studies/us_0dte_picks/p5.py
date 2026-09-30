"""One frozen A4 evaluation on local native 30m P5 data; never fetches data.

Run from the repository root: python3 -m studies.us_0dte_picks.p5 --out <new.json>
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date
import hashlib
import json
from math import isfinite, sqrt
from pathlib import Path
from statistics import mean

from . import daily_k, p3, p4

PREREG = p3.HERE / 'notes' / 'P5_PREREG.md'
PREREG_SHA256 = '99d4f1ec0523be9c7f7510460dd2a50cf0522a4aec471c42a0c04489bf815ea3'
INVENTORY = p3.HERE / 'notes' / 'test_sets_inventory.json'
INVENTORY_SHA256 = '418646c358fb7ddec307f905f1fe9ca9c9cadc631efcdb1c2788a1e447371cb3'
SELECTION_SHA256 = 'f9edf0a335a49240b5001fbf088bba0198abc3e8cc753182082940dadfedff67'
WINDOW = ('2026-07-01', '2026-09-25')
GRID = p3.GRID[5::6]
NAME = 'A4_THRUST_FOLLOW'


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def verified_inputs(root):
    """Reject incomplete or changed snapshots before reading any minute payload."""
    if sha256(PREREG) != PREREG_SHA256:
        raise ValueError('P5_PREREG.md changed after registration')
    if sha256(INVENTORY) != INVENTORY_SHA256:
        raise ValueError('frozen inventory changed')
    hashes = {}
    manifest = root / 'CHECKSUMS.sha256'
    for line in manifest.read_text(encoding='utf-8').splitlines():
        expected, name = line.split(maxsplit=1)
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or path == manifest.resolve():
            raise ValueError('invalid checksum path: ' + name)
        if str(path) in hashes or sha256(path) != expected:
            raise ValueError('duplicate or mismatched checksum: ' + name)
        hashes[str(path)] = expected
    actual = {str(p.resolve()) for p in root.rglob('*') if p.is_file() and p != manifest}
    if actual != set(hashes):
        raise ValueError('CHECKSUMS must cover every raw file exactly once')
    hashes[str(manifest.resolve())] = sha256(manifest)
    metadata, selection = read_json(root / 'manifest.json'), read_json(root / 'selection.json')
    if metadata.get('status') != 'complete':
        raise ValueError('collection is incomplete; evaluation is forbidden')
    for payload in (metadata, selection):
        if (payload.get('preregistration_sha256') != PREREG_SHA256
                or payload.get('inventory_sha256') != INVENTORY_SHA256):
            raise ValueError('metadata does not match the frozen protocol and inventory')
    if metadata['selection_sha256'] != SELECTION_SHA256 or sha256(root / 'selection.json') != SELECTION_SHA256:
        raise ValueError('frozen selection hash mismatch')
    frozen_path = root / 'metadata_checksums.json'
    if metadata['metadata_checksums_sha256'] != sha256(frozen_path):
        raise ValueError('frozen metadata checksum list changed')
    frozen = read_json(frozen_path)
    if not {'selection.json', 'calendar.json', 'candidates.json'} <= set(frozen):
        raise ValueError('frozen metadata does not cover selection, calendar and candidates')
    for name, expected in frozen.items():
        if hashes.get(str((root / name).resolve())) != expected:
            raise ValueError('frozen metadata changed: ' + name)
    for name, expected in metadata['input_sha256'].items():
        if sha256(name) != expected:
            raise ValueError('collector source changed: ' + name)
        hashes[str(Path(name).resolve())] = expected
    # Verify every actual side-table source before consuming any new minute outcomes.
    expected_sources = {}
    for dataset in read_json(INVENTORY)['datasets']:
        folder = Path(dataset['directory'])
        checksum = folder / 'CHECKSUMS.sha256'
        if sha256(checksum) != dataset['checksums_sha256']:
            raise ValueError('source checksum list changed: ' + str(checksum))
        hashes[str(checksum.resolve())] = dataset['checksums_sha256']
        for line in checksum.read_text(encoding='utf-8').splitlines():
            expected, name = line.split(maxsplit=1)
            expected_sources[str((folder / name.lstrip('*')).resolve())] = expected
    sources = {daily_k.EVENTS / 'expiry' / (row['symbol'] + '.json') for row in selection['selected']}
    sources.update(Path(folder) / table / (row['symbol'] + '.csv') for row in selection['selected']
                   for folder in p3.SIDE_DIRS for table in ('daily_none', 'option_stats', 'iv'))
    for source in sorted(sources):
        name = str(source.resolve())
        expected = expected_sources.get(name)
        actual_hash = sha256(source) if source.exists() else None
        if actual_hash != expected:
            raise ValueError('side-table source missing, changed or unregistered: ' + str(source))
        hashes[name] = actual_hash
    for path in (PREREG, INVENTORY, Path(__file__), Path(p3.__file__), Path(p4.__file__), Path(daily_k.__file__)):
        hashes[str(path.resolve())] = sha256(path)
    return selection, hashes


def sessions(rows, calendar):
    """At most 1000 raw bars for one symbol; retain only complete valid RTH days."""
    grouped, invalid, seen = defaultdict(list), set(), set()
    for row in rows:
        stamp = str(row['time_key'])
        day = date.fromisoformat(stamp[:10]).isoformat()
        if day > WINDOW[1]:
            continue
        seen.add(day)
        try:
            bar = (stamp[11:19], *(float(row[k]) for k in ('open', 'high', 'low', 'close', 'volume')))
        except (ValueError, TypeError, KeyError):
            invalid.add(day)
            continue
        if not (all(isfinite(v) for v in bar[1:]) and 0 < bar[3] <= min(bar[1], bar[4])
                <= max(bar[1], bar[4]) <= bar[2] and bar[5] >= 0):
            invalid.add(day)
        grouped[day].append(bar)
    complete = {}
    for day, bars in grouped.items():
        bars.sort()
        if (day in calendar and calendar[day] == 'WHOLE' and day not in invalid
                and tuple(bar[0] for bar in bars) == GRID):
            complete[day] = bars
    return complete, seen


def features(symbol, bars, seen, calendar, tables):
    """Yield every evaluation market date with one exclusive exclusion or a feature row."""
    market_days, days = sorted(calendar), sorted(bars)
    positions = {day: i for i, day in enumerate(days)}
    daily = {day: p3.daily_bar(bars[day]) for day in days}
    nominal, option_volume, ivs = tables
    valid_iv = [(day, value) for day, value in zip(ivs['iv_days'], ivs['iv']) if isfinite(value) and value > 0]
    ivs = {'iv_days': [x[0] for x in valid_iv], 'iv': [x[1] for x in valid_iv]}
    for index, day in enumerate(market_days):
        if not WINDOW[0] <= day <= WINDOW[1]:
            continue
        reason, record = None, None
        if day not in bars:
            reason = 'incomplete_or_invalid_session' if day in seen else 'missing_session'
        elif (position := positions[day]) < 25:
            reason = 'fewer_than_25_complete_prior_days'
        elif not index or days[position - 1] != market_days[index - 1]:
            reason = 'previous_market_day_not_complete'
        else:
            previous = market_days[index - 1]
            prior = days[position - 14:position]
            recent = set(market_days[max(0, index - 20):index])
            iv = daily_k.iv_before(ivs, day)
            close, options = nominal.get(previous), option_volume.get(previous)
            turnover = mean(daily[d][3] * daily[d][4] for d in days[position - 20:position])
            base = mean(bars[d][0][5] for d in prior)
            if not all(d in recent for d in prior):
                reason = 'baseline_14_outside_20_market_days'
            elif iv is None:
                reason = 'iv_missing_or_stale'
            elif close is None or not isfinite(close):
                reason = 'nominal_t1_close_missing_or_invalid'
            elif close < 3:
                reason = 'nominal_t1_close_below_3'
            elif options is None or not isfinite(options):
                reason = 'option_volume_t1_missing_or_invalid'
            elif options < 1000:
                reason = 'option_volume_t1_below_1000'
            elif turnover < 5e6:
                reason = 'turnover20_below_5m'
            elif not isfinite(base) or base <= 0:
                reason = 'opening_volume_baseline_invalid'
            else:
                first = bars[day][0]
                o, p10, c1 = first[1], first[4], daily[previous][3]
                sigma = iv / 100 / sqrt(252)
                record = {'symbol': symbol, 'day': day, 'p10': p10, 'iv': iv,
                          'sigma_rem': sigma * sqrt(p3.REMAINING / 390),
                          'thrust': p3.thrust_side(daily, days, position),
                          'drive_z': (p10 / o - 1) / sigma,
                          'above_c1': 1 if p10 > c1 else -1 if p10 < c1 else 0,
                          'rvol30': first[5] / base,
                          'rvol30_base': base, 'rvol30_days': prior}
        yield day, reason, record


def cap_groups(selected):
    """Freeze thirds on all selected positive caps; earlier thirds receive remainders."""
    groups = {row['symbol']: 'missing' for row in selected}
    positive = sorted((float(row['market_cap_b']), row['symbol']) for row in selected
                      if row.get('market_cap_b') is not None and isfinite(float(row['market_cap_b']))
                      and float(row['market_cap_b']) > 0)
    size, extra = divmod(len(positive), 3)
    start = 0
    for index, label in enumerate(('small', 'middle', 'large')):
        end = start + size + (index < extra)
        for _, symbol in positive[start:end]:
            groups[symbol] = label
        start = end
    return groups


def row_of(side, record):
    outcome, reverse = record['outcomes'][side], record['outcomes'][-side]
    return {key: record[key] for key in ('symbol', 'day', 'rvol30', 'p10', 'iv', 'sigma_rem',
                                        'rvol30_base', 'rvol30_days')} | {
        'side': side, 'payoff': outcome[0], 'target': outcome[1], 'stop': outcome[2],
        'chop': outcome[3] < p3.CHOP, 'edge': int(outcome[1]) - int(reverse[1]), 'option': None,
        'exit_bar_close': GRID[outcome[4]], 'exit_price': outcome[5],
        'reverse_target': reverse[1], 'reverse_stop': reverse[2], 'reverse_payoff': reverse[0],
        'reverse_exit_bar_close': GRID[reverse[4]], 'reverse_exit_price': reverse[5]}


def gates(result):
    return {'picks>=40': result.get('picks', 0) >= 40,
            'payoff_lo90>0': result.get('payoff_lo90', 0) > 0,
            'edge_lo90>0': result.get('edge_lo90', 0) > 0,
            'target_rate>=30%': result.get('target_rate', 0) >= .30}


def summary(rows):
    by_day = defaultdict(list)
    for row in rows:
        by_day[row['day']].append(row)
    result = p4.summarize(by_day, p4.HALF)
    for key in list(result):
        if key.startswith('option_'):
            del result[key]
    result['reverse_target_rate'] = mean(r['reverse_target'] for r in rows) if rows else None
    result['gates'] = gates(result)
    result['passed'] = all(result['gates'].values())
    return result


def describe(rows):
    return {'picks': len(rows), 'dates': len({r['day'] for r in rows}),
            **{name: mean(r[field] for r in rows) if rows else None for name, field in
               (('target_rate', 'target'), ('stop_rate', 'stop'), ('payoff', 'payoff'), ('edge', 'edge'))}}


def evaluate(root):
    selection, hashes = verified_inputs(root)
    selected = selection['selected']
    metadata = {r['symbol']: r for r in selected}
    if len(metadata) != len(selected):
        raise ValueError('duplicate frozen symbols')
    calendar = {str(row['time'])[:10]: str(row.get('trade_date_type', 'WHOLE')).strip().upper()
                for row in read_json(root / 'calendar.json') if str(row['time'])[:10] <= WINDOW[1]}
    if not calendar or min(calendar) > '2026-05-01' or max(calendar) != WINDOW[1]:
        raise ValueError('calendar must cover 2026-05-01 through the fixed cutoff')
    errors = read_json(root / 'errors.json')
    cap = cap_groups(selected)
    pools = {day: {'universe': len(selected), 'complete': 0, 'eligible': 0, 'triggered': 0,
                   'selected': 0, 'excluded': Counter()} for day in sorted(calendar) if WINDOW[0] <= day <= WINDOW[1]}
    candidates, by_symbol = [], {}
    for symbol, meta in metadata.items():
        weekly, mon_wed = daily_k.schedule(symbol)
        if (weekly, mon_wed) != (meta['weekly'], meta['mon_wed']) or not weekly:
            raise ValueError('expiry snapshot changed: ' + symbol)
        path = root / 'k30' / (symbol + '.json')
        counts = Counter()
        if not path.exists():
            if not any(row.get('stage') == 'minutes' and row.get('code') == meta['code'] for row in errors):
                raise ValueError('unexplained missing minute file: ' + symbol)
            for day in pools:
                pools[day]['excluded']['minute_file_missing'] += 1
                counts['minute_file_missing'] += 1
            by_symbol[symbol] = {'complete_sessions': 0, 'excluded': counts, 'eligible': 0, 'triggered': 0}
            continue
        raw = read_json(path)
        if not isinstance(raw, list) or len(raw) > 1000:
            raise ValueError('expected at most 1000 raw bars: ' + symbol)
        if any(row.get('code') != meta['code'] for row in raw):
            raise ValueError('minute payload contains a different stock: ' + symbol)
        bars, seen = sessions(raw, calendar)
        del raw
        eligible = triggered = 0
        for day, reason, record in features(symbol, bars, seen, calendar, p3.side_tables(symbol)):
            pools[day]['complete'] += day in bars
            if reason:
                pools[day]['excluded'][reason] += 1
                counts[reason] += 1
                continue
            pools[day]['eligible'] += 1
            eligible += 1
            if p3.signal(record, NAME):
                record['outcomes'] = {side: p4.first_touch_from(bars[day], 0, record['p10'], record['sigma_rem'], side)
                                      for side in (1, -1)}
                candidates.append(record)
                pools[day]['triggered'] += 1
                triggered += 1
        by_symbol[symbol] = {'complete_sessions': len(bars), 'excluded': counts,
                             'eligible': eligible, 'triggered': triggered}
        del bars
    rows = []
    for day, picks in sorted(p3.picks(candidates, NAME).items()):
        pools[day]['selected'] = len(picks)
        for rank, (side, record) in enumerate(picks, 1):
            row = row_of(side, record)
            meta = metadata[row['symbol']]
            row.update(rank=rank, code=meta['code'], industry_code=meta['industry_code'],
                       industry_name=meta['industry_name'], market_cap_group=cap[row['symbol']])
            rows.append(row)
    mwf = [r for r in rows if date.fromisoformat(r['day']).weekday() in (0, 2, 4)]
    tradable = [r for r in mwf if (metadata[r['symbol']]['weekly'] if date.fromisoformat(r['day']).weekday() == 4
                                  else metadata[r['symbol']]['mon_wed'])]
    grouped = {}
    for label, key in (('industry', lambda r: r['industry_code']), ('market_cap', lambda r: r['market_cap_group']),
                       ('month', lambda r: r['day'][:7]), ('side', lambda r: str(r['side']))):
        buckets = defaultdict(list)
        for row in rows:
            buckets[key(row)].append(row)
        categories = (sorted({r['industry_code'] for r in selected}) if label == 'industry' else
                      ['small', 'middle', 'large', 'missing'] if label == 'market_cap' else
                      sorted({d[:7] for d in pools}) if label == 'month' else ['1', '-1'])
        grouped[label] = {group: describe(buckets[group]) for group in categories}
    return {'study': 'P5', 'candidate': NAME, 'preregistration_sha256': PREREG_SHA256, 'window': WINDOW,
            'input_sha256': hashes, 'selected_universe': selected, 'market_cap_groups': cap,
            'calendar': calendar, 'collection_errors': errors,
            'filter_order': 'session, 25 prior days, T-1, 14-in-20, IV, nominal close, option volume, turnover, opening baseline',
            'bootstrap': {'draws': p3.DRAWS, 'seed': p3.SEED, 'unit': 'date', 'lo90_quantile': .05},
            'results': {'all_days': summary(rows), 'mon_wed_fri': summary(mwf), 'tradable_0dte': summary(tradable)},
            'subsets_are_filtered_main_top5': True, 'groups_descriptive_only': grouped,
            'industry_universe_counts': dict(Counter(r['industry_code'] for r in selected)),
            'per_date': pools, 'per_symbol': by_symbol, 'signals': rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=Path('data/p5-k30-validation-raw'))
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error('refusing to overwrite ' + str(args.out))
    report = evaluate(args.data)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=1, allow_nan=False)
        handle.write('\n')
    print(json.dumps(report['results'], indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
