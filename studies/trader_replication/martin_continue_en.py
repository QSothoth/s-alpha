"""EN: reconstruct the QXO/TEL peer-potential divergence without changing rules."""
import gc
import json
from pathlib import Path
import sys

import numpy as np
from studies import trader_data
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_ea as ea
from studies.trader_replication import martin_continue_em as em
from studies.trader_replication.martin_continue_dq import sha

DAY, CUT = '2026-05-12', '2026-06-30'
TARGETS = ('US.QXO', 'US.TEL')


def main(mode):
    if mode not in ('full', 'cut'):
        raise ValueError('expected full or cut')
    em_path = du.REPORTS / f'strong_continue_em_{mode}.json'
    reference = json.loads(em_path.read_text())
    if reference['script_sha256'] != sha(Path(em.__file__)):
        raise ValueError('EM source differs')
    peers = {r['code']: r for r in reference['peers']}
    expected = {code: peers[code]['factors']['peer_pot']['value'] for code in TARGETS}
    del peers, reference
    gc.collect()
    base = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    ds = base if mode == 'full' else ea.LimitedDataset(base, CUT)
    d = du.make_data(ds)
    fields, _, _ = du.compute_fields(d)
    codes = list(map(str, d.A['codes']))
    t = d.di[DAY]
    graph = next(i for i in range(t, 59, -1) if i % 5 == 0 and np.count_nonzero(d.rk[i] < 300) >= 30)
    names = np.flatnonzero(d.rk[graph] < 300)
    rr = np.empty((40, len(names)), dtype=np.float32)
    with np.errstate(divide='ignore', invalid='ignore'):
        for k, i in enumerate(range(graph - 39, graph + 1)):
            r = d.c[i] / d.c[i - 1] - 1
            median = np.nanmedian(np.where(d.rk[i] < 300, r, np.nan))
            rr[k] = np.nan_to_num(r - median)[names]
    w = rr - rr.mean(0)
    sd = w.std(0) + 1e-6
    corr = (w.T @ w) / len(w) / np.outer(sd, sd)
    near = corr >= .5
    adr5 = np.empty((5, len(codes)), dtype=np.float64)
    with np.errstate(divide='ignore', invalid='ignore'):
        for start in range(0, len(codes), 64):
            sl = slice(start, start + 64)
            result = du._ROLL_MEAN(d.h[:, sl] / d.l[:, sl] - 1, 5)
            adr5[:, sl] = result[t - 4:t + 1]
    pot = np.zeros((5, len(codes)), dtype=bool)
    days = []
    with np.errstate(divide='ignore', invalid='ignore'):
        for k, i in enumerate(range(t - 4, t + 1)):
            r = d.c[i] / d.c[i - 1] - 1
            eligible = np.flatnonzero((d.to20[i] >= 5e7) & (adr5[k] >= .035) & np.isfinite(r))
            order = eligible[np.argsort(-r[eligible])]
            if len(eligible) > 60:
                pot[k, order[:50]] = True
            days.append({'day': d.days[i], 'eligible': len(eligible),
                         'selected': [codes[j] for j in order[:50]] if len(eligible) > 60 else [],
                         'top60': [[codes[j], float(r[j])] for j in order[:60]]})
    names_pos = {codes[j]: i for i, j in enumerate(names)}
    result = {}
    for code in TARGETS:
        k = names_pos[code]
        members = near[k]
        computed = float((members * (pot[:, names].sum(axis=0) / 5.0)).sum() / members.sum())
        actual = float(fields['peer_pot'][t, codes.index(code)])
        if abs(computed - actual) > 1e-7 or abs(actual - expected[code]) > 1e-7:
            raise AssertionError('peer_pot does not reproduce ' + code)
        result[code] = {'peer_pot': actual, 'neighbors': [codes[j] for j in names[members]],
                        'correlations': [[codes[j], float(v)] for j, v in zip(names, corr[k])]}
    out = {'em_sha256': sha(em_path), 'script_sha256': sha(Path(__file__)), 'target_day': DAY,
           'graph_day': d.days[graph], 'graph_names': [codes[j] for j in names], 'potentials': days, 'targets': result}
    target = du.REPORTS / f'strong_continue_en_{mode}.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n')
    print('wrote', target, 'graph', d.days[graph], flush=True)


if __name__ == '__main__':
    main(sys.argv[1])
