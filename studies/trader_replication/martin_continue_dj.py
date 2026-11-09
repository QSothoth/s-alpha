"""DJ: compare newly admitted and existing H3 names within fixed daily strata."""
from collections import Counter, defaultdict
import gc
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from . import panels, ticket_t4, watchlist
from .martin_continue_a import required_fields
from .martin_continue_bq import _ROLL_MEAN, activity_ranks, chunked_roll_mean
from .martin_continue_bu import trigger
from .martin_continue_bv import daily_name_score
from .martin_continue_cr import json_default
from .martin_continue_cv import METRICS, compare_cells
from .martin_continue_cy import check_cv_cells
from .martin_continue_da import SEED, moving_blocks
from .martin_continue_di import select_spaced
from .martin_strong import Data
from .martin_strong_scan import HOLD, active, hold_sim


def update_age(current, previous, age, censored):
    """Advance membership age from the prior row; censor starts before the panel."""
    continuing = current & previous
    entering = current & ~previous
    age[:] = np.where(current, np.where(continuing, age + 1, 0), -1)
    censored[:] = continuing & censored
    return np.where(~current, -1, np.where(censored & (age < 5), -1, (age >= 5).astype(np.int8)))


def estimates(rows, rng):
    try:
        return moving_blocks(rows, rng)
    except ValueError as exc:
        if str(exc) != 'a block resample lacks matched observations':
            raise
        result = {}
        for metric in METRICS:
            items = [r['matched'][metric] for r in rows]
            weight = sum(x['h3_weight'] for x in items)
            result[metric] = {'days': sum(x['h3_weight'] > 0 for x in items), 'weight': weight,
                              'difference': sum(x['numerator'] for x in items) / weight if weight else None,
                              'interval95': None, 'interval_unavailable': str(exc)}
        return result


