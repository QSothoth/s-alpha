"""GB: independently check GA against truly truncated raw OHLC."""
from collections import defaultdict
from itertools import groupby
import json
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trader_replication import panels
from studies.trader_replication import martin_continue_ga as ga
from studies.trader_replication.martin_continue_du import REPORTS
from studies.trader_replication.martin_continue_dq import sha
from studies.trend_breakout.panel import factors

CUTS = ('2024-06-28', '2025-09-30', '2026-06-30')


def truncated_compression(records, actions, days):
    end = days[-1]
    rows = [(date, values) for date, values in records if date <= end]
    dates = [date for date, _ in rows]
    if not all(day in dates for day in days):
        return None
    closes = np.array([r[3] for _, r in rows], dtype=float)
    adj = factors(closes, np.array(dates), [a for a in actions if a[0] <= end])
    highs, lows = [], []
    for day in days:
        i = dates.index(day)
        o, h, l, c = rows[i][1][:4]
        if not all(np.isfinite(v) and v > 0 for v in (o, h, l, c, adj[i])):
            return None
        highs.append(max(o, h, c) * adj[i])
        lows.append(min(o, l, c) * adj[i])
    denom = rows[dates.index(end)][1][3] * adj[dates.index(end)]
    return float((max(highs) - min(lows)) / denom)


def main():
    ref_path = REPORTS / 'strong_continue_ga.json'
    ref = json.loads(ref_path.read_text())
    if ref['script_sha256'] != sha(Path(ga.__file__)):
        raise ValueError('GA source differs')
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if ds.digest() != ref['dataset_digest']:
        raise ValueError('dataset differs')
    stocks = {s['code'] for s in ds.stocks()}
    calendar = sorted({day for code, day, _ in ds.rows() if code in stocks and day <= panels.WINDOW[1]})
    idx = {day: i for i, day in enumerate(calendar)}
    candidates = {day: [r.copy() for r in ref['rows'] if r['signal_day'] == day] for day in CUTS}
    per_code = defaultdict(list)
    for day in CUTS:
        for row in candidates[day]:
            per_code[row['code']].append((day, row))
    actions = ds.actions()
    for code, group in groupby(ds.rows(), key=lambda r: r[0]):
        if code not in per_code:
            continue
        records = [(day, values) for _, day, values in group if day < CUTS[-1]]
        for day, row in per_code[code]:
            t = idx[day]
            row['recomputed'] = truncated_compression(records, actions.get(code, []), calendar[t - 3:t])
    summary = {}
    for day in CUTS:
        rows, ranked = candidates[day], []
        state_mismatch = value_mismatch = 0
        max_error = 0.
        for row in rows:
            original, new = row['compression3'], row.get('recomputed')
            if (original is None) != (new is None):
                state_mismatch += 1
            elif original is not None:
                error = abs(original - new)
                max_error = max(max_error, error)
                value_mismatch += error > 1e-10
            ranked.append({'code': row['code'], 'compression3': new, 'narrow': None})
        ga.label_narrow(ranked)
        rank_by_code = {r['code']: r['narrow'] for r in ranked}
        rank_mismatch = sum(r['narrow'] != rank_by_code[r['code']] for r in rows)
        summary[day] = {'candidates': len(rows), 'known': sum(r['compression3'] is not None for r in rows),
                        'unknown': sum(r['compression3'] is None for r in rows),
                        'state_mismatch': state_mismatch, 'value_mismatch': value_mismatch,
                        'max_absolute_error': max_error, 'rank_mismatch': rank_mismatch,
                        'passed': bool(rows) and state_mismatch == value_mismatch == rank_mismatch == 0}
    out = {'dataset_digest': ds.digest(), 'ga_sha256': sha(ref_path),
           'script_sha256': sha(Path(__file__)), 'cuts': summary}
    target = REPORTS / 'strong_continue_gb.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    print('wrote', target, summary, flush=True)


if __name__ == '__main__':
    main()
