"""DX: fixed 21-session spacing for the DW next-open candidate comparison."""
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

import numpy as np
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_dw as dw
from studies.trader_replication.martin_continue_cv import compare_cells
from studies.trader_replication.martin_continue_dk import next_open_outcome
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_list import ema


def spaced(candidates, day_index, last):
    selected = []
    for candidate in candidates:
        j = candidate[0]
        if j not in last or day_index - last[j] >= 21:
            selected.append(candidate)
            last[j] = day_index
    return selected


def main(mode):
    if mode not in ('full', 'cut'):
        raise ValueError('expected full or cut')
    full_path = du.REPORTS / 'strong_continue_du_full.json'
    dw_path = du.REPORTS / 'strong_continue_dw_full.json'
    dw_cut = du.REPORTS / 'strong_continue_dw_cut.json'
    dw_full, dw_short = json.loads(dw_path.read_text()), json.loads(dw_cut.read_text())
    if (dw_full['script_sha256'] != sha(Path(dw.__file__)) or dw_short['full_sha256'] != sha(dw_path)
            or dw_short['cutoff_differences'] or dw_full['du_full_sha256'] != sha(full_path)):
        raise ValueError('DW references differ or failed cutoff')
    adapter, dt_sha = du.load_adapter(mode == 'cut')
    if dt_sha != json.loads(full_path.read_text())['dt_report_sha256']:
        raise ValueError('DT reference changed')
    d = du.make_data(adapter)
    f, mask, holding = du.compute_fields(d)
    codes = list(map(str, d.A['codes']))
    if codes != dw_full['codes']:
        raise ValueError('codes differ')
    f_raw = dict(f)
    f_raw['cpos'] = dw.positions(adapter, d.days, codes)
    e21 = ema(d.c.astype(float), 21).astype(np.float32) if mode == 'full' else None
    last, daily, selected_2023, selection_history = {}, [], {}, []
    names = defaultdict(set)
    for i in range(1, len(d.days)):
        date = d.days[i]
        sig = du.signature(d, f_raw, mask, holding, i)
        kept = spaced(sig['candidates'], i, last)
        selection_history.extend((int(j), i) for j, _, _ in kept)
        if du.START <= date <= du.CUT:
            if sig != dw_full['signals'][date] and mode == 'full':
                raise AssertionError('DW original signals differ: ' + date)
            selected_2023[date] = {'active': sig['active'], 'holding': sig['holding'], 'candidates': kept}
        if mode == 'cut' or not du.START <= date <= du.END or i + 1 >= len(d.days):
            continue
        adr = d.adr[i - 1]
        p = adr[mask[i] & np.isfinite(adr) & (adr > 0)]
        bounds = np.quantile(p, [1 / 3, 2 / 3]) if len(p) else None
        all_cells = defaultdict(lambda: {'h3': [], 'other': []})
        kept_cells = defaultdict(lambda: {'h3': [], 'other': []})
        totals = {sample: {'h3': Counter(), 'other': Counter()} for sample in ('all', 'spaced')}
        selected_ids = {c[0] for c in kept}
        for j, kind, stop_ratio in sig['candidates']:
            side = 'h3' if holding[i, j] else 'other'
            stop = stop_ratio * float(d.c[i, j])
            o = next_open_outcome(d.A['open'][:, j], d.A['high'][:, j], d.A['low'][:, j],
                                  d.A['close'][:, j], e21[:, j], i + 1, stop)
            samples = ('all', 'spaced') if j in selected_ids else ('all',)
            for sample in samples:
                t = totals[sample][side]
                t['candidates'] += 1
                t[o['status']] += 1
                t['quick_known'] += o['quick'] is not None
                t['final_known'] += o['ret'] is not None
                names[(date[:4], sample, side)].add(codes[j])
            if bounds is not None and np.isfinite(adr[j]) and adr[j] > 0:
                cell = (kind, int(np.searchsorted(bounds, adr[j], side='right')))
                all_cells[cell][side].append(o)
                if j in selected_ids:
                    kept_cells[cell][side].append(o)
            else:
                for sample in samples:
                    totals[sample][side]['missing_adr'] += 1
        daily.append({'date': date, 'entry_date': d.days[i + 1],
                      'all': {'totals': {s: dict(v) for s, v in totals['all'].items()}, 'matched': compare_cells(all_cells)},
                      'spaced': {'totals': {s: dict(v) for s, v in totals['spaced'].items()}, 'matched': compare_cells(kept_cells)}})
    previous = {}
    for j, i in selection_history:
        if j in previous and i - previous[j] < 21:
            raise AssertionError('spacing violation for ' + codes[j])
        previous[j] = i
    out = {'selection_history': selection_history, 'du_full_sha256': sha(full_path), 'dw_full_sha256': sha(dw_path), 'dw_cut_sha256': sha(dw_cut),
           'script_sha256': sha(Path(__file__)), 'codes': codes, 'signals_2023': selected_2023}
    if mode == 'cut':
        full = du.REPORTS / 'strong_continue_dx_full.json'
        prior = json.loads(full.read_text())
        if prior['script_sha256'] != out['script_sha256'] or prior['dw_full_sha256'] != out['dw_full_sha256']:
            raise ValueError('DX full input differs')
        out['full_sha256'] = sha(full)
        out['cutoff_differences'] = dw.compare_signals(prior['signals_2023'], selected_2023)
        target = du.REPORTS / 'strong_continue_dx_cut.json'
    else:
        dw_days = {r['date']: r for r in dw_full['daily']}
        for row in daily:
            if row['date'] in dw_days and row['all']['matched'] != dw_days[row['date']]['matched']:
                raise AssertionError('DW matched values differ: ' + row['date'])
        rng = np.random.default_rng(20261101)
        years = {}
        for year in ('2023', '2024', '2025', '2026'):
            subset = [r for r in daily if r['date'].startswith(year)]
            y = {}
            rng_state = rng.bit_generator.state
            for sample in ('all', 'spaced'):
                rng.bit_generator.state = rng_state
                rows = [{'matched': r[sample]['matched']} for r in subset]
                totals = {}
                for side in ('h3', 'other'):
                    t = Counter()
                    for r in subset:
                        t.update(r[sample]['totals'][side])
                    totals[side] = dict(t)
                    totals[side]['unique_codes'] = len(names[(year, sample, side)])
                y[sample] = {'totals': totals, 'matched': du.blocks(rows, rng)}
            years[year] = y
        # Use the same seed and draw order as DW for its original 2023 benchmark.
        dw_matched = du.blocks([{'matched': r['all']['matched']} for r in daily if r['date'].startswith('2023')],
                               np.random.default_rng(20261101))
        if dw_matched != dw_full['matched']:
            raise AssertionError('DW annual matched results differ')
        out['daily'], out['years'] = daily, years
        target = du.REPORTS / 'strong_continue_dx_full.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main(sys.argv[1])