def main():
    if os.environ.get('TRADER_DATA_MODE') != 'frozen' or os.environ.get('TRADER_DATA_TAG') != 'trader-data-v1':
        raise ValueError('explicitly select frozen v1')
    root = Path(__file__).resolve().parents[2]
    reports = root / 'studies/trader_replication/reports/gap_review'
    paths = {k: reports / f'strong_continue_{k}.json' for k in ('ct', 'cv', 'di')}
    src = {k: json.loads(p.read_text()) for k, p in paths.items()}
    old = ticket_t4.ranks
    try:
        ticket_t4.ranks = activity_ranks
        D = Data()
    finally:
        ticket_t4.ranks = old
    pin = json.loads((root / 'studies/trader_replication/DATA_PIN.json').read_text())['trader-data-v1']['us']
    if D.A['digest'] != pin or any(x['dataset_digest'] != pin for x in src.values()):
        raise ValueError('frozen dataset mismatch')
    for key in ('ct', 'cv'):
        if src['di']['reference_sha256'][paths[key].name] != hashlib.sha256(paths[key].read_bytes()).hexdigest():
            raise ValueError('DI reference mismatch: ' + key)
    del D.fp, D.fwd, D.raw
    for key in ('pr21', 'pr63', 'pr126', 'rank_pool', 'stack', 'tight'):
        D.A.pop(key, None)
    D.rk = D.rk.astype(np.int32)
    gc.collect()
    try:
        watchlist.roll_mean = chunked_roll_mean
        fields = required_fields(D)
    finally:
        watchlist.roll_mean = _ROLL_MEAN
    mask = active(D, fields)
    score = daily_name_score(fields, mask, HOLD['H3'])
    holding = hold_sim(score, 12, 36)
    del score
    gc.collect()
    codes = np.asarray(D.A['codes']).astype(str)
    indices = {code: j for j, code in enumerate(codes)}
    refs = defaultdict(list)
    for row in src['ct']['candidates']:
        refs[row['day']].append(row)
    cv_days = {r['date']: r for r in src['cv']['daily']}
    di_days = {r['date']: r for r in src['di']['daily']}
    if len({(r['day'], r['code']) for r in src['ct']['candidates']}) != len(src['ct']['candidates']):
        raise ValueError('duplicate CT candidate')
    last = np.full(len(codes), -100000, dtype=np.int32)
    age = np.full(len(codes), -1, dtype=np.int32)
    previous = np.zeros(len(codes), dtype=bool)
    censored = holding[0].copy()
    age[holding[0]] = 0
    previous[:] = holding[0]
    days, candidates = [], []
    for d in range(1, len(D.days)):
        date = D.days[d]
        if date > panels.WINDOW[1]:
            break
        group = update_age(holding[d], previous, age, censored)
        previous[:] = holding[d]
        c, l = D.c[d], D.l[d]
        pull = (fields['lowe9'][d] <= .1) & (c > D.e9[d])
        br = (c > D.h[d - 1]) & (fields['cpos'][d] >= .5)
        valid = mask[d] & (pull | br) & (np.nan_to_num(fields['ext21'][d], nan=99) <= 8.) & np.isfinite(c) & np.isfinite(l)
        picked = select_spaced(d, np.flatnonzero(valid), last)
        if date < panels.WINDOW[0]:
            continue
        chosen = np.zeros(len(codes), dtype=bool)
        chosen[picked] = True
        if any(int(np.sum(valid & (holding[d] if side == 'h3' else ~holding[d]) & chosen)) !=
               di_days[date]['totals'][side]['candidates'] for side in ('h3', 'other')):
            raise AssertionError('spaced candidates differ from DI: ' + date)
        reference = refs[date]
        wanted = {str(codes[j]) for j in np.flatnonzero(valid & holding[d])}
        if wanted != {r['code'] for r in reference}:
            raise AssertionError('H3 candidates differ from CT: ' + date)
        adr = D.adr[d - 1]
        pool = adr[mask[d] & np.isfinite(adr) & (adr > 0)]
        boundaries = np.quantile(pool, [1 / 3, 2 / 3]) if len(pool) else None
        all_cells = defaultdict(lambda: {'h3': [], 'other': []})
        recent_cells = defaultdict(lambda: {'h3': [], 'other': []})
        spaced_cells = defaultdict(lambda: {'h3': [], 'other': []})
        totals = Counter()
        for r in reference:
            j = indices[r['code']]
            fill = float(c[j])
            stop = min(max(float(l[j]), fill * .95), fill * .99)
            if fill != r['fill'] or abs(stop - r['stop']) > 1e-10:
                raise AssertionError('fill or stop differs from CT')
            label = ('unknown', 'new', 'old')[int(group[j]) + 1]
            totals[label] += 1
            candidates.append({'day': date, 'code': r['code'], 'group': label, 'age': int(age[j]),
                               'spaced': bool(chosen[j]), 'outcome': r['outcome']})
            if boundaries is None or not np.isfinite(adr[j]) or adr[j] <= 0:
                totals['missing_adr'] += 1
                continue
            cell = (trigger(bool(pull[j]), bool(br[j])), int(np.searchsorted(boundaries, adr[j], side='right')))
            all_cells[cell]['h3'].append(r['outcome'])
            if label != 'unknown':
                side = 'h3' if label == 'new' else 'other'
                recent_cells[cell][side].append(r['outcome'])
                if chosen[j]:
                    spaced_cells[cell][side].append(r['outcome'])
        if totals['missing_adr'] != cv_days[date]['totals']['h3']['missing_adr']:
            raise AssertionError('missing ADR differs from CV')
        check_cv_cells(all_cells, cv_days[date]['matched'])
        days.append({'date': date, 'totals': dict(totals), 'matched': compare_cells(recent_cells),
                     'spaced': compare_cells(spaced_cells)})
    if len(candidates) != len(src['ct']['candidates']) or len(days) != len(cv_days):
        raise AssertionError('CT candidate count or session count mismatch')
    windows = []
    for day, j, ticker, _, date in D.big:
        peak = day + 1 + int(np.nanargmax(D.h[day + 1:day + 21, j]))
        end = min(day + 10, peak - 1)
        groups = {r['group'] for r in candidates if r['code'] == codes[j] and day <= D.di[r['day']] <= end}
        windows.append({'date': date, 'ticker': ticker, 'new': 'new' in groups, 'old': 'old' in groups,
                        'unknown': 'unknown' in groups})
    annual, normal_rng, spaced_rng = {}, np.random.default_rng(SEED), np.random.default_rng(SEED)
    for year in ('2024', '2025', '2026'):
        selected = [r for r in candidates if r['day'].startswith(year)]
        row_days = [r for r in days if r['date'].startswith(year)]
        groups = {}
        for label in ('new', 'old', 'unknown'):
            rows = [r for r in selected if r['group'] == label]
            groups[label] = {'candidates': len(rows), 'unique_codes': len({r['code'] for r in rows}),
                             'spaced': sum(r['spaced'] for r in rows),
                             'quick_unknown': sum(r['outcome']['quick'] is None for r in rows),
                             'final_unknown': sum(r['outcome']['ret'] is None for r in rows)}
        subset = [w for w in windows if w['date'].startswith(year)]
        annual[year] = {'groups': groups, 'matched': estimates(row_days, normal_rng),
                        'spaced_matched': estimates([{'matched': d['spaced']} for d in row_days], spaced_rng),
                        'windows': {'total': len(subset), 'new': sum(w['new'] for w in subset),
                                    'old': sum(w['old'] for w in subset),
                                    'new_only': sum(w['new'] and not w['old'] for w in subset)}}
    code_paths = ('studies/trader_replication/martin_continue_dj.py', 'studies/trader_replication/martin_continue_di.py',
                  'studies/trader_replication/martin_continue_da.py', 'studies/trader_replication/martin_continue_cy.py',
                  'studies/trader_replication/martin_continue_cv.py', 'studies/trader_replication/martin_continue_a.py',
                  'studies/trader_replication/martin_continue_bq.py', 'studies/trader_replication/martin_continue_bu.py',
                  'studies/trader_replication/martin_continue_bv.py', 'studies/trader_replication/martin_strong_scan.py')
    out = {'dataset_digest': pin, 'window': list(panels.WINDOW), 'seed': SEED, 'years': annual, 'days': days,
           'candidates': candidates, 'windows': windows,
           'reference_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths.values()},
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in code_paths}}
    target = reports / 'strong_continue_dj.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False, default=json_default) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
