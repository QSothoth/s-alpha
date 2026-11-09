"""DV: locate DU full-versus-truncated signal differences without changing the strategy."""
import json
import math
from pathlib import Path
import sys

import numpy as np
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_continue_du import (REPORTS, START, CUT, compute_fields, load_adapter,
                                                             make_data, signature)


def finite(x):
    x = float(x)
    return x if math.isfinite(x) else None


def details(d, f, mask, holding, day, j):
    i = d.di[day]
    c, lo, ph, e9 = (float(d.c[i, j]), float(d.l[i, j]), float(d.h[i - 1, j]), float(d.e9[i, j]))
    v = {'close': finite(c), 'raw': finite(d.A['raw'][i, j]), 'low': finite(lo), 'previous_high': finite(ph),
         'ema9': finite(e9), 'lowe9': finite(f['lowe9'][i, j]), 'cpos': finite(f['cpos'][i, j]),
         'ext21': finite(f['ext21'][i, j]), 'adr_previous': finite(d.adr[i - 1, j]),
         'active': bool(mask[i, j]), 'holding': bool(holding[i, j]),
         'pull': bool(f['lowe9'][i, j] <= .1 and c > e9),
         'breakout': bool(c > ph and f['cpos'][i, j] >= .5)}
    for name, x in (('low_over_close', lo), ('previous_high_over_close', ph), ('ema9_over_close', e9)):
        v[name] = finite(x / c) if c > 0 else None
    return v


def main(mode):
    if mode not in ('cut', 'full'):
        raise ValueError('expected cut or full')
    full_path, cut_path = REPORTS / 'strong_continue_du_full.json', REPORTS / 'strong_continue_du_cut.json'
    full, cut = json.loads(full_path.read_text()), json.loads(cut_path.read_text())
    from studies.trader_replication import martin_continue_du as du
    if full['script_sha256'] != sha(Path(du.__file__)) or cut['full_sha256'] != sha(full_path):
        raise ValueError('DU input fingerprint differs')
    adapter, dt_sha = load_adapter(mode == 'cut')
    if full['dt_report_sha256'] != dt_sha:
        raise ValueError('DT input differs')
    d = make_data(adapter)
    f, mask, holding = compute_fields(d)
    codes = list(map(str, d.A['codes']))
    if codes != full['codes']:
        raise ValueError('codes differ')
    if mode == 'cut':
        cases = []
        for i, day in enumerate(d.days):
            if not START <= day <= CUT:
                continue
            old, new = full['signals'][day], signature(d, f, mask, holding, i)
            before = {item[0]: item[1] for item in old['candidates']}
            after = {item[0]: item[1] for item in new['candidates']}
            for j in sorted(before.keys() | after.keys()):
                if before.get(j) != after.get(j):
                    cases.append({'day': day, 'code': codes[j], 'index': j,
                                  'full_kind': before.get(j), 'cut_kind': after.get(j),
                                  'cut': details(d, f, mask, holding, day, j)})
        if len({c['day'] for c in cases}) != cut['changes'].get('candidate_identity', 0):
            raise AssertionError('candidate difference days do not reproduce DU')
        result = {'du_cut_sha256': sha(cut_path), 'du_full_sha256': sha(full_path), 'cases': cases}
        target = REPORTS / 'strong_continue_dv_cut.json'
    else:
        input_path = REPORTS / 'strong_continue_dv_cut.json'
        result = json.loads(input_path.read_text())
        if result['du_cut_sha256'] != sha(cut_path) or result['du_full_sha256'] != sha(full_path):
            raise ValueError('diagnostic inputs differ')
        actions = adapter.actions()
        for case in result['cases']:
            case['full'] = details(d, f, mask, holding, case['day'], case['index'])
            case['actions'] = [a for a in actions.get(case['code'], []) if case['day'] <= a[0] <= '2026-10-16']
        wanted = {(c['code'], c['day']) for c in result['cases']}
        original = {}
        for code, day, values in adapter.base.rows():
            if (code, day) in wanted:
                original[(code, day)] = values
                if len(original) == len(wanted):
                    break
        if set(original) != wanted:
            raise ValueError('raw case not found in v1 Dataset')
        for case in result['cases']:
            raw = original[(case['code'], case['day'])]
            case['v1_raw_ohlc'] = raw[:4]
            case['v1_raw_cpos'] = (raw[3] - raw[2]) / (raw[1] - raw[2]) if raw[1] > raw[2] else None
        result['diagnostic_cut_sha256'] = sha(input_path)
        target = REPORTS / 'strong_continue_dv.json'
    result['script_sha256'] = sha(Path(__file__))
    target.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print('wrote', target, 'cases', len(result['cases']), flush=True)


if __name__ == '__main__':
    main(sys.argv[1])
