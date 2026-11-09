"""FU: diagnose post-stop opportunity without changing account trades."""
from collections import Counter, defaultdict
from itertools import groupby
import json
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trader_replication import panels
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_continue_du import REPORTS
from studies.trend_breakout.panel import factors

COST = .0005
HORIZON = 20


def path_outcome(calendar, bars, entry_day, stop, multiplier):
    """Classify a target reached after day zero before a hypothetical 2R stop."""
    if entry_day not in bars:
        return 'unknown', 'missing_entry'
    op, high, low, close = bars[entry_day]
    if not valid_bar(op, high, low, close) or not np.isfinite(stop) or stop <= 0:
        return 'unknown', 'invalid_entry'
    if np.float32(op) == np.float32(stop) or np.float32(low) == np.float32(stop):
        return 'unknown', 'entry_precision'
    if not op > stop or not low < stop:
        raise ValueError('day-zero stop inconsistent with saved account')
    risk = op - stop
    wide = op - 2 * risk
    if wide <= 0:
        return 'unknown', 'nonpositive_wide_stop'
    if np.float32(low) == np.float32(wide):
        return 'unknown', 'wide_precision'
    if low < wide:
        return 'miss', 'entry_wide_stop'
    net_risk = op * (1 + COST) - stop * (1 - COST)
    target = (op * (1 + COST) + multiplier * net_risk) / (1 - COST)
    start = calendar.index(entry_day) + 1
    for day in calendar[start:start + HORIZON]:
        if day not in bars:
            return 'unknown', 'missing_bar'
        o, h, l, c = bars[day]
        if not valid_bar(o, h, l, c):
            return 'unknown', 'invalid_bar'
        if np.float32(o) in (np.float32(wide), np.float32(target)):
            return 'unknown', 'opening_precision'
        if o < wide:
            return 'miss', 'gap_wide_stop'
        if o > target:
            return 'hit', 'gap_target'
        if np.float32(l) == np.float32(wide) or np.float32(h) == np.float32(target):
            return 'unknown', 'intraday_precision'
        stopped, reached = l < wide, h > target
        if stopped and reached:
            return 'ambiguous', 'same_day_both'
        if stopped:
            return 'miss', 'wide_stop'
        if reached:
            return 'hit', 'target'
    if len(calendar) - start < HORIZON:
        return 'unknown', 'unmatured'
    return 'miss', 'horizon'


def valid_bar(o, h, l, c):
    return all(np.isfinite(x) and x > 0 for x in (o, h, l, c)) and l <= min(o, c) and h >= max(o, c)


def adjusted_bars(records, actions):
    days = np.array([day for day, _ in records])
    values = np.array([values for _, values in records], dtype=float)
    adjust = factors(values[:, 3], days, actions)
    result = {}
    for day, row, factor in zip(days, values, adjust):
        o, h, l, c = (float(np.float32(x * factor)) for x in row[:4])
        h, l = float(np.fmax(h, np.fmax(o, c))), float(np.fmin(l, np.fmin(o, c)))
        result[str(day)] = (o, h, l, c)
    return result


def main():
    ft_path, fj_path = REPORTS / 'strong_continue_ft.json', REPORTS / 'strong_continue_fj.json'
    ft, fj = json.loads(ft_path.read_text()), json.loads(fj_path.read_text())
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    digest = ds.digest()
    if digest != ft['dataset_digest'] or digest != fj['dataset_digest']:
        raise ValueError('dataset digest differs')
    selected = {}
    for row in fj['rows']:
        if row['selected']:
            key = (row['entry_day'], row['code'])
            if key in selected:
                raise ValueError('duplicate selected FJ key')
            selected[key] = row
    targets = defaultdict(list)
    for account in ('FO1', 'FQ1'):
        seen = set()
        for code, side, kind, entry, exit_day, why in ft['results'][account]['trade_keys']:
            if side != 1 or kind != 'n1' or why != 'stop_day0':
                continue
            key = (entry, code)
            if key in seen or exit_day != entry:
                raise ValueError('duplicate key or non-day-zero exit')
            seen.add(key)
            match = selected.get(key)
            if match is None or match['status'] != 'filled':
                raise ValueError(f'no matching filled FJ order: {key}')
            targets[code].append((account, entry, match['stop']))
    del ft, fj, selected
    calendar = sorted({day for _, day, _ in ds.rows() if panels.WINDOW[0] <= day <= panels.WINDOW[1]})
    actions, output, found = ds.actions(), [], set()
    for code, group in groupby(ds.rows(), key=lambda row: row[0]):
        if code not in targets:
            continue
        found.add(code)
        records = [(day, values) for _, day, values in group]
        bars = adjusted_bars(records, actions.get(code, []))
        for account, entry, stop in targets[code]:
            row = {'account': account, 'code': code, 'entry': entry, 'stop': stop}
            for n in (3, 5):
                row[f'r{n}'], row[f'r{n}_reason'] = path_outcome(calendar, bars, entry, stop, n)
            output.append(row)
    if found != set(targets):
        raise ValueError('missing symbols in dataset')
    output.sort(key=lambda r: (r['account'], r['entry'], r['code']))
    summary = {}
    for account in ('FO1', 'FQ1'):
        summary[account] = {}
        for year in ('2024', '2025', '2026'):
            rows = [r for r in output if r['account'] == account and r['entry'].startswith(year)]
            metrics = {}
            for n in (3, 5):
                counts = Counter(r[f'r{n}'] for r in rows)
                total = len(rows)
                metrics[f'r{n}'] = {'counts': dict(counts),
                    'reasons': dict(Counter(r[f'r{n}_reason'] for r in rows)),
                    'lower': counts['hit'] / total if total else None,
                    'upper': (counts['hit'] + counts['unknown'] + counts['ambiguous']) / total if total else None}
            summary[account][year] = {'total': len(rows), **metrics}
    result = {'dataset_digest': digest, 'ft_sha256': sha(ft_path), 'fj_sha256': sha(fj_path),
              'script_sha256': sha(Path(__file__)), 'horizon': HORIZON, 'cost': COST,
              'window_end': panels.WINDOW[1], 'summary': summary, 'rows': output}
    target = REPORTS / 'strong_continue_fu.json'
    target.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    print('wrote', target, 'rows', len(output), flush=True)


if __name__ == '__main__':
    main()
