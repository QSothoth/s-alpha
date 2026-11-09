"""EP: as-of raw same-day ranges for H3 peer-potential eligibility."""
from collections import Counter
import gc
from itertools import groupby
import json
from pathlib import Path
import sys

import numpy as np
from studies import trader_data
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ea as ea
from studies.trader_replication import martin_continue_ee as ee
from studies.trader_replication import martin_continue_ef as ef
from studies.trader_replication import martin_continue_eh as eh
from studies.trader_replication.martin_continue_bv import daily_name_score
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import HOLD, f1_rules, hold_sim, nl_rules

CUTS = ('2024-06-28', '2024-09-30', '2025-06-30', '2025-09-30', '2026-03-31', '2026-06-30')


def original_eligibility(d):
    out = np.zeros(d.c.shape, dtype=bool)
    with np.errstate(divide='ignore', invalid='ignore'):
        for start in range(0, d.c.shape[1], 64):
            sl = slice(start, start + 64)
            adr = du._ROLL_MEAN(d.h[:, sl] / d.l[:, sl] - 1, 5)
            out[:, sl] = (d.to20[:, sl] >= 5e7) & (adr >= .035)
    return out


def peer_potential(d, eligible):
    n, width = d.c.shape
    pot = np.zeros((n, width), bool)
    rr = np.empty((n, width), np.float32)
    with np.errstate(divide='ignore', invalid='ignore'):
        for i in range(n):
            r = d.c[i] / d.c[i - 1] - 1 if i else np.full(width, np.nan, np.float32)
            ix = np.flatnonzero(eligible[i] & np.isfinite(r))
            if len(ix) > 60:
                pot[i, ix[np.argsort(-r[ix])[:50]]] = True
            median = np.nanmedian(np.where(d.rk[i] < 300, r, np.nan))
            rr[i] = np.nan_to_num(r - median)
        output = np.full((n, width), np.nan, np.float32)
        near = names = None
        for i in range(60, n):
            cur = np.flatnonzero(d.rk[i] < 300)
            if len(cur) < 30:
                continue
            if near is None or i % 5 == 0:
                w = rr[i - 39:i + 1][:, cur]
                w = w - w.mean(0)
                sd = w.std(0) + 1e-6
                near = ((w.T @ w) / len(w) / np.outer(sd, sd)) >= .5
                names = cur
            count = near.sum(1)
            pot5 = pot[i - 4:i + 1][:, names].sum(axis=0) / 5.0
            output[i, names] = (near * pot5).sum(1) / count
    return output, pot


def raw_ranges(values):
    o, h, l, c = values[:4]
    if not all(np.isfinite(v) and v > 0 for v in (o, h, l, c)):
        return np.nan
    return max(h, o, c) / min(l, o, c) - 1


def causal_inputs(dataset, d, codes):
    di, ci = {day: i for i, day in enumerate(d.days)}, {code: j for j, code in enumerate(codes)}
    events = np.zeros(d.c.shape, bool)
    eligible = np.zeros(d.c.shape, bool)
    actions, seen, ash_adr = dataset.actions(), set(), None
    for code, group in groupby(dataset.rows(), key=lambda r: r[0]):
        if code not in ci:
            continue
        if code in seen:
            raise ValueError('ungrouped dataset ' + code)
        seen.add(code)
        rows = [(day, values) for _, day, values in group if day in di]
        if not rows:
            continue
        days = [day for day, _ in rows]
        if any(days[k] >= days[k + 1] for k in range(len(days) - 1)):
            raise ValueError('duplicate or unordered day ' + code)
        idx = np.array([di[day] for day in days], np.int32)
        j = ci[code]
        events[idx, j] = ee.fast_events(days, [values[3] for _, values in rows], actions.get(code, []), idx)
        ranges = np.full((len(d.days), 1), np.nan, np.float64)
        ranges[idx, 0] = [raw_ranges(values) for _, values in rows]
        adr = du._ROLL_MEAN(ranges, 5)[:, 0]
        eligible[:, j] = (d.to20[:, j] >= 5e7) & (adr >= .035)
        if code == 'US.ASH':
            ash_adr = float(adr[di['2026-05-12']]) if '2026-05-12' in di else None
    return events, eligible, ash_adr


def build_books(d, fields, mask):
    score = daily_name_score(fields, mask, HOLD['H3'])
    holding = hold_sim(score, 12, 36)
    del score
    u1, sat = ef.books(d, fields, mask)
    return {'U1': u1, 'SAT6': sat}, holding


