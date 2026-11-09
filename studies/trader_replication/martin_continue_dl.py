"""DL: audit whether float32 close prices turn H3 close entries into intraday fills."""
from collections import Counter, defaultdict
import gc
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from studies import trader_data
from . import ticket_t4
from .martin_continue_bq import activity_ranks
from .martin_strong import Data
from .martin_strong_scan import f1_rules, nl_rules


def main():
    if os.environ.get('TRADER_DATA_MODE') != 'frozen' or os.environ.get('TRADER_DATA_TAG') != 'trader-data-v1':
        raise ValueError('explicitly select frozen v1')
    root = Path(__file__).resolve().parents[2]
    reports = root / 'studies/trader_replication/reports/gap_review'
    ref_path = reports / 'strong_continue_ct.json'
    reference = json.loads(ref_path.read_text())
    panel = trader_data.load('us', mode='frozen', version='trader-data-v1')
    if panel['digest'] != reference['dataset_digest']:
        raise ValueError('frozen panel digest differs from CT')
    ci = {str(code): j for j, code in enumerate(panel['codes'])}
    di = {str(date): d for d, date in enumerate(panel['days'])}
    close = panel['close']
    counts = defaultdict(Counter)
    mismatch = []
    for r in reference['candidates']:
        x = close[di[r['day']], ci[r['code']]]
        if not np.isfinite(x):
            result = 'missing'
        elif float(r['fill']) == np.float64(x):
            result = 'equal'
        else:
            result = 'different'
        counts[r['day'][:4]][result] += 1
        if result != 'equal':
            mismatch.append({'day': r['day'], 'code': r['code'], 'fill': r['fill'],
                             'close': float(x) if np.isfinite(x) else None, 'result': result})
    dtype = str(close.dtype)
    del panel, close
    gc.collect()
    old = ticket_t4.ranks
    try:
        ticket_t4.ranks = activity_ranks
        D = Data()
    finally:
        ticket_t4.ranks = old
    if D.A['digest'] != reference['dataset_digest']:
        raise ValueError('Martin execution panel digest differs')
    kinds = {name: list(rule.intraday_kinds) for name, rule in
             (('U1', f1_rules(D, 6, (1, 3))), ('SAT6', nl_rules(D, 6)))}
    if len(reference['candidates']) != sum(sum(c.values()) for c in counts.values()):
        raise AssertionError('candidate count mismatch')
    code_paths = ('studies/trader_replication/martin_continue_dl.py', 'studies/trader_replication/system.py',
                  'studies/trader_replication/study.py', 'studies/trader_replication/martin_strong.py',
                  'studies/trader_replication/martin_strong_scan.py', 'studies/martin_luk/replicate.py',
                  'studies/trader_data/panel.py')
    result = {'dataset_digest': D.A['digest'], 'source_dtype': dtype, 'comparisons': dict(counts),
              'intraday_kinds': kinds, 'mismatches': mismatch,
              'reference_sha256': hashlib.sha256(ref_path.read_bytes()).hexdigest(),
              'code_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in code_paths}}
    target = reports / 'strong_continue_dl.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
