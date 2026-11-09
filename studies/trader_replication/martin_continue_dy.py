"""DY: measure fixed DX outcomes in initial-risk multiples."""
from collections import defaultdict
import json
import math
from pathlib import Path

import numpy as np
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_dw as dw
from studies.trader_replication import martin_continue_dx as dx
from studies.trader_replication.martin_continue_cv import compare_cells
from studies.trader_replication.martin_continue_dk import next_open_outcome
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_list import ema


def risk_return(opening, stop, outcome):
    if outcome['status'] not in ('entered', 'stop_day0') or not (math.isfinite(opening) and opening > stop > 0):
        return None, None
    risk = (opening - stop) / opening
    return risk, None if outcome['ret'] is None else outcome['ret'] / risk


def compare_r(cells):
    out = {m: {'numerator': 0., 'h3_weight': 0, 'other_n': 0, 'unmatched_h3': 0, 'cells': []}
           for m in ('quick', 'return', 'large')}
    for key, groups in sorted(cells.items()):
        for metric in out:
            convert = (lambda x: float(x >= 3)) if metric == 'quick' else ((lambda x: float(x >= 5)) if metric == 'large' else float)
            a = [convert(v) for v in groups['h3']]
            b = [convert(v) for v in groups['other']]
            row = out[metric]
            if not a or not b:
                row['unmatched_h3'] += len(a)
                continue
            am, bm = float(np.mean(a)), float(np.mean(b))
            row['numerator'] += len(a) * (am - bm)
            row['h3_weight'] += len(a)
            row['other_n'] += len(b)
            row['cells'].append({'type': key[0], 'adr_tercile': key[1], 'h3_n': len(a),
                                 'other_n': len(b), 'h3_mean': am, 'other_mean': bm})
    return out


def describe(risk, r):
    values = r
    wins = [v for v in values if v > 0]
    losses = [-v for v in values if v < 0]
    average_win = float(np.mean(wins)) if wins else None
    average_loss = float(np.mean(losses)) if losses else None
    return {'min_risk': min(risk) if risk else None, 'min_r': min(values) if values else None,
            'filled': len(risk), 'mature': len(values), 'wins': len(wins), 'losses': len(losses),
            'zeros': len(values) - len(wins) - len(losses),
            'win_rate': len(wins) / len(values) if values else None,
            'mean_win_r': average_win, 'mean_loss_r': average_loss,
            'payoff_ratio': average_win / average_loss if average_win is not None and average_loss else None,
            'risk_quantiles': np.quantile(risk, [.05, .5, .95]).tolist() if risk else None,
            'risk_under_1pct': sum(x < .01 for x in risk),
            'p95_r': float(np.quantile(values, .95)) if values else None, 'max_r': max(values) if values else None}


