"""BW: separate R74 candidate and equal-weight risk-scale effects between v1 and v2."""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from . import compare, panels, system, systems
from .martin_continue_bv import martin_rules, selected_families, selected_shorts


def positions(D, book):
    out = []
    for day, entries in enumerate(book):
        date = str(D['days'][day])
        if not panels.WINDOW[0] <= date <= panels.WINDOW[1]:
            continue
        for e in entries:
            out.append([date, str(D['codes'][e[1]]), int(e[2]), str(e[5]), float(e[3]), float(e[4])])
    keys = [tuple(row[:4]) for row in out]
    if len(set(keys)) != len(keys):
        raise ValueError('candidate key is not unique')
    return out


def risk_counts(days, a, b):
    out = {}
    for year in ('2024', '2025', '2026'):
        inside = np.array([str(x).startswith(year) for x in days])
        valid = inside & np.isfinite(a) & np.isfinite(b)
        diff = valid & (a != b)
        out[year] = {'sessions': int(inside.sum()), 'valid_both': int(valid.sum()),
                     'changed': int(diff.sum()),
                     'v1_gt_v2': int(np.sum(diff & (a > b))),
                     'v1_lt_v2': int(np.sum(diff & (a < b))),
                     'v1_multipliers': dict(Counter(str(float(x)) for x in a[valid])),
                     'v2_multipliers': dict(Counter(str(float(x)) for x in b[valid]))}
    return out


def main():
    tag = os.environ.get('TRADER_DATA_TAG')
    if os.environ.get('TRADER_DATA_MODE') != 'frozen' or tag not in ('trader-data-v1', 'trader-data-v2'):
        raise ValueError('explicit frozen mode and v1 or v2 required')
    root = Path(__file__).resolve().parents[2]
    pins = json.loads((root / 'studies/trader_replication/DATA_PIN.json').read_text())
    W, cfg = systems.get('martin_luk').load()
    if cfg.get('setup') != 'E11+E10+E2+EW1' or cfg.get('short', {}).get('setups') != ['Z15']:
        raise ValueError('configured setups changed; re-audit compact implementation')
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    if A['digest'] != pins[tag]['us']:
        raise ValueError('frozen dataset does not match registered digest')
    old_families, old_shorts = martin_rules.setup_families, martin_rules.short_setups
    try:
        martin_rules.setup_families, martin_rules.short_setups = selected_families, selected_shorts
        book, rules, mask, pool = W.build(A, cfg)
    finally:
        martin_rules.setup_families, martin_rules.short_setups = old_families, old_shorts
    del mask
    if rules.risk_scale != 'idx_pb16':
        raise ValueError('R74 risk scale changed')
    candidates = positions(A, book)
    for key in ('pr21', 'pr63', 'pr126', 'rank_pool', 'stack', 'tight', 'raw', 'turnover', 'to20', 'e50'):
        A.pop(key, None)
    px = base.px(A)
    em = base.ema_inputs(A, pool, rules)
    idx = em[rules.risk_scale]
    if idx.shape != A['days'].shape:
        raise ValueError('risk scale is not a daily vector')
    start = int(np.searchsorted(A['days'], panels.WINDOW[0]))
    end = int(np.searchsorted(A['days'], panels.WINDOW[1], side='right'))
    def run(inputs):
        curve, dates, trades = system.simulate(px, inputs, rules, book, *panels.WINDOW, audit=True)
        metrics = compare.metrics(curve, dates, trades, book, start, end)
        metrics['entries_by_year'] = {y: sum(t['entry'].startswith(y) for t in trades)
                                      for y in ('2024', '2025', '2026')}
        return metrics
    own = run(em)
    prior = json.loads((root / f'studies/trader_replication/reports/gap_review/strong_continue_bv_{tag}.json').read_text())['results']['R74']['metrics']
    if own['entries_by_year'] != prior['entries_by_year'] or any(abs(own['by_year'][y] - prior['by_year'][y]) > 1e-10 for y in own['by_year']):
        raise AssertionError('R74 does not reproduce BV')
    out = {'tag': tag, 'dataset_digest': A['digest'], 'dates': list(map(str, A['days'])),
           'risk': [float(x) if np.isfinite(x) else None for x in idx],
           'pool_count': pool.sum(axis=1).astype(int).tolist(), 'candidates': candidates, 'own': own}
    if tag == 'trader-data-v1':
        v2 = json.loads((root / 'studies/trader_replication/reports/gap_review/strong_continue_bw_trader-data-v2.json').read_text())
        if v2['dates'] != out['dates'] or v2['dataset_digest'] != pins['trader-data-v2']['us']:
            raise ValueError('v2 dates or digest differ')
        alt = np.array([np.nan if v is None else v for v in v2['risk']], dtype=float)
        out['risk_comparison'] = risk_counts(A['days'], idx, alt)
        out['v1_inputs_v2_risk'] = run({**em, rules.risk_scale: alt})
        v1keys = {tuple(v[:4]) for v in candidates}
        v2keys = {tuple(v[:4]) for v in v2['candidates']}
        ref = {r['code'] for r in json.loads((root / 'data/trader-data-v1/us/universe.json').read_text())['stocks']}
        out['candidate_comparison'] = {}
        for year in ('2024', '2025', '2026'):
            a = {x for x in v1keys if x[0].startswith(year)}
            b = {x for x in v2keys if x[0].startswith(year)}
            out['candidate_comparison'][year] = {'common': len(a & b), 'v1_only': len(a - b),
                                                  'v2_only': len(b - a),
                                                  'v2_only_new_names': sum(x[1] not in ref for x in b - a)}
    paths = ('studies/trader_replication/martin_continue_bw.py', 'studies/trader_replication/martin_continue_bv.py',
             'studies/martin_luk/replicate.py', 'studies/trader_replication/martin.py',
             'studies/trader_replication/shorts.py', 'studies/trader_replication/system.py')
    out['code_sha256'] = {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}
    target = root / f'studies/trader_replication/reports/gap_review/strong_continue_bw_{tag}.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in out.items() if k not in ('dates', 'risk', 'pool_count', 'candidates')},
                     ensure_ascii=False, indent=2, allow_nan=False), flush=True)


if __name__ == '__main__':
    main()
