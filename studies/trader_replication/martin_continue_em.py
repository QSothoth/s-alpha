"""EM: trace ORCL's as-of-fast H3 membership and score components."""
import gc
import json
from pathlib import Path
import sys

import numpy as np
from studies import trader_data
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ea as ea
from studies.trader_replication import martin_continue_ee as ee
from studies.trader_replication import martin_continue_ej as ej
from studies.trader_replication.martin_continue_bv import daily_name_score
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_strong import pct
from studies.trader_replication.martin_strong_scan import HOLD, hold_sim

DAY, CODE, CUT = '2026-05-13', 'US.ORCL', '2026-06-30'


def finite(x):
    return float(x) if np.isfinite(x) else None


def main(mode):
    if mode not in ('full', 'cut'):
        raise ValueError('expected full or cut')
    p, q = du.REPORTS / 'strong_continue_ej_full.json', du.REPORTS / f'strong_continue_ej_{CUT}.json'
    full, cut = json.loads(p.read_text()), json.loads(q.read_text())
    if full['script_sha256'] != sha(Path(ej.__file__)) or cut['dataset_digest'] != full['dataset_digest']:
        raise ValueError('EJ inputs differ')
    digest = full['dataset_digest']
    del full, cut
    gc.collect()
    base = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if base.digest() != digest:
        raise ValueError('dataset differs')
    dataset = base if mode == 'full' else ea.LimitedDataset(base, CUT)
    d = du.make_data(dataset)
    fields, mask, _ = du.compute_fields(d)
    events, positions = ee.source_inputs(dataset, d.days, list(map(str, d.A['codes'])))
    del positions
    fast = np.empty(events.shape, np.float32)
    for start in range(0, events.shape[1], 64):
        sl = slice(start, start + 64)
        fast[:, sl] = du._ROLL_MEAN(events[:, sl].astype(np.float32), 250)
    fields['fast250'] = fast
    del events, fast
    gc.collect()
    score = daily_name_score(fields, mask, HOLD['H3'])
    holding = hold_sim(score, 12, 36)
    codes = list(map(str, d.A['codes']))
    j = codes.index(CODE)
    history = []
    for i, day in enumerate(d.days):
        if not '2024-01-02' <= day <= CUT:
            continue
        order = np.argsort(-np.nan_to_num(score[i], nan=-1e9))
        history.append({'day': day, 'active': bool(mask[i, j]), 'h3': bool(holding[i, j]),
                        'rank': int(np.flatnonzero(order == j)[0]), 'score': finite(score[i, j])})
    i = d.di[DAY]
    ranks = np.empty(len(codes), dtype=np.int32)
    ranks[np.argsort(-np.nan_to_num(score[i], nan=-1e9))] = np.arange(len(codes))
    pcts = {key: pct(fields[key][i - 1:i], mask[i:i + 1])[0] for group in HOLD['H3'] for key in group}
    peers = []
    for k in np.flatnonzero(mask[i]):
        peers.append({'code': codes[k], 'rank': int(ranks[k]), 'score': finite(score[i, k]),
                      'factors': {key: {'value': finite(fields[key][i - 1, k]), 'pct': finite(pcts[key][k])} for key in pcts}})
    out = {'ej_full_sha256': sha(p), 'ej_cut_sha256': sha(q), 'script_sha256': sha(Path(__file__)),
           'day': DAY, 'history': history, 'peers': peers}
    target = du.REPORTS / f'strong_continue_em_{mode}.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    print('wrote', target, 'peers', len(peers), flush=True)


if __name__ == '__main__':
    main(sys.argv[1])
