"""The four factors that held in both parts of the ledger, equal weight, inside the full-market evening list (daily bars).
Does his name reach the top 4 / 10 / 20 of the 100 more often than the 20% / 39% / 49% of the trained baseline?

    $PY -m studies.trader_replication.martin_f4
"""
from pathlib import Path

import numpy as np

from . import review as RV, systems as SY, ticket_t4 as T4, watchlist as WL

ROOT = Path(__file__).resolve().parents[2]
K = 100


def pct(x):
    ok = np.isfinite(x)
    q = np.full(len(x), .5)
    if ok.sum() > 1:
        v = x[ok]
        q[ok] = (v[:, None] > v).mean(1) + .5 * ((v[:, None] == v).mean(1) - 1 / len(v))
    return q - .5


def main():
    W, cfg = SY.get('martin_luk').load()
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    reg, rules, mask, pool = W.build(A, cfg)
    rk = T4.ranks(A, pool)
    score = np.load(ROOT / 'data' / 'martin-luk-cache' / 'm1_score.npy').astype(float)
    H, L, T = (A[k].astype(float) for k in ('high', 'low', 'turnover'))
    rng, to20 = WL.roll_mean(H / L - 1, 20), WL.roll_mean(T, 20)
    di = {str(d): i for i, d in enumerate(A['days'])}
    longs = [(di[t.entry_date], j, t.entry_date) for t, j, a, z in base.located(A, base.trades()) if t.side == 'long' and t.dated and t.entry_date in di]
    bought = {}
    for d, j, _ in longs:
        bought.setdefault(j, []).append(d)
    test = [x for x in longs if x[2] >= '2024-01-02' and rk[x[0], x[1]] < K]
    def place(use):
        out = []
        for d, j, day in test:
            names = np.flatnonzero(rk[d] < K)
            s = np.zeros(len(names))
            if 'score' in use:
                s += pct(score[d, names])
            if 'turn' in use:
                s += pct(to20[d - 1, names])
            if 'adr' in use:
                s += pct(rng[d - 1, names])
            if 'his' in use:
                s += pct(np.array([float(sum(a < d for a in bought.get(n, []))) for n in names]))
            out.append((int((s > s[np.flatnonzero(names == j)[0]]).sum()), day))
        return out
    res = dict(n=len(test), of=sum(1 for x in longs if x[2] >= '2024-01-02'))
    print('in list', res['n'], 'of', res['of'], flush=True)
    for k, use in dict(four=('score', 'turn', 'adr', 'his'), no_his=('score', 'turn', 'adr'), score_only=('score',)).items():
        p = place(use)
        hit = lambda rows, n: round(float(np.mean([x[0] < n for x in rows])), 2)
        a, b = [x for x in p if x[1] <= '2025-12-31'], [x for x in p if x[1] > '2025-12-31']
        res[k] = dict(all={n: hit(p, n) for n in (4, 10, 20)}, y2425={n: hit(a, n) for n in (4, 10, 20)}, y2026={n: hit(b, n) for n in (4, 10, 20)}, n=(len(a), len(b)))
        print(k, res[k], flush=True)
    RV.write('martin_f4.json', res)


if __name__ == '__main__':
    main()