def main():
    full_path, cut_path = du.REPORTS / 'strong_continue_dx_full.json', du.REPORTS / 'strong_continue_dx_cut.json'
    prior, cut = json.loads(full_path.read_text()), json.loads(cut_path.read_text())
    if prior['script_sha256'] != sha(Path(dx.__file__)) or cut['full_sha256'] != sha(full_path) or cut['cutoff_differences']:
        raise ValueError('DX inputs differ or failed cutoff')
    adapter, dt_sha = du.load_adapter(False)
    d = du.make_data(adapter)
    f, mask, holding = du.compute_fields(d)
    codes = list(map(str, d.A['codes']))
    if codes != prior['codes']:
        raise ValueError('codes differ from DX')
    f_raw = dict(f)
    f_raw['cpos'] = dw.positions(adapter, d.days, codes)
    e21 = ema(d.c.astype(float), 21).astype(np.float32)
    last, daily = {}, []
    observations = defaultdict(lambda: {'risk': [], 'r': []})
    extremes = defaultdict(lambda: {'low': [], 'high': []})
    dx_days = {r['date']: r for r in prior['daily']}
    for i in range(1, len(d.days) - 1):
        day = d.days[i]
        sig = du.signature(d, f_raw, mask, holding, i)
        kept = dx.spaced(sig['candidates'], i, last)
        if not du.START <= day <= du.END:
            continue
        adr = d.adr[i - 1]
        pool = adr[mask[i] & np.isfinite(adr) & (adr > 0)]
        bounds = np.quantile(pool, [1 / 3, 2 / 3]) if len(pool) else None
        oldcells = {sample: defaultdict(lambda: {'h3': [], 'other': []}) for sample in ('all', 'spaced')}
        rcells = {sample: {scope: defaultdict(lambda: {'h3': [], 'other': []}) for scope in ('all_risk', 'risk_ge_1pct')}
                  for sample in ('all', 'spaced')}
        ids = {c[0] for c in kept}
        for j, kind, stop_ratio in sig['candidates']:
            side = 'h3' if holding[i, j] else 'other'
            stop, opening = stop_ratio * float(d.c[i, j]), float(d.A['open'][i + 1, j])
            outcome = next_open_outcome(d.A['open'][:, j], d.A['high'][:, j], d.A['low'][:, j],
                                        d.A['close'][:, j], e21[:, j], i + 1, stop)
            risk, net_r = risk_return(opening, stop, outcome)
            samples = ('all', 'spaced') if j in ids else ('all',)
            for sample in samples:
                obs = observations[(day[:4], sample, side)]
                if risk is not None:
                    obs['risk'].append(risk)
                if net_r is not None:
                    obs['r'].append(net_r)
                    record = {'day': day, 'entry_day': d.days[i + 1], 'code': codes[j],
                              'open': opening, 'stop': stop, 'risk': risk, 'ret': outcome['ret'],
                              'net_r': net_r, 'status': outcome['status']}
                    tail = extremes[(day[:4], sample, side)]
                    for key, reverse in (('low', False), ('high', True)):
                        tail[key].append(record)
                        tail[key].sort(key=lambda x: (x['net_r'], x['day'], x['code']), reverse=reverse)
                        del tail[key][10:]
            if bounds is None or not np.isfinite(adr[j]) or adr[j] <= 0:
                continue
            cell = (kind, int(np.searchsorted(bounds, adr[j], side='right')))
            for sample in samples:
                oldcells[sample][cell][side].append(outcome)
                if net_r is not None:
                    rcells[sample]['all_risk'][cell][side].append(net_r)
                    if risk >= .01:
                        rcells[sample]['risk_ge_1pct'][cell][side].append(net_r)
        row = {'date': day}
        for sample in ('all', 'spaced'):
            if compare_cells(oldcells[sample]) != dx_days[day][sample]['matched']:
                raise AssertionError('DX daily matched outcome differs: ' + day + ' ' + sample)
            row[sample] = {scope: compare_r(rcells[sample][scope]) for scope in ('all_risk', 'risk_ge_1pct')}
        daily.append(row)
        if len(daily) % 200 == 0:
            print('completed signal days', len(daily), flush=True)
    rng = np.random.default_rng(20261101)
    years = {}
    for year in ('2023', '2024', '2025', '2026'):
        rows = [r for r in daily if r['date'].startswith(year)]
        state = rng.bit_generator.state
        years[year] = {}
        for sample in ('all', 'spaced'):
            result = {'groups': {side: describe(**observations[(year, sample, side)]) for side in ('h3', 'other')},
                      'candidate_status': prior['years'][year][sample]['totals']}
            for side in ('h3', 'other'):
                tail = extremes[(year, sample, side)]
                result['groups'][side]['lowest_r_cases'] = tail['low']
                result['groups'][side]['highest_r_cases'] = tail['high']
            for scope in ('all_risk', 'risk_ge_1pct'):
                rng.bit_generator.state = state
                result[scope] = du.blocks([{'matched': r[sample][scope]} for r in rows], rng)
            years[year][sample] = result
    out = {'dx_full_sha256': sha(full_path), 'dx_cut_sha256': sha(cut_path), 'dt_report_sha256': dt_sha,
           'script_sha256': sha(Path(__file__)), 'years': years, 'daily': daily}
    target = du.REPORTS / 'strong_continue_dy.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
