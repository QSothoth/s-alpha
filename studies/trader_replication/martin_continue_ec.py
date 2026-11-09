"""EC: trace EA's first full/cut H3 membership divergence to score inputs."""
import gc
import json
import math
from pathlib import Path
import sys

import numpy as np
from studies import trader_data
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ea as ea
from studies.trader_replication.martin_continue_bv import daily_name_score
from studies.trader_replication.martin_continue_dk import next_open_outcome
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_list import ema
from studies.trader_replication.martin_strong import pct
from studies.trader_replication.martin_strong_scan import HOLD

DAYS = ('2024-07-25', '2024-07-26', '2024-07-29', '2024-07-30', '2024-07-31',
        '2024-08-01', '2024-08-02', '2024-08-05', '2024-08-06', '2024-08-07')
CODES = ('US.ENPH', 'US.VKTX')


def finite(x):
    x = float(x)
    return x if math.isfinite(x) else None


def main(mode):
    if mode not in ('full', 'cut'):
        raise ValueError('expected full or cut')
    base = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    full_path, cut_path = du.REPORTS / 'strong_continue_ea_full.json', du.REPORTS / 'strong_continue_ea_cut.json'
    ea_full, ea_cut = json.loads(full_path.read_text()), json.loads(cut_path.read_text())
    if (ea_full['dataset_digest'] != base.digest() or ea_full['script_sha256'] != sha(Path(ea.__file__))
            or ea_cut['full_sha256'] != sha(full_path)):
        raise ValueError('EA reference inputs differ')
    reference_codes = ea_full['codes']
    source = ea_cut if mode == 'cut' else ea_full
    audit = {day: source['audit'][day]['all'] for day in DAYS}
    del source, ea_full, ea_cut
    gc.collect()
    dataset = ea.LimitedDataset(base, ea.CUT) if mode == 'cut' else base
    d = du.make_data(dataset)
    f, mask, holding = du.compute_fields(d)
    score = daily_name_score(f, mask, HOLD['H3'])
    codes = list(map(str, d.A['codes']))
    if codes != reference_codes:
        raise ValueError('EA codes differ')
    outputs = []
    for day in DAYS:
        i = d.di[day]
        ranks = np.empty(len(codes), dtype=np.int32)
        ranks[np.argsort(-np.nan_to_num(score[i], nan=-1e9))] = np.arange(len(codes))
        pcts = {key: pct(f[key][i - 1:i], mask[i:i + 1])[0] for group in HOLD['H3'] for key in group}
        expected = audit[day]
        for code in CODES:
            j = codes.index(code)
            if bool(holding[i, j]) != (j in expected['holding']):
                raise AssertionError('EA holding did not reproduce ' + day + ' ' + code)
            candidate = next((row for row in expected['candidates'] if row[0] == j), None)
            record = {'day': day, 'code': code, 'active': bool(mask[i, j]), 'h3': bool(holding[i, j]),
                      'previous_h3': bool(holding[i - 1, j]), 'rank': int(ranks[j]), 'score': finite(score[i, j]),
                      'factors': {key: {'value': finite(f[key][i - 1, j]), 'percentile': finite(pcts[key][j])}
                                  for key in pcts}, 'candidate': candidate}
            if candidate is not None:
                e21 = ema(d.c[:, j:j + 1].astype(float), 21)[:, 0].astype(np.float32)
                stop = candidate[2] * float(d.c[i, j])
                record['outcome'] = next_open_outcome(d.A['open'][:, j], d.A['high'][:, j],
                                                      d.A['low'][:, j], d.A['close'][:, j], e21, i + 1, stop)
            outputs.append(record)
    target = du.REPORTS / f'strong_continue_ec_{mode}.json'
    out = {'ea_full_sha256': sha(full_path), 'ea_cut_sha256': sha(cut_path),
           'script_sha256': sha(Path(__file__)), 'rows': outputs}
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main(sys.argv[1])
