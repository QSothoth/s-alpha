"""CX: decompose the already registered CV matched-pool return difference."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np

from . import martin_continue_cv as cv
from .martin_continue_cr import json_default


def decompose_cells(cells):
    result = {'weight': 0, 'unmatched_h3': 0, 'cells': [],
              'h3': [0., 0., 0.], 'other': [0., 0., 0.]}
    for key, groups in sorted(cells.items()):
        values = {side: [float(o['ret']) for o in groups[side] if o['ret'] is not None]
                  for side in ('h3', 'other')}
        n = len(values['h3'])
        if not n or not values['other']:
            result['unmatched_h3'] += n
            continue
        cell = {'type': key[0], 'adr_tercile': key[1], 'h3_n': n, 'other_n': len(values['other'])}
        for side in ('h3', 'other'):
            arr = np.asarray(values[side])
            components = [float(np.mean(arr > 0)), float(np.mean(np.maximum(arr, 0))),
                          float(np.mean(np.minimum(arr, 0)))]
            cell[side] = components
            result[side] = [a + n * b for a, b in zip(result[side], components)]
        result['weight'] += n
        result['cells'].append(cell)
    return result


def summarize(daily, rng):
    rows = [d for d in daily if d['weight']]
    weight = np.asarray([d['weight'] for d in rows], dtype=float)
    sides = {s: np.asarray([d[s] for d in rows], dtype=float) for s in ('h3', 'other')}
    total = weight.sum()
    result = {'days': len(rows), 'weight': int(total), 'unmatched_h3': sum(d['unmatched_h3'] for d in daily)}
    for side in sides:
        win, positive, negative = sides[side].sum(axis=0) / total
        result[side] = {'win_probability': float(win), 'positive_contribution': float(positive),
                        'negative_contribution': float(negative), 'mean_return': float(positive + negative),
                        'mean_win': float(positive / win) if win else None,
                        'mean_nonwin': float(negative / (1 - win)) if win < 1 else None}
    differences = sides['h3'] - sides['other']
    draw = rng.integers(0, len(rows), size=(1000, len(rows)))
    boot = differences[draw].sum(axis=1) / weight[draw].sum(axis=1)[:, None]
    names = ('win_probability', 'positive_contribution', 'negative_contribution')
    result['difference'] = {name: {'estimate': float(differences[:, i].sum() / total),
                                   'interval95': np.quantile(boot[:, i], [.025, .975]).tolist()}
                            for i, name in enumerate(names)}
    total_boot = boot[:, 1] + boot[:, 2]
    result['difference']['mean_return'] = {
        'estimate': float((differences[:, 1] + differences[:, 2]).sum() / total),
        'interval95': np.quantile(total_boot, [.025, .975]).tolist()}
    return result


def main():
    root = Path(__file__).resolve().parents[2]
    report_dir = root / 'studies/trader_replication/reports/gap_review'
    source = report_dir / 'strong_continue_cv.json'
    reference = json.loads(source.read_text())
    captured, decomposition = [], []
    original_compare = cv.compare_cells

    def compare(cells):
        result = original_compare(cells)
        part = decompose_cells(cells)
        original = result['return']
        if part['weight'] != original['h3_weight'] or part['unmatched_h3'] != original['unmatched_h3']:
            raise AssertionError('matched return sample differs')
        delta = (part['h3'][1] + part['h3'][2]) - (part['other'][1] + part['other'][2])
        if abs(delta - original['numerator']) > 1e-9:
            raise AssertionError('return contributions do not reconcile')
        decomposition.append(part)
        return result

    def capture(path, text, *args, **kwargs):
        if path != source or captured:
            raise AssertionError('unexpected CV output path or repeated write')
        captured.append(text)
        return len(text)

    def progress(*args, **kwargs):
        if args and args[0] == 'wrote':
            print('CV replay captured without overwriting the original report', flush=True)
        else:
            print(*args, **kwargs)

    with patch.object(cv, 'compare_cells', compare), patch.object(Path, 'write_text', capture), \
         patch.object(cv, 'print', progress, create=True):
        cv.main()
    if len(captured) != 1:
        raise AssertionError('CV replay did not complete')
    replay = json.loads(captured[0])
    if replay['dataset_digest'] != reference['dataset_digest'] or replay['window'] != reference['window']:
        raise AssertionError('CV dataset or window changed')
    if replay['daily'] != reference['daily'] or replay['years'] != reference['years'] or replay['windows'] != reference['windows']:
        raise AssertionError('CV replay does not match the saved daily, annual, or window results')
    if len(decomposition) != len(replay['daily']):
        raise AssertionError('daily decomposition count differs')
    for day, part in zip(replay['daily'], decomposition):
        part['date'] = day['date']
    rng = np.random.default_rng(20261101)
    years = {}
    for year in ('2024', '2025', '2026'):
        subset = [d for d in decomposition if d['date'].startswith(year)]
        years[year] = summarize(subset, rng)
        ref = reference['years'][year]['matched']['return']
        if (years[year]['weight'] != ref['h3_weight'] or years[year]['days'] != ref['days']
                or abs(years[year]['difference']['mean_return']['estimate'] - ref['difference']) > 1e-10):
            raise AssertionError('annual result differs from CV')
    out = {'dataset_digest': replay['dataset_digest'], 'window': replay['window'],
           'bootstrap_seed': 20261101, 'bootstrap_draws': 1000, 'years': years, 'daily': decomposition,
           'source_cv_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
           'source_ct_sha256': replay['source_ct_sha256'], 'cv_source_pins': replay['code_sha256'],
           'cx_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    target = report_dir / 'strong_continue_cx.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False, default=json_default) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
