"""DU: fixed H3 next-open sensitivity on the locally cached 2023 subset."""
from collections import Counter, defaultdict
import gc
import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np
from studies import trader_data
from studies.trader_data import panel
from studies.trader_replication import systems, ticket_t4, watchlist
from studies.trader_replication.martin_continue_a import required_fields
from studies.trader_replication.martin_continue_bb import data_with_system
from studies.trader_replication.martin_continue_bq import _ROLL_MEAN, activity_ranks, chunked_roll_mean
from studies.trader_replication.martin_continue_bu import trigger
from studies.trader_replication.martin_continue_bv import daily_name_score
from studies.trader_replication.martin_continue_cr import json_default
from studies.trader_replication.martin_continue_cv import METRICS, compare_cells
from studies.trader_replication.martin_continue_dk import next_open_outcome
from studies.trader_replication.martin_continue_dq import ROOT, NAMES, sha, verify_files
from studies.trader_replication.martin_continue_dt import EarlyHistory
from studies.trader_replication.martin_list import ema
from studies.trader_replication.martin_strong_scan import HOLD, active, hold_sim

START, END, CUT = '2023-10-02', '2026-10-15', '2023-12-29'
REPORTS = ROOT / 'studies/trader_replication/reports/gap_review'


class Truncated(EarlyHistory):
    def rows(self):
        for code, day, values in super().rows():
            if day <= CUT:
                yield code, day, values


def load_adapter(cut):
    dt_path = REPORTS / 'strong_continue_dt.json'
    dt = json.loads(dt_path.read_text())
    if not dt['overlap_gate'] or sha(ROOT / 'studies/trader_replication/martin_continue_dt.py') != dt['inputs']['script']:
        raise ValueError('DT qualification or script pin differs')
    if sha(ROOT / 'studies/trader_data/panel.py') != dt['inputs']['panel']:
        raise ValueError('panel source differs from DT')
    base = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if base.digest() != dt['inputs']['v1']:
        raise ValueError('v1 differs from DT')
    available = {s['code'] for s in base.stocks()}
    paths = {}
    for name in NAMES[:2]:
        folder = ROOT / 'data' / name
        verify_files(folder)
        if sha(folder / 'CHECKSUMS.sha256') != dt['inputs']['sources'][name]:
            raise ValueError('source differs from DT')
        for path in (folder / 'daily').glob('*.csv'):
            code = 'US.' + path.stem
            if code in paths:
                raise ValueError('duplicate source ' + code)
            if code in available:
                paths[code] = folder
    if len(paths) != dt['stocks']:
        raise ValueError('universe differs from DT')
    if sha(ROOT / 'data/martin-luk-benchmarks-v1/US.QQQ.csv') != dt['qqq_sha256']:
        raise ValueError('benchmark differs from DT')
    cls = Truncated if cut else EarlyHistory
    adapter = cls(base, paths, dt['adapter_digest'] + ('-cut' if cut else ''))
    return adapter, sha(dt_path)


def make_data(adapter):
    selected = systems.get('martin_luk')
    wrapper, _ = selected.load()
    base = getattr(wrapper, 'base', wrapper)

    def arrays(market):
        if market != 'us':
            raise ValueError('unexpected market')
        p = panel.build(adapter, cache=False, write_cache=False)
        a = base.R.market_arrays(market, p)
        a['digest'] = p['digest']
        return a

    base.arrays = arrays
    original_ranks = ticket_t4.ranks
    try:
        ticket_t4.ranks = activity_ranks
        return data_with_system(selected)
    finally:
        ticket_t4.ranks = original_ranks


def compute_fields(d):
    del d.fp, d.fwd, d.raw
    for key in ('pr21', 'pr63', 'pr126', 'rank_pool', 'stack', 'tight'):
        d.A.pop(key, None)
    d.rk = d.rk.astype(np.int32)
    gc.collect()
    try:
        watchlist.roll_mean = chunked_roll_mean
        f = required_fields(d)
    finally:
        watchlist.roll_mean = _ROLL_MEAN
    mask = active(d, f)
    score = daily_name_score(f, mask, HOLD['H3'])
    holding = hold_sim(score, 12, 36)
    return f, mask, holding


