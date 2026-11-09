"""CU: prior-close R13 near-high proxy on fixed CT candidate outcomes."""
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from . import panels


def near_high(close, high, day, stock):
    """R13's 252-session high, computed at the preceding close."""
    if day < 252:
        return None
    prior_close = close[day - 1, stock]
    peak = np.fmax.reduce(high[day - 252:day, stock])
    if not (np.isfinite(prior_close) and prior_close > 0 and np.isfinite(peak) and peak > 0):
        return None
    return bool(prior_close >= .85 * peak)


def summarize(rows):
    output = {}
    for label, expected in (('near', True), ('far', False), ('unknown', None)):
        group = [r for r in rows if r['near_high'] is expected]
        quick = [r['outcome']['quick'] for r in group if r['outcome']['quick'] is not None]
        finished = [r['outcome'] for r in group if r['outcome']['ret'] is not None]
        output[label] = {'candidates': len(group), 'quick_known': len(quick), 'quick_unknown': len(group) - len(quick),
            'quick_rate': sum(quick) / len(quick) if quick else None, 'final_known': len(finished),
            'final_unknown': len(group) - len(finished),
            'mean_return': float(np.mean([x['ret'] for x in finished])) if finished else None,
            'large_count': sum(x['ret'] >= .30 for x in finished),
            'large_rate': float(np.mean([x['ret'] >= .30 for x in finished])) if finished else None,
            'median_days': float(np.median([x['days'] for x in finished])) if finished else None,
            'reasons': dict(Counter(r['outcome']['reason'] for r in group))}
    days = defaultdict(lambda: [[], []])
    for r in rows:
        quick, group = r['outcome']['quick'], r['near_high']
        if quick is not None and group is not None:
            days[r['day']][0 if group else 1].append(int(quick))
    differences = [float(np.mean(a) - np.mean(b)) for a, b in days.values() if a and b]
    output['same_day'] = {'days': len(differences), 'mean_quick_difference': float(np.mean(differences)) if differences else None}
    return output


def main():
    if os.environ.get('TRADER_DATA_MODE') != 'frozen' or os.environ.get('TRADER_DATA_TAG') != 'trader-data-v1':
        raise ValueError('explicitly select the registered frozen v1 dataset')
    root = Path(__file__).resolve().parents[2]
    source_path = root / 'studies/trader_replication/reports/gap_review/strong_continue_ct.json'
    source = json.loads(source_path.read_text())
    A = panels.arrays('us', mode='frozen')
    expected = json.loads((root / 'studies/trader_replication/DATA_PIN.json').read_text())['trader-data-v1']['us']
    if A['digest'] != expected or source['dataset_digest'] != expected:
        raise ValueError('data pin or CT data differs')
    days = {str(day): i for i, day in enumerate(A['days'])}
    codes = {str(code): j for j, code in enumerate(A['codes'])}
    rows = []
    for candidate in source['candidates']:
        day, j = days[candidate['day']], codes[candidate['code']]
        fill = float(np.float32(A['close'][day, j]))
        low = float(np.float32(A['low'][day, j]))
        stop = min(max(low, fill * .95), fill * .99)
        if fill != candidate['fill'] or abs(stop - candidate['stop']) > 1e-10:
            raise AssertionError('CT candidate price or stop differs')
        rows.append({**candidate, 'near_high': near_high(A['close'], A['high'], day, j)})
    if len(rows) != 5483:
        raise AssertionError('CT candidate count differs')
    years = {}
    for year in ('2024', '2025', '2026'):
        sample = [r for r in rows if r['day'].startswith(year)]
        if len(sample) != source['years'][year]['candidates']:
            raise AssertionError('CT yearly candidate count differs')
        years[year] = summarize(sample)
    paths = ('studies/trader_replication/martin_continue_cu.py', 'studies/trader_replication/martin_continue_ct.py',
             'studies/trader_replication/panels.py', 'studies/martin_luk/strength.py')
    out = {'dataset_digest': A['digest'], 'window': list(panels.WINDOW), 'years': years, 'candidates': rows,
           'source_ct_sha256': hashlib.sha256(source_path.read_bytes()).hexdigest(),
           'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}}
    target = root / 'studies/trader_replication/reports/gap_review/strong_continue_cu.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
