"""DZ: audit opening/stop precision and fee-inclusive initial risk."""
from collections import Counter, defaultdict
import json
import math
from pathlib import Path

import numpy as np
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_dw as dw
from studies.trader_replication import martin_continue_dx as dx
from studies.trader_replication import martin_continue_dy as dy
from studies.trader_replication.martin_continue_dk import next_open_outcome
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_list import ema


def precision_unknown(opening, stop, outcome):
    return (outcome['status'] in ('entered', 'stop_day0') and math.isfinite(opening) and opening > stop > 0
            and np.float32(opening) == np.float32(stop))


def fee_risk(opening, stop):
    return (opening * 1.0005 - stop * .9995) / opening


def main():
    old_path, dx_path = du.REPORTS / 'strong_continue_dy.json', du.REPORTS / 'strong_continue_dx_full.json'
    old, old_dx = json.loads(old_path.read_text()), json.loads(dx_path.read_text())
    if old['script_sha256'] != sha(Path(dy.__file__)) or old['dx_full_sha256'] != sha(dx_path):
        raise ValueError('DY input changed')
    adapter, dt_sha = du.load_adapter(False)
    d = du.make_data(adapter)
    f, mask, holding = du.compute_fields(d)
    codes = list(map(str, d.A['codes']))
    if codes != old_dx['codes']:
        raise ValueError('codes differ from DX')
    f_raw = dict(f)
    f_raw['cpos'] = dw.positions(adapter, d.days, codes)
    e21 = ema(d.c.astype(float), 21).astype(np.float32)
    last, daily, ambiguous = {}, [], []
    groups = defaultdict(lambda: {'risk': [], 'r': []})
    ref_days = {r['date']: r for r in old['daily']}
    for i in range(1, len(d.days) - 1):
        day = d.days[i]
        sig = du.signature(d, f_raw, mask, holding, i)
        kept = dx.spaced(sig['candidates'], i, last)
        if not du.START <= day <= du.END:
            continue
        adr = d.adr[i - 1]
        pool = adr[mask[i] & np.isfinite(adr) & (adr > 0)]
        bounds = np.quantile(pool, [1 / 3, 2 / 3]) if len(pool) else None
        kinds = ('dy_all', 'dy_risk_ge_1pct', 'price_distinct', 'cost_all', 'cost_price_distinct')
        cells = {sample: {kind: defaultdict(lambda: {'h3': [], 'other': []}) for kind in kinds}
                 for sample in ('all', 'spaced')}
        totals = {sample: {'h3': Counter(), 'other': Counter()} for sample in ('all', 'spaced')}
        ids = {c[0] for c in kept}
        for j, kind, stop_ratio in sig['candidates']:
            side = 'h3' if holding[i, j] else 'other'
            stop, opening = stop_ratio * float(d.c[i, j]), float(d.A['open'][i + 1, j])
            outcome = next_open_outcome(d.A['open'][:, j], d.A['high'][:, j], d.A['low'][:, j],
                                        d.A['close'][:, j], e21[:, j], i + 1, stop)
            risk, old_r = dy.risk_return(opening, stop, outcome)
            uncertain = precision_unknown(opening, stop, outcome)
            new_risk = fee_risk(opening, stop) if risk is not None else None
            new_r = outcome['ret'] / new_risk if outcome['ret'] is not None and new_risk is not None else None
            samples = ('all', 'spaced') if j in ids else ('all',)
            if uncertain:
                ambiguous.append({'day': day, 'entry_day': d.days[i + 1], 'code': codes[j], 'side': side,
                                  'spaced': j in ids, 'opening': opening, 'stop': stop, 'risk': risk,
                                  'status': outcome['status'], 'ret': outcome['ret'], 'old_r': old_r, 'fee_r': new_r})
            for sample in samples:
                t = totals[sample][side]
                t['candidates'] += 1
                t[outcome['status']] += 1
                t['precision_unknown'] += int(uncertain)
                for scope in ('cost_all', 'cost_price_distinct'):
                    if scope == 'cost_price_distinct' and uncertain:
                        continue
                    obs = groups[(day[:4], sample, scope, side)]
                    if new_risk is not None:
                        obs['risk'].append(new_risk)
                    if new_r is not None:
                        obs['r'].append(new_r)
            if bounds is None or not np.isfinite(adr[j]) or adr[j] <= 0 or old_r is None:
                continue
            cell = (kind, int(np.searchsorted(bounds, adr[j], side='right')))
            for sample in samples:
                cells[sample]['dy_all'][cell][side].append(old_r)
                if risk >= .01:
                    cells[sample]['dy_risk_ge_1pct'][cell][side].append(old_r)
                cells[sample]['cost_all'][cell][side].append(new_r)
                if not uncertain:
                    cells[sample]['price_distinct'][cell][side].append(old_r)
                    cells[sample]['cost_price_distinct'][cell][side].append(new_r)
        row = {'date': day}
        for sample in ('all', 'spaced'):
            matched = {kind: dy.compare_r(cells[sample][kind]) for kind in kinds}
            if (matched['dy_all'] != ref_days[day][sample]['all_risk'] or
                    matched['dy_risk_ge_1pct'] != ref_days[day][sample]['risk_ge_1pct']):
                raise AssertionError('DY daily R results differ ' + day + ' ' + sample)
            row[sample] = {'matched': matched, 'totals': {side: dict(t) for side, t in totals[sample].items()}}
        daily.append(row)
        if len(daily) % 200 == 0:
            print('completed signal days', len(daily), flush=True)
    rng, years = np.random.default_rng(20261101), {}
    for year in ('2023', '2024', '2025', '2026'):
        rows = [r for r in daily if r['date'].startswith(year)]
        state = rng.bit_generator.state
        years[year] = {}
        for sample in ('all', 'spaced'):
            x = {'totals': {}, 'groups': {}, 'matched': {}}
            for side in ('h3', 'other'):
                c = Counter()
                for row in rows:
                    c.update(row[sample]['totals'][side])
                x['totals'][side] = dict(c)
            for scope in ('cost_all', 'cost_price_distinct'):
                x['groups'][scope] = {side: dy.describe(**groups[(year, sample, scope, side)]) for side in ('h3', 'other')}
            for kind in kinds:
                rng.bit_generator.state = state
                x['matched'][kind] = du.blocks([{'matched': r[sample]['matched'][kind]} for r in rows], rng)
            for kind, prior_kind in (('dy_all', 'all_risk'), ('dy_risk_ge_1pct', 'risk_ge_1pct')):
                if x['matched'][kind] != old['years'][year][sample][prior_kind]:
                    raise AssertionError('DY annual R results differ ' + year + ' ' + sample)
            years[year][sample] = x
    out = {'dy_sha256': sha(old_path), 'dx_sha256': sha(dx_path), 'dt_report_sha256': dt_sha,
           'script_sha256': sha(Path(__file__)), 'ambiguous': ambiguous, 'years': years, 'daily': daily}
    target = du.REPORTS / 'strong_continue_dz.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    print('wrote', target, 'precision_unknown', len(ambiguous), flush=True)


if __name__ == '__main__':
    main()
