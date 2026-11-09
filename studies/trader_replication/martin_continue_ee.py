"""EE: build the 250-session fast-move feature from as-of raw closes and actions."""
from collections import Counter
import gc
from itertools import groupby
import json
from pathlib import Path
import sys

import numpy as np
from studies import trader_data
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_dw as dw
from studies.trader_replication import martin_continue_dx as dx
from studies.trader_replication import martin_continue_ea as ea
from studies.trader_replication.martin_continue_bv import daily_name_score
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import HOLD, hold_sim


def fast_events(days, closes, actions, indices):
    """Current/previous raw close in the current session's action basis; no later actions."""
    days = np.asarray(days)
    prices = np.asarray(closes, dtype=float)
    step = np.ones(len(prices), dtype=float)
    for ex_date, a, b in actions:
        k = int(np.searchsorted(days, ex_date))
        if 0 < k < len(prices):
            prev = prices[k - 1]
            if not np.isfinite(prev) or prev <= 0:
                step[k] = np.nan
            else:
                step[k] *= (a * prev + b) / prev
    out = np.zeros(len(prices), dtype=bool)
    if len(prices) < 2:
        return out
    denominator = prices[:-1] * step[1:]
    valid = ((np.diff(indices) == 1) & np.isfinite(prices[1:]) & (prices[1:] > 0) &
             np.isfinite(denominator) & (denominator > 0))
    with np.errstate(invalid='ignore', divide='ignore'):
        out[1:] = valid & (np.abs(prices[1:] / denominator - 1) >= .05)
    return out


def source_inputs(dataset, days, codes):
    di, ci = {day: i for i, day in enumerate(days)}, {code: j for j, code in enumerate(codes)}
    events = np.zeros((len(days), len(codes)), dtype=bool)
    positions = np.full((len(days), len(codes)), np.nan, dtype=np.float64)
    actions = dataset.actions()
    seen = set()
    for code, group in groupby(dataset.rows(), key=lambda row: row[0]):
        if code not in ci:
            continue
        if code in seen:
            raise ValueError('dataset rows not grouped: ' + code)
        seen.add(code)
        rows = [(day, values) for _, day, values in group if day in di]
        if not rows:
            continue
        dates = [day for day, _ in rows]
        if any(dates[k] >= dates[k + 1] for k in range(len(dates) - 1)):
            raise ValueError('duplicate or unordered day: ' + code)
        idx = np.array([di[day] for day in dates], dtype=np.int32)
        close = [values[3] for _, values in rows]
        j = ci[code]
        events[idx, j] = fast_events(dates, close, actions.get(code, []), idx)
        positions[idx, j] = [dw.raw_position(values) for _, values in rows]
    return events, positions


def main(mode):
    if mode not in ('full', 'cut'):
        raise ValueError('expected full or cut')
    ea_path = du.REPORTS / 'strong_continue_ea_full.json'
    ea_cut_path = du.REPORTS / 'strong_continue_ea_cut.json'
    original = json.loads(ea_path.read_text())
    base = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    base_digest = base.digest()
    if original['dataset_digest'] != base_digest or original['script_sha256'] != sha(Path(ea.__file__)):
        raise ValueError('EA inputs differ')
    codes = original['codes']
    ea_audit = original['audit']['2024-07-26']['all'] if mode == 'full' else None
    del original
    gc.collect()
    dataset = ea.LimitedDataset(base, ea.CUT) if mode == 'cut' else base
    d = du.make_data(dataset)
    fields, mask, old_holding = du.compute_fields(d)
    if codes != list(map(str, d.A['codes'])):
        raise ValueError('codes differ')
    if mode == 'cut' and d.days[-1] != ea.CUT:
        raise ValueError('not a real cutoff')
    if ea_audit is not None:
        idx = d.di['2024-07-26']
        if np.flatnonzero(old_holding[idx]).tolist() != ea_audit['holding']:
            raise AssertionError('EA first H3 split does not reproduce')
    events, raw_position = source_inputs(dataset, d.days, codes)
    with np.errstate(divide='ignore', invalid='ignore'):
        old_events = np.zeros(d.c.shape, dtype=bool)
        old_events[1:] = np.abs(d.c[1:] / d.c[:-1] - 1) >= .05
    count_events, count_fast = Counter(), Counter()
    new_fast = np.empty(events.shape, dtype=np.float32)
    for start in range(0, events.shape[1], 64):
        sl = slice(start, start + 64)
        new_fast[:, sl] = du._ROLL_MEAN(events[:, sl].astype(np.float32), 250)
    old_fast = fields['fast250']
    for i, day in enumerate(d.days):
        if ea.START <= day <= (ea.CUT if mode == 'cut' else ea.END):
            count_events[day[:4]] += int(np.count_nonzero(events[i] != old_events[i]))
            a, b = old_fast[i], new_fast[i]
            count_fast[day[:4]] += int(np.count_nonzero((a != b) & ~(np.isnan(a) & np.isnan(b))))
    fields['fast250'] = new_fast
    del old_events, old_fast, new_fast
    gc.collect()
    score = daily_name_score(fields, mask, HOLD['H3'])
    new_holding = hold_sim(score, 12, 36)
    del score
    fields['cpos'] = raw_position
    last, audit, daily = {}, {}, []
    for i in range(1, len(d.days)):
        day = d.days[i]
        sig = du.signature(d, fields, mask, new_holding, i)
        kept = dx.spaced(sig['candidates'], i, last)
        if ea.START <= day <= ea.CUT:
            audit[day] = {'all': sig, 'spaced': {'active': sig['active'], 'holding': sig['holding'], 'candidates': kept}}
        if ea.START <= day <= (ea.CUT if mode == 'cut' else ea.END):
            changed = old_holding[i] != new_holding[i]
            candidate_change = sum(bool(changed[row[0]]) for row in sig['candidates'])
            daily.append({'date': day, 'holding_name_changes': int(np.count_nonzero(changed)),
                          'candidate_group_changes': int(candidate_change)})
    boundary = {}
    for code, day in (('US.SIRI', '2024-07-24'), ('US.USB', '2023-09-13')):
        boundary[code + ':' + day] = bool(events[d.di[day], codes.index(code)])
    out = {'ea_full_sha256': sha(ea_path), 'ea_cut_sha256': sha(ea_cut_path),
           'dataset_digest': base_digest, 'script_sha256': sha(Path(__file__)), 'codes': codes,
           'boundary_events': boundary, 'events_changed_by_year': dict(count_events),
           'fast250_changed_by_year': dict(count_fast), 'daily_changes': daily, 'audit': audit}
    if mode == 'cut':
        del d, fields, mask, old_holding, new_holding, events, raw_position
        gc.collect()
        full_path = du.REPORTS / 'strong_continue_ee_full.json'
        full = json.loads(full_path.read_text())
        if (full['script_sha256'] != out['script_sha256'] or full['dataset_digest'] != base_digest or
                full['codes'] != codes or set(full['audit']) != set(audit)):
            raise ValueError('EE full inputs differ')
        out['full_sha256'] = sha(full_path)
        out['cutoff_differences'] = {sample: dw.compare_signals({k: v[sample] for k, v in full['audit'].items()},
                                                               {k: v[sample] for k, v in audit.items()})
                                     for sample in ('all', 'spaced')}
        target = du.REPORTS / 'strong_continue_ee_cut.json'
    else:
        target = du.REPORTS / 'strong_continue_ee_full.json'
    with target.open('w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        f.write('\n')
    print('wrote', target, 'events', dict(count_events), 'boundary', boundary, flush=True)


if __name__ == '__main__':
    main(sys.argv[1])