def main(mode):
    if mode != 'full' and mode not in CUTS:
        raise ValueError('expected full or a registered cutoff')
    ef_path, ee_path = du.REPORTS / 'strong_continue_ef.json', du.REPORTS / 'strong_continue_ee_full.json'
    ef_ref, ee_ref = json.loads(ef_path.read_text()), json.loads(ee_path.read_text())
    if ef_ref['script_sha256'] != sha(Path(ef.__file__)) or ee_ref['script_sha256'] != sha(Path(ee.__file__)):
        raise ValueError('reference source differs')
    digest = ef_ref['dataset_digest']
    baseline = {name: {'keys': ef_ref['results'][name + '_asof']['trade_keys'],
                       'by_year': ef_ref['results'][name + '_asof']['metrics']['by_year'],
                       'entries': ef_ref['results'][name + '_asof']['metrics']['entries_by_year']}
                for name in ('U1', 'SAT6')}
    del ef_ref, ee_ref
    gc.collect()
    base = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if base.digest() != digest:
        raise ValueError('v1 dataset differs')
    dataset = base if mode == 'full' else ea.LimitedDataset(base, mode)
    d = du.make_data(dataset)
    if (mode == 'full' and d.days[-1] <= CUTS[-1]) or (mode != 'full' and d.days[-1] != mode):
        raise ValueError('actual input ending differs')
    fields, mask, _ = du.compute_fields(d)
    original_eligible = original_eligibility(d)
    replay, old_pot = peer_potential(d, original_eligible)
    for i in range(len(d.days)):
        if not np.array_equal(replay[i], fields['peer_pot'][i], equal_nan=True):
            raise AssertionError('original peer_pot mismatch ' + d.days[i])
    del replay, original_eligible
    gc.collect()
    codes = list(map(str, d.A['codes']))
    events, raw_eligible, ash_adr = causal_inputs(dataset, d, codes)
    fast = np.empty(events.shape, np.float32)
    for start in range(0, events.shape[1], 64):
        sl = slice(start, start + 64)
        fast[:, sl] = du._ROLL_MEAN(events[:, sl].astype(np.float32), 250)
    fields['fast250'] = fast
    del events, fast
    baseline_books, baseline_h = build_books(d, fields, mask)
    new_peer, new_pot = peer_potential(d, raw_eligible)
    del raw_eligible
    counts = {year: Counter() for year in ('2024', '2025', '2026')}
    old_peer = fields['peer_pot']
    for i, day in enumerate(d.days):
        if '2024-01-02' <= day <= '2026-10-16':
            counts[day[:4]]['potential_names'] += int(np.count_nonzero(old_pot[i] != new_pot[i]))
            a, b = old_peer[i], new_peer[i]
            counts[day[:4]]['peer_pot_names'] += int(np.count_nonzero((a != b) & ~(np.isnan(a) & np.isnan(b))))
    fields['peer_pot'] = new_peer
    del old_peer, new_peer, old_pot, new_pot
    gc.collect()
    corrected_books, corrected_h = build_books(d, fields, mask)
    for i, day in enumerate(d.days):
        if '2024-01-02' <= day <= '2026-10-16':
            counts[day[:4]]['h3_names'] += int(np.count_nonzero(baseline_h[i] != corrected_h[i]))
            left = {e[1] for e in baseline_books['SAT6'][i]}
            right = {e[1] for e in corrected_books['SAT6'][i]}
            counts[day[:4]]['candidate_names'] += len(left ^ right)
    del fields, mask, baseline_h, corrected_h
    gc.collect()
    rules = {'U1': f1_rules(d, 6, (1, 3)), 'SAT6': nl_rules(d, 6)}
    results = {}
    if mode == 'full':
        for name in ('U1', 'SAT6'):
            print('baseline account', name, flush=True)
            item = ef.account(d, baseline_books[name], rules[name])
            if item['trade_keys'] != baseline[name]['keys']:
                raise AssertionError('EF baseline trades differ ' + name)
            for year in ('2024', '2025', '2026'):
                if (abs(item['metrics']['by_year'][year] - baseline[name]['by_year'][year]) > 1e-10 or
                        item['metrics']['entries_by_year'][year] != baseline[name]['entries'][year]):
                    raise AssertionError('EF baseline result differs ' + name + ' ' + year)
            results[name + '_baseline'] = item
            print('corrected account', name, flush=True)
            results[name + '_raw_adr'] = ef.account(d, corrected_books[name], rules[name])
    del baseline_books
    gc.collect()
    snapshots = {}
    for name in ('U1', 'SAT6'):
        snapshots[name] = {}
        for cutoff in (CUTS if mode == 'full' else (mode,)):
            print(mode, name, cutoff, flush=True)
            snapshots[name][cutoff] = eh.snapshot(d, name, corrected_books[name], rules[name], cutoff, {})
    out = {'mode': mode, 'dataset_digest': digest, 'actual_last': d.days[-1], 'ash_adr': ash_adr,
           'ef_sha256': sha(ef_path), 'ee_sha256': sha(ee_path), 'script_sha256': sha(Path(__file__)),
           'original_peer_replayed': True, 'changes': {k: dict(v) for k, v in counts.items()},
           'results': results, 'snapshots': snapshots}
    target = du.REPORTS / f'strong_continue_ep_{mode}.json'
    with target.open('w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        f.write('\n')
    print('wrote', target, 'ASH adr', ash_adr, flush=True)


if __name__ == '__main__':
    main(sys.argv[1])
