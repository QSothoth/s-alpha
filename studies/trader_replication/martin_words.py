"""His description as daily-bar measures, read at t-1 against the evening list.

The hand score has fixed weights, but repeated research on these dates means it is not an independent out-of-sample
test. The historical cross-fold logit in main() also trains on later folds, so its output is noncausal and cannot
validate a tradable model.

    $PY -m studies.trader_replication.martin_words
"""
from __future__ import annotations

import numpy as np

from . import review as RV, systems as SY, ticket_t4 as T4, watchlist as WL
from .martin_list import ema
from .pick_model import DAY, K, NAMES, day_matrix, features, fit

# name -> direction in his words
WORDS = dict(spread=-1, tight=-1, rising=1, stack=1, above=1, basedays=1, range10=-1, firstpb=-1, hl=1, coc=1, wk_above=1, wk_near=-1, wk_tight=-1, wk_inside=1, wk_hl=1, scan=-1)
FOLDS = (('2024-01-01', '2024-12-31'), ('2025-01-01', '2025-06-30'), ('2025-07-01', '2025-12-31'), ('2026-01-01', '2026-06-30'), ('2026-07-01', '2026-12-31'))


def rmax(x, n):
    o = np.full(x.shape, np.nan)
    for i in range(n - 1, len(x)):
        o[i] = np.nanmax(x[i - n + 1:i + 1], axis=0)
    return o


def rmin(x, n):
    o = np.full(x.shape, np.nan)
    for i in range(n - 1, len(x)):
        o[i] = np.nanmin(x[i - n + 1:i + 1], axis=0)
    return o


def lagn(x, n):
    return np.vstack([np.full((n,) + x.shape[1:], np.nan), x[:-n]])


def weekly(A):
    """Completed-week bars mapped back to days: a day sees the weeks finished before its own week started."""
    import datetime as dt
    days = [str(d) for d in A['days']]
    wk = [dt.date.fromisoformat(d).isocalendar()[:2] for d in days]
    ends = [i for i in range(len(days)) if i + 1 == len(days) or wk[i + 1] != wk[i]]
    starts = [0] + [e + 1 for e in ends[:-1]]
    c, h, l = (A[k].astype(float) for k in ('close', 'high', 'low'))
    wc = np.full((len(ends), c.shape[1]), np.nan)
    wh, wl = wc.copy(), wc.copy()
    for i, (a, z) in enumerate(zip(starts, ends)):
        with np.errstate(all='ignore'):
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                wh[i], wl[i] = np.nanmax(h[a:z + 1], axis=0), np.nanmin(l[a:z + 1], axis=0)
        wc[i] = c[z]
    idx = np.searchsorted(np.array(ends), np.arange(len(days)), side='left') - 1   # last week finished before this day's week
    return wc, wh, wl, idx


def words(A, rk):
    c, h, l, v = (A[k].astype(float) for k in ('close', 'high', 'low', 'turnover'))
    rng = WL.roll_mean(h / l - 1, 20)
    e9, e21, e50 = ema(c, 9), ema(c, 21), ema(c, 50)
    r = c / lagn(c, 1) - 1
    F = {}
    import warnings
    warnings.simplefilter('ignore')
    with np.errstate(all='ignore'):
        F['spread'] = (e9 / e50 - 1) / rng
        F['tight'] = np.abs(e9 / e21 - 1) / rng
        F['rising'] = sum((x > lagn(x, 5)).astype(float) for x in (e9, e21, e50))
        F['stack'] = (e9 > e21).astype(float) + (e21 > e50).astype(float)
        F['above'] = (c > e9).astype(float) + (c > e21).astype(float)
        hh = rmax(h, 40)
        since = np.full(c.shape, 40.0)
        run = np.full(c.shape[1], 40.0)
        for i in range(len(c)):
            run = np.where(h[i] >= hh[i], 0, np.minimum(run + 1, 40))
            since[i] = run
        F['basedays'] = np.minimum(since, 10)
        F['range10'] = (rmax(h, 10) / rmin(l, 10) - 1) / rng
        touch = ((l <= e9) & ~(lagn(l, 1) <= lagn(e9, 1))).astype(float)
        F['firstpb'] = WL.roll_mean(touch, 20)
        F['hl'] = (rmin(l, 5) > lagn(rmin(l, 10), 5)).astype(float) + (lagn(rmin(l, 10), 5) > lagn(rmin(l, 15), 15)).astype(float)
        rec = ((r > rng) & (c > e21) & (lagn(c, 1) < lagn(e21, 1))).astype(float)
        F['coc'] = WL.roll_mean(rec, 10)
        wc, wh, wl, idx = weekly(A)
        w9, w21 = ema(wc, 9), ema(wc, 21)
        pick = lambda x: np.where((idx >= 0)[:, None], x[np.maximum(idx, 0)], np.nan)
        F['wk_above'] = (c > pick(w9)).astype(float) + (c > pick(w21)).astype(float)
        F['wk_near'] = np.abs(c / pick(w21) - 1) / rng
        wr = wh / wl - 1
        F['wk_tight'] = pick(wr / WL.roll_mean(wr, 10))
        F['wk_inside'] = pick(((wh <= lagn(wh, 1)) & (wl >= lagn(wl, 1))).astype(float))
        F['wk_hl'] = pick((rmin(wl, 3) > lagn(rmin(wl, 5), 3)).astype(float))
        # the potent scan: the prior day's strongest with at least 50 million traded and 3.5% weekly volatility
        vol = pick(wr)
        ok = (v >= 5e7) & (vol >= .035)
        rr = np.where(ok, r, np.nan)
        top = np.zeros(c.shape, bool)
        for i in range(len(c)):
            f = np.flatnonzero(np.isfinite(rr[i]))
            if len(f) > 50:
                top[i, f[np.argsort(-rr[i, f])[:50]]] = True
        since = np.full(c.shape, 60.0)
        run = np.full(c.shape[1], 60.0)
        for i in range(len(c)):
            run = np.where(top[i], 0, np.minimum(run + 1, 60))
            since[i] = run
        F['scan'] = since
    return {k: lagn(x, 1) for k, x in F.items()}


