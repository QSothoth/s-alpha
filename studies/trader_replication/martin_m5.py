"""M5: choosing among the day's intraday triggers with what was known at each trigger.  notes/PREREG_M5.md

    $PY -m studies.trader_replication.martin_m5
"""
from dataclasses import replace
import csv
import gzip
from pathlib import Path

import numpy as np

from . import panels, review as RV, systems as SY, ticket_t4 as T4, watchlist as WL
from .martin_m1 import report
from .martin_words import FOLDS
from .pick_model import fit

ROOT = Path(__file__).resolve().parents[2]
NB = 78
CACHE = ROOT / 'data' / 'martin-luk-cache' / 'm5_fires.npy'
NAMES = ('score', 'early', 'width', 'day', 'from_open', 'gap', 'off_high', 'depth', 'rvol')


def bars():
    z = np.load(ROOT / 'data' / 'martin-luk-cache' / 'k5.npz', allow_pickle=True)
    days, syms, arr = z['days'].astype(str), z['syms'].astype(str), z['arr']
    have = set(syms)
    for s, sym in enumerate(syms):
        yield sym, days, arr[:, s]
    del arr
    for f in sorted((ROOT / 'data' / 'martin-luk-k5-r8').glob('*.csv.gz')):
        sym = f.name.split('.')[0]
        if sym in have:
            continue
        with gzip.open(f, 'rt', newline='') as fh:
            rd = csv.reader(fh)
            next(rd)
            di, dl, a = {}, [], []
            for t, *v in rd:
                b = (int(t[11:13]) * 60 + int(t[14:16]) - 570) // 5 - 1
                if not 0 <= b < NB or t[:10] < '2023-12-01':
                    continue
                k = di.get(t[:10])
                if k is None:
                    k = di[t[:10]] = len(dl)
                    dl.append(t[:10])
                    a.append(np.full((6, NB), np.nan, np.float32))
                a[k][:, b] = [float(x) for x in v[:6]]
        if a:
            yield sym, np.array(dl), np.stack(a, 1)


def first(o, h, l, c, to):
    fin = np.flatnonzero(np.isfinite(c))
    if len(fin) < 20:
        return None
    o, h, l, c, to = o[fin], h[fin], l[fin], c[fin], to[fin]
    armed = False
    for t in range(3, len(c) - 1):
        armed = armed or (c[t] < c[t - 1] < c[t - 2]) or l[t] < l[:3].min()
        if armed and t >= 4 and h[t] > h[t - 1]:
            fill = max(o[t], h[t - 1])
            low = l[:t].min()
            w = 1 - low / fill
            if w > .03 or w < .003:
                armed = False
                continue
            return fill, low, float((l[t:] <= low).any()), fin[t], h[:t].max(), np.nansum(to[:t]), o[0]
    return None


def fires(A, rk, score):
    days = {str(d): i for i, d in enumerate(A['days'])}
    code = {str(c).replace('US.', ''): j for j, c in enumerate(A['codes'])}
    C, H, L, T = (A[k].astype(float) for k in ('close', 'high', 'low', 'turnover'))
    rng, to20 = WL.roll_mean(H / L - 1, 20), WL.roll_mean(T, 20)
    rows = []
    for sym, ds, a in bars():
        j = code.get(sym)
        if j is None:
            continue
        for i, day in enumerate(ds):
            d = days.get(str(day))
            if d is None or day < '2024-01-02' or d < 1 or rk[d, j] >= 100 or not np.isfinite(a[3, i]).any():
                continue
            s = C[d, j] / a[3, i][np.isfinite(a[3, i])][-1]
            if not np.isfinite(s):
                continue
            x = first(a[0, i] * s, a[1, i] * s, a[2, i] * s, a[3, i] * s, a[5, i], )
            if not x:
                continue
            fill, low, stopped, t, hod, turn, op = x
            pc, ad = C[d - 1, j], rng[d - 1, j]
            if not (np.isfinite(ad) and ad > 0):
                continue
            rv = turn / (to20[d - 1, j] * (t + 1) / NB) if to20[d - 1, j] > 0 else np.nan
            rows.append((d, j, fill, low, stopped, score[d, j], -t, -(1 - low / fill) / ad, (fill / pc - 1) / ad, (fill / op - 1) / ad, (op / pc - 1) / ad, -(1 - fill / hod) / ad, -(1 - low / op) / ad, rv))
    out = np.array(rows, float)
    np.save(CACHE, out)
    return out


