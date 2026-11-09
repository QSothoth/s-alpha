"""ED: trace the 250-day fast-move percentile at EA's first membership split."""
import gc
import json
import math
from pathlib import Path
import sys

import numpy as np
from studies import trader_data
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ea as ea
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong import pct

DAY = '2024-07-26'


def safe(x):
    return float(x) if np.isfinite(x) else None


def main(mode):
    if mode not in ('full', 'cut'):
        raise ValueError('expected full or cut')
    full_path, cut_path = du.REPORTS / 'strong_continue_ea_full.json', du.REPORTS / 'strong_continue_ea_cut.json'
    full, cut = json.loads(full_path.read_text()), json.loads(cut_path.read_text())
    base = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if (full['dataset_digest'] != base.digest() or full['script_sha256'] != sha(Path(ea.__file__))
            or cut['full_sha256'] != sha(full_path)):
        raise ValueError('EA inputs differ')
    codes = full['codes']
    expected = (cut if mode == 'cut' else full)['audit'][DAY]['all']['active']
    del full, cut
    gc.collect()
    ds = ea.LimitedDataset(base, ea.CUT) if mode == 'cut' else base
    d = du.make_data(ds)
    fields, mask, _ = du.compute_fields(d)
    if codes != list(map(str, d.A['codes'])):
        raise ValueError('codes differ')
    i = d.di[DAY]
    if np.flatnonzero(mask[i]).tolist() != expected:
        raise AssertionError('EA active mask differs')
    names = np.flatnonzero(mask[i])
    values = fields['fast250'][i - 1]
    perc = pct(values[None, :], mask[i:i + 1])[0]
    with np.errstate(divide='ignore', invalid='ignore'):
        r = d.c[i - 250:i, names] / d.c[i - 251:i - 1, names] - 1
    flags = np.abs(r) >= .05
    rows = []
    for col, j in enumerate(names):
        rows.append({'code': codes[j], 'fast250': safe(values[j]), 'percentile': safe(perc[j]),
                     'returns': [safe(x) for x in r[:, col]],
                     'events': ''.join('1' if x else '0' for x in flags[:, col])})
    out = {'ea_full_sha256': sha(full_path), 'ea_cut_sha256': sha(cut_path), 'script_sha256': sha(Path(__file__)),
           'signal_day': DAY, 'event_days': d.days[i - 250:i], 'rows': rows}
    target = du.REPORTS / f'strong_continue_ed_{mode}.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    print('wrote', target, 'names', len(rows), flush=True)


if __name__ == '__main__':
    main(sys.argv[1])
