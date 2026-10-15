"""W24 exploration analysis helpers (selection data only)."""
import math
import sys
from collections import defaultdict

import numpy as np


def load(path):
    z = np.load(path, allow_pickle=False)
    d = z['data']
    return {name: d[:, k] for k, name in enumerate(z['fields'])}


def clustered(day, v):
    """Mean and day-clustered t of v."""
    ok = np.isfinite(v)
    day, v = day[ok], v[ok]
    if len(v) < 50:
        return math.nan, math.nan, len(v)
    m = v.mean()
    sums = defaultdict(float)
    for d, x in zip(day, v - m):
        sums[d] += x
    infl = np.array(list(sums.values())) / len(v)
    n = len(infl)
    se = math.sqrt(n / (n - 1) * (infl ** 2).sum())
    return m, m / se, len(v)


def quintile_spread(day, x, y):
    """Top minus bottom quintile of y, quintiles by checkpoint-free rank of x."""
    ok = np.isfinite(x) & np.isfinite(y)
    x, y, day = x[ok], y[ok], day[ok]
    lo, hi = np.quantile(x, [0.2, 0.8])
    v = np.where(x >= hi, y, np.where(x <= lo, -y, np.nan))
    return clustered(day, v)


if __name__ == '__main__':
    F = load(sys.argv[1])
    base = F['tpb'] >= 2
    print('obs tpb>=2', base.sum(), 'tpb>=5', (F['tpb'] >= 5).sum())
    feats = ['gap', 'r_open', 'r_30', 'vwap_dev', 'pos', 'tally', 'all_same', 'last_side',
             'hsi_open', 'hsi_30', 'hsi_prev']
    for tier, mask in (('tpb>=2', base), ('tpb>=5', F['tpb'] >= 5)):
        print('\n== direction, sign(x)*future, bp (t) --', tier)
        print('%-10s %18s %18s %18s %18s' % ('feature', 'f30', 'f60', 'fclose', 'Q5-Q1 fclose'))
        for name in feats:
            x = F[name][mask]
            out = []
            for tgt in ('f30', 'f60', 'fclose'):
                m, t, n = clustered(F['day'][mask], np.sign(x) * F[tgt][mask])
                out.append('%7.2f (%5.1f)' % (m * 1e4, t))
            m, t, n = quintile_spread(F['day'][mask], x, F['fclose'][mask])
            out.append('%7.2f (%5.1f)' % (m * 1e4, t))
            print('%-10s ' % name + '  '.join(out))