def signature(d, f, mask, holding, idx):
    close, low, high = d.c[idx], d.l[idx], d.h[idx - 1]
    pull = (f['lowe9'][idx] <= .1) & (close > d.e9[idx])
    br = (close > high) & (f['cpos'][idx] >= .5)
    valid = mask[idx] & (pull | br) & (np.nan_to_num(f['ext21'][idx], nan=99) <= 8.) & np.isfinite(close) & np.isfinite(low)
    ids = np.flatnonzero(valid)
    stop = np.minimum(np.maximum(low[ids].astype(float), close[ids].astype(float) * .95), close[ids].astype(float) * .99)
    return {'active': np.flatnonzero(mask[idx]).tolist(), 'holding': np.flatnonzero(holding[idx]).tolist(),
            'candidates': [[int(j), trigger(bool(pull[j]), bool(br[j])), float(s / float(close[j]))]
                           for j, s in zip(ids, stop)]}


def blocks(rows, rng):
    n = len(rows)
    if n < 21:
        return {m: None for m in METRICS}
    starts = rng.integers(0, n - 20, size=(1000, (n + 20) // 21))
    sample = (starts[:, :, None] + np.arange(21)).reshape(1000, -1)[:, :n]
    out = {}
    for metric in METRICS:
        weights = np.asarray([r['matched'][metric]['h3_weight'] for r in rows], float)
        nums = np.asarray([r['matched'][metric]['numerator'] for r in rows], float)
        den = weights[sample].sum(axis=1)
        difference = float(nums.sum() / weights.sum()) if weights.sum() else None
        interval = None if np.any(den <= 0) else np.quantile(nums[sample].sum(axis=1) / den, [.025, .975]).tolist()
        out[metric] = {'matched_days': int(np.count_nonzero(weights)), 'h3_weight': int(weights.sum()),
                       'difference': difference, 'interval95': interval,
                       'unmatched_h3': sum(r['matched'][metric]['unmatched_h3'] for r in rows),
                       'zero_denominator_draws': int(np.sum(den <= 0))}
    return out


def main(mode):
    if mode not in ('full', 'cut') or os.environ.get('TRADER_DATA_MODE') != 'frozen' or os.environ.get('TRADER_DATA_TAG') != 'trader-data-v1':
        raise ValueError('use full/cut with explicit frozen v1')
    adapter, source_hash = load_adapter(mode == 'cut')
    d = make_data(adapter)
    if d.A['digest'] != adapter.digest() or (mode == 'cut' and d.days[-1] != CUT):
        raise ValueError('adapter or cutoff differs')
    f, mask, holding = compute_fields(d)
    codes = list(map(str, d.A['codes']))
    sig = {d.days[i]: signature(d, f, mask, holding, i) for i in range(1, len(d.days)) if START <= d.days[i] <= CUT}
    if mode == 'cut':
        full_path = REPORTS / 'strong_continue_du_full.json'
        full = json.loads(full_path.read_text())
        if full['script_sha256'] != sha(Path(__file__)) or full['dt_report_sha256'] != source_hash or full['codes'] != codes:
            raise ValueError('full run inputs differ')
        if set(sig) != set(full['signals']):
            raise AssertionError('signal dates differ')
        changes = Counter()
        first = {}
        for day in sorted(sig):
            a, b = full['signals'][day], sig[day]
            for key in ('active', 'holding'):
                if a[key] != b[key]:
                    changes[key] += 1
                    first.setdefault(key, day)
            ac, bc = a['candidates'], b['candidates']
            if [x[:2] for x in ac] != [x[:2] for x in bc]:
                changes['candidate_identity'] += 1
                first.setdefault('candidate_identity', day)
                continue
            if not np.allclose([x[2] for x in ac], [x[2] for x in bc], rtol=1e-5, atol=0, equal_nan=False):
                changes['normalized_stop'] += 1
                first.setdefault('normalized_stop', day)
        out = {'dt_report_sha256': source_hash, 'script_sha256': sha(Path(__file__)), 'full_sha256': sha(full_path),
               'cutoff': CUT, 'days': len(sig), 'changes': dict(changes), 'first': first}
        target = REPORTS / 'strong_continue_du_cut.json'
        target.write_text(json.dumps(out, indent=2, allow_nan=False) + '\n')
        print('wrote', target, 'changes', dict(changes), flush=True)
        return
    e21 = np.empty(d.c.shape, dtype=np.float32)
    for start in range(0, d.c.shape[1], 64):
        sl = slice(start, start + 64)
        e21[:, sl] = ema(d.c[:, sl].astype(float), 21).astype(np.float32)
    daily, years, names = [], {}, defaultdict(set)
    for i in range(1, len(d.days) - 1):
        date = d.days[i]
        if not START <= date <= END:
            continue
        values = signature(d, f, mask, holding, i)
        adr = d.adr[i - 1]
        adr_pool = adr[mask[i] & np.isfinite(adr) & (adr > 0)]
        boundaries = np.quantile(adr_pool, [1 / 3, 2 / 3]) if len(adr_pool) else None
        cells = defaultdict(lambda: {'h3': [], 'other': []})
        totals = {'h3': Counter(), 'other': Counter()}
        for j, kind, stop_ratio in values['candidates']:
            side = 'h3' if holding[i, j] else 'other'
            stop = stop_ratio * float(d.c[i, j])
            outcome = next_open_outcome(d.A['open'][:, j], d.A['high'][:, j], d.A['low'][:, j], d.A['close'][:, j], e21[:, j], i + 1, stop)
            totals[side]['candidates'] += 1
            totals[side][outcome['status']] += 1
            totals[side]['quick_known'] += outcome['quick'] is not None
            totals[side]['final_known'] += outcome['ret'] is not None
            names[(date[:4], side)].add(codes[j])
            if boundaries is not None and np.isfinite(adr[j]) and adr[j] > 0:
                cell = (kind, int(np.searchsorted(boundaries, adr[j], side='right')))
                cells[cell][side].append(outcome)
            else:
                totals[side]['missing_adr'] += 1
        daily.append({'date': date, 'entry_date': d.days[i + 1], 'totals': {k: dict(v) for k, v in totals.items()},
                      'matched': compare_cells(cells)})
        if len(daily) % 100 == 0:
            print('completed signal days', len(daily), flush=True)
    rng = np.random.default_rng(20261101)
    for year in ('2023', '2024', '2025', '2026'):
        subset = [row for row in daily if row['date'].startswith(year)]
        counts = {}
        for side in ('h3', 'other'):
            summed = Counter()
            for row in subset:
                summed.update(row['totals'][side])
            counts[side] = dict(summed)
            counts[side]['unique_codes'] = len(names[(year, side)])
        years[year] = {'signals': len(subset), 'totals': counts, 'matched': blocks(subset, rng)}
    paths = ['studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_bq.py',
             'studies/trader_replication/martin_continue_bv.py', 'studies/trader_replication/martin_continue_cv.py',
             'studies/trader_replication/martin_continue_dk.py', 'studies/trader_replication/martin_continue_ct.py',
             'studies/trader_replication/martin_strong_scan.py', 'studies/martin_luk/replicate.py']
    out = {'dt_report_sha256': source_hash, 'adapter_digest': adapter.digest(), 'script_sha256': sha(Path(__file__)),
           'code_sha256': {p: sha(ROOT / p) for p in paths}, 'codes': codes, 'signals': sig, 'years': years, 'daily': daily}
    target = REPORTS / 'strong_continue_du_full.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False, default=json_default) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main(sys.argv[1])
