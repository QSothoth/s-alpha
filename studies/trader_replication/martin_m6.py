"""M6: which measure, known at the trigger, separates his name from the day's other triggers?  Each factor alone, on both
parts of the ledger, then the groups together, fold-held-out.  Theme and his own repeat names join the price measures.

    $PY -m studies.trader_replication.martin_m6
"""
import json
from pathlib import Path

import numpy as np

from . import review as RV, systems as SY, ticket_t4 as T4, watchlist as WL
from .martin_m5 import CACHE, NAMES, matrices
from .martin_words import FOLDS
from .pick_model import fit

ROOT = Path(__file__).resolve().parents[2]
EXTRA = ('adr', 'price', 'turn', 'stick120', 'stick20', 'his_before', 'his_n', 'fire10', 'ind_fires', 'ind_rank', 'ind_ret5', 'ind_ret20', 'clu_n', 'clu_rank', 'clu_ret5', 'age', 'off52')


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
    R = np.load(CACHE)
    X0, day = matrices(R)
    C, H, L, T = (A[k].astype(float) for k in ('close', 'high', 'low', 'turnover'))
    rng, to20 = WL.roll_mean(H / L - 1, 20), WL.roll_mean(T, 20)
    r1 = np.full(C.shape, np.nan)
    r1[1:] = C[1:] / C[:-1] - 1
    ind = json.loads((ROOT / 'data' / 'martin-luk-cache' / 'industry.json').read_text(encoding='utf-8'))
    labels = sorted(set(ind.values()))
    gid = np.array([labels.index(ind[str(c)]) if str(c) in ind else -1 for c in A['codes']])
    ret5, ret20 = np.full(C.shape, np.nan), np.full(C.shape, np.nan)
    ret5[5:], ret20[20:] = C[5:] / C[:-5] - 1, C[20:] / C[:-20] - 1
    ig5, ig20 = np.full((len(C), len(labels)), np.nan), np.full((len(C), len(labels)), np.nan)
    for g in range(len(labels)):
        m = np.flatnonzero(gid == g)
        if len(m) >= 3:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                ig5[:, g], ig20[:, g] = np.nanmedian(ret5[:, m], 1), np.nanmedian(ret20[:, m], 1)
    first = np.argmax(np.isfinite(C), 0)
    hi252 = np.full(C.shape, np.nan)
    for i in range(len(C)):
        hi252[i] = np.nanmax(H[max(0, i - 251):i + 1], axis=0) if np.isfinite(H[max(0, i - 251):i + 1]).any() else np.nan
    in100 = (rk < 100).astype(float)
    cum = np.vstack([np.zeros((1, C.shape[1])), np.cumsum(in100, 0)])
    his = [x for x in base.located(A, base.trades()) if x[0].side == 'long' and x[0].dated and x[0].entry_date >= '2024-01-02']
    all_long = [x for x in base.located(A, base.trades()) if x[0].side == 'long' and x[0].dated]
    bought = {}
    for t, j, a, z in all_long:
        bought.setdefault(j, []).append(a)
    fired = {}
    for d, j in R[:, :2].astype(int):
        fired.setdefault(j, []).append(d)
    Ex = np.full((len(R), len(EXTRA)), np.nan)
    for d, ix in day.items():
        ix = np.array(ix)
        js = R[ix, 1].astype(int)
        p = d - 1
        dayg = R[ix, 8]
        col = dict(adr=rng[p, js], price=C[p, js], turn=np.log(to20[p, js] + 1), stick120=cum[d, js] - cum[max(0, d - 120), js], stick20=cum[d, js] - cum[max(0, d - 20), js],
                   his_before=np.array([float(any(a < d for a in bought.get(j, []))) for j in js]), his_n=np.array([float(sum(a < d for a in bought.get(j, []))) for j in js]),
                   fire10=np.array([float(sum(d - 10 <= x < d for x in fired.get(j, []))) for j in js]), age=np.minimum(d - first[js], 500.0), off52=C[p, js] / hi252[p, js] - 1)
        g = gid[js]
        col['ind_fires'] = np.array([float((g == x).sum()) for x in g])
        ir = np.zeros(len(js))
        for x in set(g.tolist()):
            m = g == x
            ir[m] = pct(dayg[m])
        col['ind_rank'] = ir
        col['ind_ret5'] = np.where(g >= 0, ig5[p, g], np.nan)
        col['ind_ret20'] = np.where(g >= 0, ig20[p, g], np.nan)
        w = r1[max(0, p - 59):p + 1][:, js]
        w = np.nan_to_num(w - np.nanmean(w, 0))
        sd = w.std(0) + 1e-9
        rho = (w.T @ w) / len(w) / np.outer(sd, sd)
        near = rho >= .5
        col['clu_n'] = near.sum(1).astype(float)
        col['clu_rank'] = np.array([(dayg[near[i]] <= dayg[i]).mean() for i in range(len(js))])
        col['clu_ret5'] = np.array([np.nanmean(ret5[p, js[near[i]]]) for i in range(len(js))])
        for c, k in enumerate(EXTRA):
            Ex[ix, c] = col[k]
    PX = np.zeros(Ex.shape)
    for d, ix in day.items():
        ix = np.array(ix)
        for c in range(Ex.shape[1]):
            PX[ix, c] = pct(Ex[ix, c])
    X = np.hstack([X0, PX])
    names = NAMES + EXTRA
    idx = {(int(a), int(b)): i for i, (a, b) in enumerate(R[:, :2])}
    pos = []
    for t, j, a, z in his:
        got = [idx[(d, j)] for d in range(a, z + 1) if (d, j) in idx]
        if got:
            pos.append((t.entry_date, got[0]))
    sel = [i for dt, i in pos if dt <= '2025-12-31']
    val = [i for dt, i in pos if dt > '2025-12-31']
    print('positives', len(sel), len(val), flush=True)
    res = dict(single={})
    for c, k in sorted(enumerate(names), key=lambda v: -abs(X[sel + val, v[0]].mean())):
        a, b = X[sel, c].mean() + .5, X[val, c].mean() + .5
        res['single'][k] = (round(float(a), 3), round(float(b), 3))
        print(f'{k:11} {a:.3f} {b:.3f}', flush=True)
    days = [str(x) for x in A['days']]
    def cv(cols, ridge=3.0):
        s = np.zeros(len(R))
        for a, b in FOLDS:
            tr = []
            for dt, i in pos:
                if not a <= dt <= b:
                    ix = np.array(day[int(R[i, 0])])
                    tr.append((X[ix][:, cols], int(np.flatnonzero(ix == i)[0])))
            w = fit(tr, len(cols), ridge)
            m = np.array([a <= days[int(d)] <= b for d in R[:, 0]])
            s[m] = X[m][:, cols] @ w
        pl = []
        for dt, i in pos:
            ix = np.array(day[int(R[i, 0])])
            pl.append(int((s[ix] > s[i]).sum()))
        pl = np.array(pl)
        return {n: round(float((pl < n).mean()), 2) for n in (1, 2, 4, 8)}, s
    I = {k: i for i, k in enumerate(names)}
    groups = dict(price=list(range(len(NAMES))), plus_name=list(range(len(NAMES))) + [I[k] for k in ('his_before', 'his_n', 'stick120', 'stick20', 'adr', 'turn', 'price', 'age')], plus_theme=list(range(len(NAMES))) + [I[k] for k in ('ind_fires', 'ind_rank', 'ind_ret5', 'ind_ret20', 'clu_n', 'clu_rank', 'clu_ret5')], everything=list(range(len(names))))
    res['random'] = {n: round(float(np.mean([min(1, n / len(day[int(R[i, 0])])) for _, i in pos])), 2) for n in (1, 2, 4, 8)}
    print('random', res['random'], flush=True)
    for k, cols in groups.items():
        res[k], s = cv(cols)
        print(k, res[k], flush=True)
        if k == 'everything':
            np.save(ROOT / 'data' / 'martin-luk-cache' / 'm6_score.npy', s)
    RV.write('martin_m6.json', res)
    from dataclasses import replace
    from . import panels
    from .martin_m1 import report
    from .martin_m5 import book
    p = X[:, I['score']] + X[:, I['turn']] + X[:, I['his_n']] - X[:, I['off_high']] + X[:, I['adr']]
    pl = np.array([int((p[np.array(day[int(R[i, 0])])] > p[i]).sum()) for _, i in pos])
    res['m7_hit'] = {n: round(float((pl < n).mean()), 2) for n in (1, 2, 4, 8)}
    print('m7 hits', res['m7_hit'], flush=True)
    ru = replace(rules, max_new_long=0, max_new_by_kind={}, max_position=.25, max_gross=2.8, intraday_kinds=('his',), trail='e9', stop_ema_buffer=.03)
    for n in (4, 8):
        st, tr = base.run(A, book(R, p, n, len(A['days'])), panels.WINDOW, pool, ru, placebo=0, audit=True)
        r = res[f'M7_{n}'] = report(base, A, st, tr, his)
        print(f'M7_{n}', {y: round(v, 2) for y, v in r['by_year'].items()}, f"dd {r['maxdd']:.2f} n/y {r['per_year']:.0f} win {r['win']:.3f} aw {r['avg_win']:+.3f} al {r['avg_loss']:+.3f} strict {r['strict']}/{r['of']} 2026 {r['strict26']}/{r['of26']}", flush=True)
    RV.write('martin_m6.json', res)


if __name__ == '__main__':
    main()