def matrices(R):
    day = {}
    for i, d in enumerate(R[:, 0].astype(int)):
        day.setdefault(d, []).append(i)
    X = np.zeros((len(R), len(NAMES)))
    for d, ix in day.items():
        ix = np.array(ix)
        v = R[ix, 5:14]
        for c in range(v.shape[1]):
            x = v[:, c]
            ok = np.isfinite(x)
            q = np.full(len(x), .5)
            if ok.sum() > 1:
                q[ok] = (x[ok][:, None] > x[ok]).mean(1) + .5 * ((x[ok][:, None] == x[ok]).mean(1) - 1 / ok.sum())
            X[ix, c] = q - .5
    return X, day


def book(R, pr, n, size):
    out = [[] for _ in range(size)]
    for d in sorted(set(R[:, 0].astype(int))):
        ix = np.flatnonzero(R[:, 0] == d)
        for i in ix[np.argsort(-pr[ix])][:n]:
            e = ((float(-pr[i]),), int(R[i, 1]), 1, float(R[i, 2]), float(R[i, 3]), 'his')
            out[d].append(e + ((float(R[i, 3]),) if R[i, 4] else ()))
    return out


def main():
    W, cfg = SY.get('martin_luk').load()
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    reg, rules, mask, pool = W.build(A, cfg)
    rk = T4.ranks(A, pool)
    score = np.load(ROOT / 'data' / 'martin-luk-cache' / 'm1_score.npy').astype(float)
    R = np.load(CACHE) if CACHE.exists() else fires(A, rk, score)
    X, day = matrices(R)
    idx = {(int(a), int(b)): i for i, (a, b) in enumerate(R[:, :2])}
    his = [x for x in base.located(A, base.trades()) if x[0].side == 'long' and x[0].dated and x[0].entry_date >= '2024-01-02']
    pos = []
    for t, j, a, z in his:
        got = [idx[(d, j)] for d in range(a, z + 1) if (d, j) in idx]
        if got:
            pos.append((t.entry_date, got[0]))
    print('rows', len(R), 'per day', round(len(R) / len(day), 1), 'his fired', len(pos), 'sel', sum(p[0] <= '2025-12-31' for p in pos), 'of', len(his), flush=True)
    days = [str(x) for x in A['days']]
    s = np.zeros(len(R))
    for a, b in FOLDS:
        tr = []
        for dt, i in pos:
            if not a <= dt <= b:
                ix = np.array(day[int(R[i, 0])])
                tr.append((X[ix], int(np.flatnonzero(ix == i)[0])))
        w = fit(tr, X.shape[1], 3.0)
        m = np.array([a <= days[int(d)] <= b for d in R[:, 0]])
        s[m] = X[m] @ w
        print(a, dict(zip(NAMES, w.round(2))), flush=True)
    early = X[:, 1]
    plain = np.nan_to_num(X[:, 8]) + np.nan_to_num(X[:, 3])
    def hits(p):
        pl = []
        for dt, i in pos:
            ix = np.array(day[int(R[i, 0])])
            pl.append(int((p[ix] > p[i]).sum()))
        pl = np.array(pl)
        return {n: round(float((pl < n).mean()), 2) for n in (1, 2, 4, 8)}
    rand = {n: round(float(np.mean([min(1, n / len(day[int(R[i, 0])])) for _, i in pos])), 2) for n in (1, 2, 4, 8)}
    res = dict(random=rand, hit=dict(logit=hits(s), early=hits(early), plain=hits(plain)))
    print(res, flush=True)
    show = lambda k, r: print(k, {y: round(v, 2) for y, v in r['by_year'].items()}, f"dd {r['maxdd']:.2f} n/y {r['per_year']:.0f} win {r['win']:.3f} aw {r['avg_win']:+.3f} al {r['avg_loss']:+.3f} dw {r['days_win']:.1f} strict {r['strict']}/{r['of']} 2026 {r['strict26']}/{r['of26']}", flush=True)
    ru = replace(rules, max_new_long=0, max_new_by_kind={}, max_position=.25, max_gross=2.8, intraday_kinds=('his',), trail='e9', stop_ema_buffer=.03)
    g = np.random.default_rng(2)
    plans = dict(M5A=(early, 4), M5B=(s, 4), M5C=(s, 8), M5D=(plain, 4), M5E=(plain, 8), **{f'rand4_{i}': (g.random(len(R)), 4) for i in range(5)}, **{f'rand8_{i}': (g.random(len(R)), 8) for i in range(5)})
    for k, (p, n) in plans.items():
        st, tr = base.run(A, book(R, p, n, len(A['days'])), panels.WINDOW, pool, ru, placebo=0, audit=True)
        res[k] = report(base, A, st, tr, his)
        show(k, res[k])
        RV.write('martin_m5.json', res)


if __name__ == '__main__':
    main()
