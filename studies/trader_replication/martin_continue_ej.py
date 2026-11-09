"""EJ: fixed quarter-end raw-row cutoffs for as-of-fast U1 and SAT6."""
import gc
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
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong_scan import f1_rules, nl_rules

CUTS = ('2024-06-28', '2025-06-30', '2026-03-31', '2026-06-30')


def main(mode):
    if mode != 'full' and mode not in CUTS:
        raise ValueError('expected full or a registered cutoff')
    ef_path = du.REPORTS / 'strong_continue_ef.json'
    ee_path = du.REPORTS / 'strong_continue_ee_full.json'
    ref = json.loads(ef_path.read_text())
    if ref['script_sha256'] != sha(Path(ef.__file__)) or ref['ee_full_sha256'] != sha(ee_path):
        raise ValueError('EF references differ')
    expected_digest = ref['dataset_digest']
    baselines = {name: {'trade_keys': ref['results'][name + '_asof']['trade_keys'],
                        'by_year': ref['results'][name + '_asof']['metrics']['by_year'],
                        'entries': ref['results'][name + '_asof']['metrics']['entries_by_year']}
                 for name in ('U1', 'SAT6')}
    del ref
    gc.collect()
    base = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if base.digest() != expected_digest:
        raise ValueError('v1 digest differs')
    dataset = base if mode == 'full' else ea.LimitedDataset(base, mode)
    d = du.make_data(dataset)
    if (mode == 'full' and d.days[-1] <= CUTS[-1]) or (mode != 'full' and d.days[-1] != mode):
        raise ValueError('actual dataset ending differs')
    fields, mask, _ = du.compute_fields(d)
    events, positions = ee.source_inputs(dataset, d.days, list(map(str, d.A['codes'])))
    del positions
    fast = np.empty(events.shape, dtype=np.float32)
    for start in range(0, events.shape[1], 64):
        sl = slice(start, start + 64)
        fast[:, sl] = du._ROLL_MEAN(events[:, sl].astype(np.float32), 250)
    fields['fast250'] = fast
    del events, fast
    u1, sat = ef.books(d, fields, mask)
    del fields, mask
    gc.collect()
    rules = {'U1': f1_rules(d, 6, (1, 3)), 'SAT6': nl_rules(d, 6)}
    books = {'U1': u1, 'SAT6': sat}
    if mode == 'full':
        for name in ('U1', 'SAT6'):
            print('full baseline', name, flush=True)
            actual = ef.account(d, books[name], rules[name])
            expected = baselines[name]
            if actual['trade_keys'] != expected['trade_keys']:
                raise AssertionError('EF trade keys differ: ' + name)
            for year in ('2024', '2025', '2026'):
                if (abs(actual['metrics']['by_year'][year] - expected['by_year'][year]) > 1e-10 or
                        actual['metrics']['entries_by_year'][year] != expected['entries'][year]):
                    raise AssertionError('EF account differs: ' + name + ' ' + year)
            del actual
    snapshots = {}
    for name in ('U1', 'SAT6'):
        snapshots[name] = {}
        for cutoff in (CUTS if mode == 'full' else (mode,)):
            print(mode, name, cutoff, flush=True)
            snapshots[name][cutoff] = eh.snapshot(d, name, books[name], rules[name], cutoff, {})
    out = {'mode': mode, 'dataset_digest': expected_digest, 'actual_last': d.days[-1],
           'ef_sha256': sha(ef_path), 'ee_sha256': sha(ee_path), 'script_sha256': sha(Path(__file__)),
           'snapshots': snapshots}
    target = du.REPORTS / f'strong_continue_ej_{mode}.json'
    with target.open('w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        f.write('\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main(sys.argv[1])
