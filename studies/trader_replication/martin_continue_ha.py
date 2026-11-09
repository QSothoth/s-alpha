"""HA: quantify opening-risk drift for already executed long entries."""
from collections import Counter, defaultdict
from itertools import groupby
import json
from pathlib import Path

import numpy as np

from studies import trader_data
from studies.trader_replication import martin_continue_fj as fj
from studies.trader_replication import martin_continue_gw as gw
from studies.trader_replication import martin_continue_gz as gz
from studies.trader_replication import panels, system
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_continue_du import REPORTS
from studies.trend_breakout.panel import factors


def risk_drift(previous, opening, stop):
    if previous is None or not np.isfinite(previous) or previous <= 0:
        return {'status': 'missing_previous'}
    if np.float32(previous) == np.float32(stop):
        return {'status': 'previous_stop_precision_unknown'}
    if previous <= stop:
        return {'status': 'previous_not_above_stop'}
    if not np.isfinite(opening) or opening <= stop:
        raise ValueError('invalid recorded long opening')
    gap = opening / previous - 1
    ratio = (opening - stop) / (previous - stop)
    return {'status': 'known', 'gap': float(gap), 'risk_ratio': float(ratio)}


def describe(rows):
    status = Counter(r['status'] for r in rows)
    known = [r for r in rows if r['status'] == 'known']
    out = {'entries': len(rows), 'status': dict(status), 'known': len(known)}
    if known:
        gap = np.array([r['gap'] for r in known])
        risk = np.array([r['risk_ratio'] for r in known])
        out.update(gap_quantiles=[float(x) for x in np.quantile(gap, [.1, .5, .9])],
                   risk_quantiles=[float(x) for x in np.quantile(risk, [.1, .5, .9])],
                   gap_up_over_1pct=int(np.sum(gap > .01)), gap_down_over_1pct=int(np.sum(gap < -.01)),
                   risk_at_least_double=int(np.sum(risk >= 2)), risk_at_most_half=int(np.sum(risk <= .5)))
    return out


def main():
    p_fj, p_gw, p_gz = (REPORTS / f'strong_continue_{name}.json' for name in ('fj', 'gw', 'gz'))
    f, w, z = (json.loads(p.read_text()) for p in (p_fj, p_gw, p_gz))
    old_system = REPORTS / 'source_pins/system_pre_gz.py.txt'
    if (f['script_sha256'] != sha(Path(fj.__file__)) or w['script_sha256'] != sha(Path(gw.__file__)) or
            w['system_sha256'] != sha(old_system) or z['script_sha256'] != sha(Path(gz.__file__)) or
            z['system_sha256'] != sha(Path(system.__file__))):
        raise ValueError('reference source differs')
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    data_digest = ds.digest()
    if any(x['dataset_digest'] != data_digest for x in (f, w, z)):
        raise ValueError('frozen data differs')
    candidates = {}
    for row in f['rows']:
        k = (row['entry_day'], row['code'])
        if k in candidates:
            raise AssertionError('duplicate original core candidate')
        candidates[k] = row
    samples = {}
    for scenario in ('hit', 'nohit'):
        entries = []
        for code, side, kind, entry, _, _ in w['results']['C0:' + scenario]['trade_keys']:
            if side != 1 or kind != 'n1':
                raise AssertionError('cash core contains other kinds')
            row = candidates[(entry, code)]
            if not row['selected'] or row['status'] != 'filled':
                raise AssertionError('cash entry not in original fillable selection')
            entries.append({'day': entry, 'code': code, 'kind': kind, 'stop': row['stop'], 'fill': None})
        samples['C0:' + scenario] = entries
        samples['L0:' + scenario] = [dict(day=r['day'], code=r['code'], kind=r['kind'], stop=r['stop'], fill=r['fill'])
                                     for r in z['feedback_traces']['L0:' + scenario + ':prior']['entries']
                                     if r['side'] == 1]
        for row in samples['L0:' + scenario]:
            if row['kind'] == 'n1':
                old = candidates[(row['day'], row['code'])]
                if not old['selected'] or old['status'] != 'filled' or abs(old['stop'] - row['stop']) > 1e-8:
                    raise AssertionError('leveraged core differs from original candidate')
            elif row['kind'] != 'list':
                raise AssertionError('unexpected leveraged kind')
    del f, w, z, candidates
    for name, rows in samples.items():
        keys = [(r['day'], r['code'], r['kind']) for r in rows]
        if len(keys) != len(set(keys)):
            raise AssertionError('duplicate entry key: ' + name)
    stocks = {s['code'] for s in ds.stocks()}
    calendar = sorted({day for code, day, _ in ds.rows() if code in stocks and day <= panels.WINDOW[1]})
    prior = {calendar[i]: calendar[i - 1] for i in range(1, len(calendar))}
    by_code = defaultdict(list)
    for name, rows in samples.items():
        for row in rows:
            if row['day'] not in prior:
                raise AssertionError('previous session not in calendar')
            by_code[row['code']].append(row)
    acts, seen = ds.actions(), set()
    for code, group in groupby(ds.rows(), key=lambda r: r[0]):
        if code not in by_code:
            continue
        seen.add(code)
        records = [(day, values) for _, day, values in group]
        dates = np.array([r[0] for r in records])
        raw = np.array([r[1] for r in records], dtype=float)
        adjusted = factors(raw[:, 3], dates, acts.get(code, []))
        indices = {day: i for i, day in enumerate(dates)}
        for row in by_code[code]:
            i, j = indices.get(row['day']), indices.get(prior[row['day']])
            if i is None:
                raise AssertionError('actual entry has no bar')
            opening = float(np.float32(raw[i, 0] * adjusted[i]))
            previous = float(np.float32(raw[j, 3] * adjusted[j])) if j is not None else None
            if row['fill'] is not None and row['fill'] != opening:
                raise AssertionError('stored fill differs from rebuilt open: ' + str((row['day'], code)))
            row.update(fill=opening, prior_day=prior[row['day']], previous_close=previous,
                       **risk_drift(previous, opening, row['stop']))
    if seen != set(by_code):
        raise AssertionError('actual entry code absent from frozen dataset')
    summary = {}
    for name, rows in samples.items():
        summary[name] = {}
        for year in ('2024', '2025', '2026'):
            summary[name][year] = {kind: describe([r for r in rows if r['day'].startswith(year)
                                                   and (kind == 'all' or r['kind'] == kind)])
                                   for kind in ('all', 'n1', 'list')}
    out = {'dataset_digest': data_digest, 'fj_sha256': sha(p_fj), 'gw_sha256': sha(p_gw),
           'gz_sha256': sha(p_gz), 'system_sha256': sha(Path(system.__file__)),
           'script_sha256': sha(Path(__file__)), 'summary': summary, 'entries': samples}
    target = REPORTS / 'strong_continue_ha.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