def signed_pct(F, keys, signs, names, d):
    return day_matrix(F, keys, names, d) * signs


def main():
    W, cfg = SY.get('martin_luk').load()
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    e, rules, mask, pool = W.build(A, cfg)
    rk = T4.ranks(A, pool)
    print('panel', A['close'].shape, flush=True)
    G = words(A, rk)
    F0 = features(A, rk)
    di = {str(d): i for i, d in enumerate(A['days'])}
    his = [(t, j) for t, j, a, z in base.located(A, base.trades()) if t.side == 'long' and t.dated and t.entry_date >= '2024-01-02' and t.entry_date in di]
    his = [(t, j) for t, j in his if rk[di[t.entry_date], j] < K]
    print('his in list', len(his), flush=True)
    wk = tuple(WORDS)
    signs = np.array([WORDS[k] for k in wk], float)
    rows, sc = [], {}
    pct = {k: {'sel': [], 'val': []} for k in wk}
    places = {'sel': [], 'val': []}
    for t, j in his:
        d = di[t.entry_date]
        names = np.flatnonzero(rk[d] < K)
        y = int(np.flatnonzero(names == j)[0])
        X = signed_pct(G, wk, signs, names, d)
        part = 'sel' if t.entry_date <= '2025-12-31' else 'val'
        for i, k in enumerate(wk):
            pct[k][part].append(float(X[y, i] + .5))
        s = X.mean(1)
        places[part].append(int((s > s[y]).sum()))
    out = {k: {p: round(float(np.mean(v[p])), 3) for p in v} for k, v in pct.items()}
    for k, v in sorted(out.items(), key=lambda kv: -(kv[1]['sel'] + kv[1]['val'])):
        print(f"{k:10} {v['sel']:.3f} {v['val']:.3f}", flush=True)
    hit = lambda p, n: round(float(np.mean(np.array(p) < n)), 2)
    res = dict(feat=out, words_score={p: {n: hit(v, n) for n in (4, 10, 20)} for p, v in places.items()})
    print('hand score hits', res['words_score'], flush=True)

    # Historical comparison only: other folds include later dates and must not be used as a forward model.
    def cv(keys, Fx, ridge=3.0):
        place = []
        for a, z in FOLDS:
            tr, te = [], []
            for t, j in his:
                d = di[t.entry_date]
                names = np.flatnonzero(rk[d] < K)
                row = (day_matrix(Fx, keys, names, d), int(np.flatnonzero(names == j)[0]))
                (te if a <= t.entry_date <= z else tr).append(row)
            w = fit(tr, len(keys), ridge)
            place += [int(((X @ w) > (X @ w)[y]).sum()) for X, y in te]
        return {n: hit(place, n) for n in (4, 10, 20)}
    all_ = {**F0, **G}
    old = NAMES + DAY
    res['cv_old'], res['cv_new'], res['cv_words_day'] = cv(old, all_), cv(old + wk, all_), cv(DAY + wk, all_)
    print('cv old', res['cv_old'], 'old+words', res['cv_new'], 'day+words', res['cv_words_day'], 'random', {n: n / K for n in (4, 10, 20)}, flush=True)
    RV.write('martin_words.json', res)


if __name__ == '__main__':
    main()
