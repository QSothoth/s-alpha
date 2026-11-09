"""CY: matched outcomes for H3 candidates by prior EMA convergence."""
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
from .martin_continue_cv import METRICS, compare_cells, metric_value
from .martin_continue_cx import decompose_cells
from .martin_list import ema
from .martin_strong import Data
from .martin_strong_scan import active


def prior_squeeze(e9, e21, adr, day):
    """H4 squeeze, using strictly the preceding completed trading day."""
    prev_adr = adr[day - 1]
    with np.errstate(all='ignore'):
        result = np.abs(e9[day - 1] / e21[day - 1] - 1) / prev_adr
    result[(~np.isfinite(prev_adr)) | (prev_adr <= 0)] = np.nan
    return result


def classify(squeeze, eligible):
    """Use the prior-close active pool's median; invalid values remain unknown."""
    valid = eligible & np.isfinite(squeeze)
    if not valid.any():
        return np.full(squeeze.shape, -1, dtype=np.int8), None
    threshold = float(np.median(squeeze[valid]))
    return np.where(np.isfinite(squeeze), (squeeze > threshold).astype(np.int8), -1), threshold


def check_cv_cells(cells, original):
    """Reconcile each CV-paired H3 cell, regardless of squeeze group."""
    for metric in METRICS:
        for cell in original[metric]['cells']:
            key = cell['type'], cell['adr_tercile']
            values = [metric_value(o, metric) for o in cells[key]['h3']]
            values = [v for v in values if v is not None]
            if len(values) != cell['h3_n'] or abs(float(np.mean(values)) - cell['h3_mean']) > 1e-10:
                raise AssertionError('candidate cell differs from CV: ' + str((metric, key)))


def summarize(days, rng):
    # One draw of calendar days supplies all metrics; missing pairs get zero weight.
    sampled = rng.integers(0, len(days), size=(1000, len(days)))
    result = {}
    for metric in METRICS:
        matches = [d['matched'][metric] for d in days]
        w = np.asarray([m['h3_weight'] for m in matches], dtype=float)
        n = np.asarray([m['numerator'] for m in matches], dtype=float)
        denom = w[sampled].sum(axis=1)
        if not w.sum() or np.any(denom == 0):
            raise ValueError('insufficient paired observations for bootstrap')
        b = n[sampled].sum(axis=1) / denom
        result[metric] = {'days': int(np.count_nonzero(w)), 'weight': int(w.sum()),
                          'other_n': sum(m['other_n'] for m in matches),
                          'unmatched_near': sum(m['unmatched_h3'] for m in matches),
                          'difference': float(n.sum() / w.sum()),
                          'interval95': np.quantile(b, [.025, .975]).tolist()}
    weight = sum(d['contributions']['weight'] for d in days)
    for side in ('h3', 'other'):
        pos = sum(d['contributions'][side][1] for d in days) / weight
        neg = sum(d['contributions'][side][2] for d in days) / weight
        result.setdefault('contributions', {})['near' if side == 'h3' else 'far'] = {
            'positive': pos, 'negative': neg, 'return': pos + neg}
    if abs(result['contributions']['near']['return'] - result['contributions']['far']['return']
           - result['return']['difference']) > 1e-10:
        raise AssertionError('return contribution mismatch')
    return result


