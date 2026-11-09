"""EF: isolated as-of fast250 correction in fixed U1 and SAT6 accounts."""
from collections import Counter
import gc
import json
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trader_replication import compare, panels, system
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ea as ea
from studies.trader_replication import martin_continue_ee as ee
from studies.trader_replication.martin_continue_bm import describe
from studies.trader_replication.martin_continue_bt import fidelity
from studies.trader_replication.martin_continue_bv import daily_name_score
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import HOLD, f1_rules, hold_sim, nl_rules, pool_book2, u1_entries


def books(d, fields, mask):
    score = daily_name_score(fields, mask, HOLD['H3'])
    holding = hold_sim(score, 12, 36)
    u1 = u1_entries(d, fields, holding, score)
    raw = pool_book2(d, fields, holding, score, True, 8.0, None, False)
    sat = [[((2.0,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:6]) for e in row] for row in raw]
    return u1, sat


def account(d, book, rules):
    px, em = d.base.px(d.A), d.base.ema_inputs(d.A, d.pool, rules)
    track = {}
    curve, dates, trades = system.simulate(px, em, rules, book, *panels.WINDOW, audit=True, track=track)
    lo = int(np.searchsorted(d.A['days'], panels.WINDOW[0]))
    hi = int(np.searchsorted(d.A['days'], panels.WINDOW[1], side='right'))
    m = compare.metrics(curve, dates, trades, book, lo, hi)
    m['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in trades) for y in ('2024', '2025', '2026')}
    m['average_close_positions'] = float(np.mean(track['open']))
    m['max_close_positions'] = max(track['open'])
    m['invested_basis'] = describe([t for t in trades if t['why'] != 'end'], 'ret_invested')
    keys = [[t['code'], int(t['side']), t['kind'], t['entry'], t['exit'], t['why']] for t in trades]
    return {'metrics': m, 'fidelity': fidelity(d, trades), 'trade_keys': keys}


def differences(a, b):
    x, y = Counter(tuple(v) for v in a), Counter(tuple(v) for v in b)
    return {'same': sum((x & y).values()), 'only_original': sum((x - y).values()),
            'only_corrected': sum((y - x).values())}


def main():
    root = du.REPORTS
    ee_path, ee_cut_path = root / 'strong_continue_ee_full.json', root / 'strong_continue_ee_cut.json'
    bz_path = root / 'strong_continue_bz.json'
    ref_ee, cut, bz = json.loads(ee_path.read_text()), json.loads(ee_cut_path.read_text()), json.loads(bz_path.read_text())
    if (ref_ee['script_sha256'] != sha(Path(ee.__file__)) or cut['full_sha256'] != sha(ee_path)
            or any(cut['cutoff_differences'].values())):
        raise ValueError('EE inputs differ or failed cutoff')
    expected_counts, expected_digest = ref_ee['events_changed_by_year'], ref_ee['dataset_digest']
    expected_baselines = {k: {'by_year': bz['results'][k]['metrics']['by_year'],
                               'entries': bz['results'][k]['metrics']['entries_by_year']} for k in ('U1', 'SAT6')}
    del ref_ee, cut, bz
    gc.collect()
    dataset = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if dataset.digest() != expected_digest:
        raise ValueError('dataset differs from EE')
    d = du.make_data(dataset)
    fields, mask, _ = du.compute_fields(d)
    original_u1, original_sat = books(d, fields, mask)
    events, positions = ee.source_inputs(dataset, d.days, list(map(str, d.A['codes'])))
    del positions
    with np.errstate(divide='ignore', invalid='ignore'):
        old_events = np.zeros(d.c.shape, dtype=bool)
        old_events[1:] = np.abs(d.c[1:] / d.c[:-1] - 1) >= .05
    counts = Counter()
    for i, day in enumerate(d.days):
        if ea.START <= day <= ea.END:
            counts[day[:4]] += int(np.count_nonzero(events[i] != old_events[i]))
    if dict(counts) != expected_counts:
        raise AssertionError('EE event differences do not reproduce')
    del old_events
    fast = np.empty(events.shape, np.float32)
    for start in range(0, events.shape[1], 64):
        sl = slice(start, start + 64)
        fast[:, sl] = du._ROLL_MEAN(events[:, sl].astype(np.float32), 250)
    fields['fast250'] = fast
    del events, fast
    gc.collect()
    corrected_u1, corrected_sat = books(d, fields, mask)
    for old, new in zip(original_u1, corrected_u1):
        if [e for e in old if e[5] != 'list'] != [e for e in new if e[5] != 'list']:
            raise AssertionError('core or short order changed')
    signal_counts = {}
    for label, old, new in (('U1', original_u1, corrected_u1), ('SAT6', original_sat, corrected_sat)):
        signal_counts[label] = {year: {'original': sum(sum(e[5] == 'list' for e in old[i]) for i, day in enumerate(d.days) if day.startswith(year)),
                                      'corrected': sum(sum(e[5] == 'list' for e in new[i]) for i, day in enumerate(d.days) if day.startswith(year)),
                                      'days_changed': sum(old[i] != new[i] for i, day in enumerate(d.days) if day.startswith(year))}
                                for year in ('2024', '2025', '2026')}
    del fields, mask
    gc.collect()
    lever, unlevered = f1_rules(d, 6, (1, 3)), nl_rules(d, 6)
    results = {}
    for name, book, rules in (('U1', original_u1, lever), ('U1_asof', corrected_u1, lever),
                              ('SAT6', original_sat, unlevered), ('SAT6_asof', corrected_sat, unlevered)):
        print('account', name, flush=True)
        results[name] = account(d, book, rules)
    for name in ('U1', 'SAT6'):
        for year in ('2024', '2025', '2026'):
            actual, prior = results[name]['metrics'], expected_baselines[name]
            if abs(actual['by_year'][year] - prior['by_year'][year]) > 1e-10 or actual['entries_by_year'][year] != prior['entries'][year]:
                raise AssertionError('baseline differs from BZ: ' + name + ' ' + year)
    out = {'dataset_digest': expected_digest, 'ee_full_sha256': sha(ee_path), 'ee_cut_sha256': sha(ee_cut_path),
           'bz_sha256': sha(bz_path), 'script_sha256': sha(Path(__file__)), 'window': list(panels.WINDOW),
           'events_changed_by_year': dict(counts), 'signal_counts': signal_counts, 'results': results,
           'trade_differences': {name: differences(results[name]['trade_keys'], results[name + '_asof']['trade_keys'])
                                 for name in ('U1', 'SAT6')}}
    target = root / 'strong_continue_ef.json'
    with target.open('w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        f.write('\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
