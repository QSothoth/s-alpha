"""DA: assess CV/CY matched results under 21-session moving-block resampling."""
import hashlib
import json
from pathlib import Path

import numpy as np

from .martin_continue_cv import METRICS, year_estimate
from .martin_continue_cy import summarize

BLOCK = 21
DRAWS = 1000
SEED = 20261101
YEARS = ('2024', '2025', '2026')


def moving_blocks(days, rng):
    n = len(days)
    if n < BLOCK:
        raise ValueError('fewer than 21 sessions in year')
    starts = rng.integers(0, n - BLOCK + 1, size=(DRAWS, (n + BLOCK - 1) // BLOCK))
    selected = (starts[:, :, None] + np.arange(BLOCK)).reshape(DRAWS, -1)[:, :n]
    result = {}
    for metric in METRICS:
        weight = np.asarray([d['matched'][metric]['h3_weight'] for d in days], dtype=float)
        numerator = np.asarray([d['matched'][metric]['numerator'] for d in days], dtype=float)
        denom = weight[selected].sum(axis=1)
        if not weight.sum() or np.any(denom <= 0):
            raise ValueError('a block resample lacks matched observations')
        estimates = numerator[selected].sum(axis=1) / denom
        result[metric] = {'days': int(np.count_nonzero(weight)), 'weight': int(weight.sum()),
                          'difference': float(numerator.sum() / weight.sum()),
                          'interval95': np.quantile(estimates, [.025, .975]).tolist()}
    return result


def compare_saved(actual, expected):
    for key in ('days', 'h3_weight', 'difference', 'interval95', 'unmatched_h3'):
        if actual[key] != expected[key]:
            raise AssertionError('CV original daily bootstrap mismatch: ' + key)


def main():
    root = Path(__file__).resolve().parents[2]
    reports = root / 'studies/trader_replication/reports/gap_review'
    paths = {key: reports / f'strong_continue_{key}.json' for key in ('cv', 'cy')}
    sources = {name: json.loads(path.read_text()) for name, path in paths.items()}
    pin = json.loads((root / 'studies/trader_replication/DATA_PIN.json').read_text())['trader-data-v1']['us']
    if any(p['dataset_digest'] != pin for p in sources.values()):
        raise ValueError('frozen digest differs')
    if sources['cv']['window'] != sources['cy']['window']:
        raise ValueError('registered window differs')
    ct = reports / 'strong_continue_ct.json'
    ct_digest = hashlib.sha256(ct.read_bytes()).hexdigest()
    cv_digest = hashlib.sha256(paths['cv'].read_bytes()).hexdigest()
    if (sources['cv']['source_ct_sha256'] != ct_digest
            or sources['cy']['reference_sha256'].get(ct.name) != ct_digest
            or sources['cy']['reference_sha256'].get(paths['cv'].name) != cv_digest):
        raise ValueError('CV / CY input report fingerprints differ')
    result = {}
    for source_name, source in sources.items():
        dates = source['daily' if source_name == 'cv' else 'days']
        if len({d['date'] for d in dates}) != len(dates) or any(
                dates[i]['date'] >= dates[i + 1]['date'] for i in range(len(dates) - 1)):
            raise ValueError('dates missing ordering or unique identity')
        old_rng = np.random.default_rng(SEED)
        block_rng = np.random.default_rng(SEED)
        result[source_name] = {}
        for year in YEARS:
            rows = [d for d in dates if d['date'].startswith(year)]
            expected = source['years'][year]['matched']
            if source_name == 'cv':
                for metric in METRICS:
                    compare_saved(year_estimate(rows, metric, old_rng), expected[metric])
            else:
                if summarize(rows, old_rng) != expected:
                    raise AssertionError('CY original daily bootstrap mismatch: ' + year)
            blocks = moving_blocks(rows, block_rng)
            for metric in METRICS:
                e, b = expected[metric], blocks[metric]
                weight = e['h3_weight'] if source_name == 'cv' else e['weight']
                if (e['days'] != b['days'] or weight != b['weight']
                        or abs(e['difference'] - b['difference']) > 1e-12):
                    raise AssertionError('saved matched point estimate differs')
                b['daily_interval95'] = e['interval95']
            result[source_name][year] = {'calendar_days': len(rows), 'metrics': blocks}
    out = {'dataset_digest': pin, 'window': sources['cv']['window'], 'seed': SEED, 'draws': DRAWS,
           'block_sessions': BLOCK, 'results': result,
           'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (*paths.values(), ct)},
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in (
               'studies/trader_replication/martin_continue_da.py',
               'studies/trader_replication/martin_continue_cv.py',
               'studies/trader_replication/martin_continue_cy.py')}}
    target = reports / 'strong_continue_da.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
