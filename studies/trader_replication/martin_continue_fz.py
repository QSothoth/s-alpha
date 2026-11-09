"""FZ: independently recompute FY features from truly truncated raw rows."""
from collections import defaultdict
from itertools import groupby
import json
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trader_replication import panels
from studies.trader_replication import martin_continue_fy as fy
from studies.trader_replication.martin_continue_du import REPORTS
from studies.trader_replication.martin_continue_dq import sha
from studies.trend_breakout.panel import factors

CUTS = ('2024-06-28', '2025-09-30', '2026-06-30')


def truncated_return(records, actions, day, old_day):
    rows = [(date, values) for date, values in records if date <= day]
    dates = [date for date, _ in rows]
    if day not in dates or old_day not in dates:
        return None
    closes = np.array([r[3] for _, r in rows], dtype=float)
    adj = factors(closes, np.array(dates), [a for a in actions if a[0] <= day])
    i, j = dates.index(day), dates.index(old_day)
    current, past = closes[i] * adj[i], closes[j] * adj[j]
    if not all(np.isfinite(v) and v > 0 for v in (current, past)):
        return None
    return float(current / past - 1)


def main():
    ref_path = REPORTS / 'strong_continue_fy.json'
    ref = json.loads(ref_path.read_text())
    if ref['script_sha256'] != sha(Path(fy.__file__)):
        raise ValueError('FY source differs')
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if ds.digest() != ref['dataset_digest']:
        raise ValueError('dataset differs')
    stocks = {s['code'] for s in ds.stocks()}
    calendar = sorted({day for code, day, _ in ds.rows() if code in stocks and day <= panels.WINDOW[1]})
    idx = {day: i for i, day in enumerate(calendar)}
    candidates = {day: [r.copy() for r in ref['rows'] if r['signal_day'] == day] for day in CUTS}
    symbols = {r['code'] for day in CUTS for r in candidates[day]}
    actions = ds.actions()
    per_code = defaultdict(list)
    for day in CUTS:
        for row in candidates[day]:
            per_code[row['code']].append((day, row))
    for code, group in groupby(ds.rows(), key=lambda r: r[0]):
        if code not in symbols:
            continue
        records = [(day, values) for _, day, values in group if day <= CUTS[-1]]
        for day, row in per_code[code]:
            old_day = calendar[idx[day] - 126] if idx[day] >= 126 else None
            row['recomputed'] = truncated_return(records, actions.get(code, []), day, old_day)
    summary = {}
    for day in CUTS:
        rows = candidates[day]
        value_mismatch, state_mismatch, max_error = 0, 0, 0.
        ranked = []
        for row in rows:
            original, new = row['momentum126'], row.get('recomputed')
            if (original is None) != (new is None):
                state_mismatch += 1
            elif original is not None:
                error = abs(original - new)
                max_error = max(max_error, error)
                value_mismatch += error > 1e-10
            ranked.append({'code': row['code'], 'momentum126': new, 'strength_high': None})
        fy.label_group(ranked)
        rank_by_code = {r['code']: r['strength_high'] for r in ranked}
        rank_mismatch = sum(r['strength_high'] != rank_by_code[r['code']] for r in rows)
        summary[day] = {'candidates': len(rows), 'known': sum(r['momentum126'] is not None for r in rows),
                        'unknown': sum(r['momentum126'] is None for r in rows),
                        'state_mismatch': state_mismatch, 'value_mismatch': value_mismatch,
                        'max_absolute_error': max_error, 'rank_mismatch': rank_mismatch,
                        'passed': bool(rows) and state_mismatch == value_mismatch == rank_mismatch == 0}
    out = {'dataset_digest': ds.digest(), 'fy_sha256': sha(ref_path),
           'script_sha256': sha(Path(__file__)), 'cuts': summary}
    target = REPORTS / 'strong_continue_fz.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    print('wrote', target, summary, flush=True)


if __name__ == '__main__':
    main()