def main():
    if os.environ.get('TRADER_DATA_MODE') != 'frozen' or os.environ.get('TRADER_DATA_TAG') != 'trader-data-v1':
        raise ValueError('explicitly select frozen v1')
    root = Path(__file__).resolve().parents[2]
    reports = root / 'studies/trader_replication/reports/gap_review'
    ct_path, cv_path = reports / 'strong_continue_ct.json', reports / 'strong_continue_cv.json'
    ct, cv = json.loads(ct_path.read_text()), json.loads(cv_path.read_text())
    old = ticket_t4.ranks
    try:
        ticket_t4.ranks = activity_ranks
        D = Data()
    finally:
        ticket_t4.ranks = old
    pin = json.loads((root / 'studies/trader_replication/DATA_PIN.json').read_text())['trader-data-v1']['us']
    if D.A['digest'] != pin or ct['dataset_digest'] != pin or cv['dataset_digest'] != pin:
        raise ValueError('dataset digest mismatch')
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
    e21 = np.empty(D.c.shape, dtype=np.float32)
    for start in range(0, D.c.shape[1], 64):
        sl = slice(start, start + 64)
        e21[:, sl] = ema(D.c[:, sl].astype(float), 21).astype(np.float32)
    codes = {str(code): j for j, code in enumerate(D.A['codes'])}
    source_days = defaultdict(list)
    for row in ct['candidates']:
        source_days[row['day']].append(row)
    if sum(map(len, source_days.values())) != 5483 or len({(r['day'], r['code']) for r in ct['candidates']}) != 5483:
        raise AssertionError('CT candidates changed or contain duplicates')
    cv_days = {d['date']: d for d in cv['daily']}
    all_days, all_rows = [], []
    for date, reference in cv_days.items():
        d = D.di[date]
        adr = D.adr[d - 1]
        adr_pool = adr[mask[d] & np.isfinite(adr) & (adr > 0)]
        boundaries = np.quantile(adr_pool, [1 / 3, 2 / 3]) if len(adr_pool) else None
        sq = prior_squeeze(D.e9, e21, D.adr, d)
        group, median = classify(sq, mask[d])
        original = defaultdict(lambda: {'h3': [], 'other': []})
        paired = defaultdict(lambda: {'h3': [], 'other': []})
        totals = Counter()
        for r in source_days.get(date, []):
            j = codes[r['code']]
            c, l = float(D.c[d, j]), float(D.l[d, j])
            stop = min(max(l, c * .95), c * .99)
            if c != r['fill'] or abs(stop - r['stop']) > 1e-10 or not mask[d, j]:
                raise AssertionError('CT fill, stop, or active pool mismatch: ' + str((date, r['code'])))
            pull = bool(fields['lowe9'][d, j] <= .1 and c > D.e9[d, j])
            br = bool(c > D.h[d - 1, j] and fields['cpos'][d, j] >= .5)
            kind = trigger(pull, br)
            label = ('unknown', 'near', 'far')[int(group[j]) + 1]
            totals[label] += 1
            item = {'day': date, 'code': r['code'], 'group': label, 'squeeze': float(sq[j]) if np.isfinite(sq[j]) else None,
                    'median': median, 'outcome': r['outcome']}
            all_rows.append(item)
            if boundaries is None or not np.isfinite(adr[j]) or adr[j] <= 0:
                totals['missing_adr'] += 1
                continue
            key = kind, int(np.searchsorted(boundaries, adr[j], side='right'))
            original[key]['h3'].append(r['outcome'])
            if label != 'unknown':
                paired[key]['h3' if label == 'near' else 'other'].append(r['outcome'])
        if sum(totals[k] for k in ('unknown', 'near', 'far')) != reference['totals']['h3']['candidates']:
            raise AssertionError('CT daily candidate count mismatch')
        if totals['missing_adr'] != reference['totals']['h3']['missing_adr']:
            raise AssertionError('CV missing ADR mismatch')
        check_cv_cells(original, reference['matched'])
        all_days.append({'date': date, 'totals': dict(totals), 'matched': compare_cells(paired),
                         'contributions': decompose_cells(paired)})
    if len(all_rows) != len(ct['candidates']):
        raise AssertionError('candidate identity count mismatch')
    windows = []
    for day, j, ticker, _, date in D.big:
        peak = day + 1 + int(np.nanargmax(D.h[day + 1:day + 21, j]))
        last = min(day + 10, peak - 1)
        groups = {r['group'] for r in all_rows if r['code'] == str(D.A['codes'][j]) and day <= D.di[r['day']] <= last}
        windows.append({'date': date, 'ticker': ticker, 'near': 'near' in groups, 'far': 'far' in groups,
                        'unknown': 'unknown' in groups})
    rng = np.random.default_rng(20261101)
    years = {}
    for year in ('2024', '2025', '2026'):
        days = [d for d in all_days if d['date'].startswith(year)]
        rows = [r for r in all_rows if r['day'].startswith(year)]
        counts = {g: {'candidates': sum(r['group'] == g for r in rows),
                      'quick_unknown': sum(r['group'] == g and r['outcome']['quick'] is None for r in rows),
                      'final_unknown': sum(r['group'] == g and r['outcome']['ret'] is None for r in rows)}
                  for g in ('near', 'far', 'unknown')}
        w = [v for v in windows if v['date'].startswith(year)]
        years[year] = {'groups': counts, 'matched': summarize(days, rng),
                       'windows': {'total': len(w), 'near': sum(v['near'] for v in w),
                                   'far': sum(v['far'] for v in w),
                                   'near_only': sum(v['near'] and not v['far'] for v in w)}}
    paths = ('studies/trader_replication/martin_continue_cy.py', 'studies/trader_replication/martin_continue_cv.py',
             'studies/trader_replication/martin_continue_ct.py', 'studies/trader_replication/martin_continue_cx.py',
             'studies/trader_replication/martin_continue_a.py', 'studies/trader_replication/martin_continue_bq.py',
             'studies/trader_replication/martin_continue_ca.py', 'studies/trader_replication/martin_strong.py',
             'studies/trader_replication/martin_strong_scan.py')
    out = {'dataset_digest': pin, 'window': list(panels.WINDOW), 'bootstrap_seed': 20261101,
           'bootstrap_draws': 1000, 'years': years, 'days': all_days, 'candidates': all_rows, 'windows': windows,
           'reference_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (ct_path, cv_path)},
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}}
    target = reports / 'strong_continue_cy.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
