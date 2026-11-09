"""DW: use same-day raw OHLC for the DU close-position threshold."""
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import sys

import numpy as np
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication.martin_continue_bu import trigger
from studies.trader_replication.martin_continue_cv import compare_cells
from studies.trader_replication.martin_continue_dk import next_open_outcome
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_list import ema


def raw_position(values):
    o, high, low, close = values[:4]
    if not all(math.isfinite(x) and x > 0 for x in (o, high, low, close)):
        return float('nan')
    high = max(high, o, close)
    low = min(low, o, close)
    return (close - low) / (high - low) if high > low else float('nan')


def positions(adapter, days, codes):
    di, ci = {day: i for i, day in enumerate(days)}, {code: j for j, code in enumerate(codes)}
    out = np.full((len(days), len(codes)), np.nan, np.float64)
    for code, day, values in adapter.rows():
        if day in di:
            out[di[day], ci[code]] = raw_position(values)
    return out


def compare_signals(a, b):
    changes = Counter()
    for day in a:
        for key in ('active', 'holding'):
            changes[key] += a[day][key] != b[day][key]
        before, after = a[day]['candidates'], b[day]['candidates']
        if [x[:2] for x in before] != [x[:2] for x in after]:
            changes['candidate_identity'] += 1
        elif not np.allclose([x[2] for x in before], [x[2] for x in after], rtol=1e-5, atol=0):
            changes['normalized_stop'] += 1
    return {k: v for k, v in changes.items() if v}


def main(mode):
    if mode not in ('full', 'cut'):
        raise ValueError('expected full or cut')
    full_path = du.REPORTS / 'strong_continue_du_full.json'
    cut_path = du.REPORTS / 'strong_continue_du_cut.json'
    dv_path = du.REPORTS / 'strong_continue_dv.json'
    reference, cut_ref = json.loads(full_path.read_text()), json.loads(cut_path.read_text())
    if reference['script_sha256'] != sha(Path(du.__file__)) or cut_ref['full_sha256'] != sha(full_path):
        raise ValueError('DU references changed')
    adapter, dt_sha = du.load_adapter(mode == 'cut')
    if dt_sha != reference['dt_report_sha256']:
        raise ValueError('DT reference changed')
    d = du.make_data(adapter)
    f, mask, holding = du.compute_fields(d)
    codes = list(map(str, d.A['codes']))
    if codes != reference['codes']:
        raise ValueError('codes differ from DU')
    positions_raw = positions(adapter, d.days, codes)
    f_raw = dict(f)
    f_raw['cpos'] = positions_raw
    old, new = {}, {}
    diffs, missing = Counter(), 0
    for i, day in enumerate(d.days):
        if not du.START <= day <= du.CUT:
            continue
        old[day] = du.signature(d, f, mask, holding, i)
        new[day] = du.signature(d, f_raw, mask, holding, i)
        missing += int(np.isnan(positions_raw[i]).sum())
        a = {x[0]: x[1] for x in old[day]['candidates']}
        b = {x[0]: x[1] for x in new[day]['candidates']}
        for j in a.keys() | b.keys():
            if a.get(j) != b.get(j):
                diffs['h3' if holding[i, j] else 'other'] += 1
    if mode == 'full' and compare_signals(old, reference['signals']):
        raise AssertionError('original DU signals do not reproduce')
    if mode == 'cut' and compare_signals(reference['signals'], old) != cut_ref['changes']:
        raise AssertionError('original DU cutoff changes do not reproduce')
    out = {'du_full_sha256': sha(full_path), 'du_cut_sha256': sha(cut_path), 'dv_sha256': sha(dv_path),
           'script_sha256': sha(Path(__file__)), 'codes': codes, 'signals': new,
           'old_to_new_changed_candidates': dict(diffs), 'missing_raw_positions': missing}
    for code, day in [('US.STX', '2023-11-29'), ('US.JPM', '2023-12-01')]:
        j, i = codes.index(code), d.di[day]
        if positions_raw[i, j] != .5 or not any(x[0] == j and x[1] == 'breakout_only' for x in new[day]['candidates']):
            raise AssertionError('raw boundary case failed: ' + code)
    if mode == 'cut':
        path = du.REPORTS / 'strong_continue_dw_full.json'
        baseline = json.loads(path.read_text())
        if baseline['script_sha256'] != sha(Path(__file__)) or baseline['du_full_sha256'] != sha(full_path):
            raise ValueError('DW full inputs differ')
        out['full_sha256'] = sha(path)
        out['cutoff_differences'] = compare_signals(baseline['signals'], new)
        target = du.REPORTS / 'strong_continue_dw_cut.json'
    else:
        e21 = ema(d.c.astype(float), 21).astype(np.float32)
        daily = []
        for i, day in enumerate(d.days[:-1]):
            if day not in new:
                continue
            adr = d.adr[i - 1]
            pool = adr[mask[i] & np.isfinite(adr) & (adr > 0)]
            bounds = np.quantile(pool, [1 / 3, 2 / 3]) if len(pool) else None
            cells = defaultdict(lambda: {'h3': [], 'other': []})
            totals = {'h3': Counter(), 'other': Counter()}
            for j, kind, stop_ratio in new[day]['candidates']:
                side = 'h3' if holding[i, j] else 'other'
                stop = stop_ratio * float(d.c[i, j])
                outcome = next_open_outcome(d.A['open'][:, j], d.A['high'][:, j], d.A['low'][:, j],
                                            d.A['close'][:, j], e21[:, j], i + 1, stop)
                totals[side]['candidates'] += 1
                totals[side][outcome['status']] += 1
                if bounds is not None and np.isfinite(adr[j]) and adr[j] > 0:
                    cells[(kind, int(np.searchsorted(bounds, adr[j], side='right'))) ][side].append(outcome)
                else:
                    totals[side]['missing_adr'] += 1
            daily.append({'date': day, 'totals': {k: dict(v) for k, v in totals.items()},
                          'matched': compare_cells(cells)})
        out['daily'] = daily
        out['matched'] = du.blocks(daily, np.random.default_rng(20261101))
        out['original_matched'] = reference['years']['2023']['matched']
        target = du.REPORTS / 'strong_continue_dw_full.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    print('wrote', target, 'changed candidates', dict(diffs), flush=True)


if __name__ == '__main__':
    main(sys.argv[1])
