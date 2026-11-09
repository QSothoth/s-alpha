"""EH: raw-row as-of cutoff audit for fixed B2, F1 and U1 accounts."""
from dataclasses import replace
import gc
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from studies import trader_data
from studies.trader_replication import gate, martin_continue_du as du, martin_continue_ea as ea
from studies.trader_replication import martin_continue_ee as ee
from studies.trader_replication import system
from studies.trader_replication.martin_continue_b import support_book
from studies.trader_replication.martin_continue_b_check import digest
from studies.trader_replication.martin_continue_bv import daily_name_score
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import (HOLD, f1_rules, hold_sim, merge, nl_rules,
                                                            pool_book2, pool_book3, sized, tilt_core, u1_entries)

CUTS = ('2024-09-30', '2025-09-30')


def normalized(book, d, cutoff):
    result = {}
    for i, day in enumerate(d.days):
        if not '2024-01-02' <= day <= cutoff:
            continue
        rows = []
        for entry in sorted(book[i], key=lambda e: e[0]):
            j, fill, stop = int(entry[1]), float(entry[3]), float(entry[4])
            close = float(d.c[i, j])
            extra = entry[6] if len(entry) > 6 else None
            rows.append({'code': str(d.A['codes'][j]), 'side': int(entry[2]), 'kind': entry[5],
                         'fill_over_close': fill / close if np.isfinite(close) and close > 0 else None,
                         'stop_over_fill': stop / fill if fill > 0 else None,
                         'dayexit_over_fill': float(extra) / fill if extra is not None and fill > 0 else None,
                         'extra': list(entry[7:])})
        result[day] = rows
    return result


def pending_book(d, broad, accepted):
    result = {}
    for i in range(1, len(d.days) - 1):
        selected = {e[1] for e in accepted[i]}
        candidates = sorted((e for e in broad[i] if e[1] not in selected and np.isfinite(d.l[i, e[1]])
                             and d.l[i, e[1]] > 0), key=lambda e: e[0])
        if candidates:
            j = candidates[0][1]
            result[d.days[i + 1]] = [str(d.A['codes'][j]), float(d.l[i, j] / d.c[i, j])]
    return result


def make_books(d, fields, mask):
    score = daily_name_score(fields, mask, HOLD['H3'])
    holding = hold_sim(score, 12, 36)
    d1 = pool_book3(d, fields, holding, score, 8.0, False, .03)
    broad = pool_book2(d, fields, holding, score, True, 8.0, None, False)
    limits, _ = support_book(d, broad, d1)
    pending = pending_book(d, broad, d1)
    b2 = merge(d1, limits)
    f1 = merge(tilt_core(d, holding, .5), sized(pool_book2(d, fields, holding, score), .5))
    u1 = u1_entries(d, fields, holding, score)
    return {'B2': b2, 'F1': f1, 'U1': u1}, pending


def snapshot(d, name, book, rules, cutoff, pending):
    px, em = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules)
    curve, dates, trades = system.simulate(px, em, rules, book, '2024-01-02', cutoff)
    keys = [[t['code'], int(t['side']), t['kind'], t['entry'], t['exit'], t['why']] for t in trades]
    return {'signals': normalized(book, d, cutoff),
            'pending': {day: item for day, item in pending.items() if '2024-01-02' <= day <= cutoff} if name == 'B2' else {},
            'trade_keys': keys, 'curve': curve.tolist(), 'dates': [str(x) for x in dates],
            'curve_sha256': hashlib.sha256(np.ascontiguousarray(curve).tobytes()).hexdigest(),
            'trade_digest': digest(keys)}


def main(mode):
    if mode != 'full' and mode not in CUTS:
        raise ValueError('expected full or registered cutoff')
    root = du.REPORTS
    bc_path, ee_path, ee_cut_path = root / 'strong_continue_bc_full.json', root / 'strong_continue_ee_full.json', root / 'strong_continue_ee_cut.json'
    bc, old_ee, ee_cut = json.loads(bc_path.read_text()), json.loads(ee_path.read_text()), json.loads(ee_cut_path.read_text())
    if old_ee['script_sha256'] != sha(Path(ee.__file__)) or ee_cut['full_sha256'] != sha(ee_path) or any(ee_cut['cutoff_differences'].values()):
        raise ValueError('EE input differs or cutoff failed')
    expected_digest = old_ee['dataset_digest']
    old_bc = bc['snapshots']
    old_bb = {}
    for cut in CUTS:
        file = root / f'strong_continue_bb_full_{cut}.json'
        obj = json.loads(file.read_text())
        old_bb[cut] = {'trade_keys': obj['trade_keys'], 'curve': obj['curve'], 'sha256': sha(file)}
    del old_ee, ee_cut, bc, obj
    gc.collect()
    base = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if base.digest() != expected_digest:
        raise ValueError('v1 digest differs')
    dataset = base if mode == 'full' else ea.LimitedDataset(base, mode)
    d = du.make_data(dataset)
    if (mode == 'full' and d.days[-1] <= CUTS[-1]) or (mode != 'full' and d.days[-1] != mode):
        raise AssertionError('wrong dataset ending')
    fields, mask, _ = du.compute_fields(d)
    events, positions = ee.source_inputs(dataset, d.days, list(map(str, d.A['codes'])))
    del positions
    fast = np.empty(events.shape, np.float32)
    for start in range(0, events.shape[1], 64):
        sl = slice(start, start + 64)
        fast[:, sl] = du._ROLL_MEAN(events[:, sl].astype(np.float32), 250)
    del events
    snapshots = {}
    actual_cuts = CUTS if mode == 'full' else (mode,)
    rules = {'B2': replace(nl_rules(d, 6, trail='e9'), intraday_kinds=tuple(nl_rules(d, 6, trail='e9').intraday_kinds) + ('lim',)),
             'F1': f1_rules(d), 'U1': f1_rules(d, 6, (1, 3))}
    for variant in ('original', 'asof_fast'):
        if variant == 'asof_fast':
            fields['fast250'] = fast
        books, pending = make_books(d, fields, mask)
        snapshots[variant] = {}
        for name in ('B2', 'F1', 'U1'):
            print(mode, variant, name, flush=True)
            snapshots[variant][name] = {}
            for cut in actual_cuts:
                item = snapshot(d, name, books[name], rules[name], cut, pending)
                if mode == 'full' and variant == 'original':
                    if name in ('B2', 'F1'):
                        expected = old_bc[name][cut]
                        if item['trade_digest'] != expected['trade_keys'] or item['curve_sha256'] != expected['curve']:
                            raise AssertionError('BC baseline differs: ' + name + ' ' + cut)
                    elif item['trade_keys'] != old_bb[cut]['trade_keys'] or item['curve'] != old_bb[cut]['curve']:
                        raise AssertionError('BB baseline differs: ' + cut)
                snapshots[variant][name][cut] = item
        del books, pending
        gc.collect()
    out = {'mode': mode, 'dataset_digest': expected_digest, 'actual_last': d.days[-1],
           'script_sha256': sha(Path(__file__)), 'bc_full_sha256': sha(bc_path), 'ee_full_sha256': sha(ee_path),
           'ee_cut_sha256': sha(ee_cut_path), 'bb_full_sha256': {k: v['sha256'] for k, v in old_bb.items()},
           'snapshots': snapshots}
    target = root / f'strong_continue_eh_{mode}.json'
    with target.open('w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        f.write('\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main(sys.argv[1])
