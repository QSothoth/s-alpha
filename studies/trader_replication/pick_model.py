"""Choosing inside the evening list by a conditional logit: his name against the other names of that list on that day.
Every feature is the within-day percentile of a daily-bar measure known at the close.  Trained on 2024-25, scored on 2026,
and checked on what the picks earn, every day, not only on his days.

    $PY -m studies.trader_replication.pick_model
"""
from __future__ import annotations

import numpy as np

from . import review as RV, systems as SY, ticket_t4 as T4, watchlist as WL
from .martin_list import ema
from .pick_map import panel

K = 100
NAMES = ('g20', 'g60', 'g120', 'rs20', 'rs60', 'acc20', 'acc60', 'big20', 'big60', 'above21', 'above50', 'from_hi', 'tight5', 'dry5', 'money5', 'money20', 'stay20', 'stay', 'climb', 'adr', 'low_vol')
DAY = ('gain', 'over_pdh', 'to_e9', 'to_e21', 'close_pos', 'gapd', 'vol', 'touch_e9', 'touch_e21')


def features(A, rk):
    m, ret = panel(A, rk)
    lag = lambda x: np.vstack([np.full((1, x.shape[1]), np.nan), x[:-1]])
    F = {k: lag(m[k]) for k in NAMES}
    c, h, l, o, v = (A[k].astype(float) for k in ('close', 'high', 'low', 'open', 'turnover'))
    rng = lag(WL.roll_mean(h / l - 1, 20))
    e9, e21 = ema(c, 9), ema(c, 21)
    with np.errstate(all='ignore'):
        F.update(gain=(c / lag(c) - 1) / rng, over_pdh=(c / lag(h) - 1) / rng, to_e9=(c / e9 - 1) / rng, to_e21=(c / e21 - 1) / rng, close_pos=(c - l) / (h - l), gapd=(o / lag(c) - 1) / rng,
                 vol=v / lag(WL.roll_mean(v, 20)), touch_e9=(l / e9 - 1) / rng, touch_e21=(l / e21 - 1) / rng)
    return F


def day_matrix(F, keys, names, d):
    X = np.full((len(names), len(keys)), .5)
    for i, k in enumerate(keys):
        v = F[k][d, names]
        ok = np.isfinite(v)
        if ok.sum() > 2:
            X[ok, i] = (v[ok][:, None] > v[ok]).mean(1)
    return X - .5


def fit(samples, n, ridge, steps=400, lr=.3):
    w = np.zeros(n)
    for _ in range(steps):
        g = -ridge * w
        for X, y in samples:
            s = X @ w
            p = np.exp(s - s.max())
            p /= p.sum()
            g += X[y] - p @ X
        w += lr * g / len(samples)
    return w


def main():
    W, cfg = SY.get('martin_luk').load()
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    e, rules, mask, pool = W.build(A, cfg)
    rk = T4.ranks(A, pool)
    F = features(A, rk)
    keys = NAMES + DAY
    di = {str(d): i for i, d in enumerate(A['days'])}
    his = [(t, j) for t, j, a, z in base.located(A, base.trades()) if t.side == 'long' and t.dated and t.entry_date >= '2024-01-02' and t.entry_date in di]
    data = {'sel': [], 'val': []}
    for t, j in his:
        d = di[t.entry_date]
        if rk[d, j] >= K:
            continue
        names = np.flatnonzero(rk[d] < K)
        data['sel' if t.entry_date <= '2025-12-31' else 'val'].append((day_matrix(F, keys, names, d), int(np.flatnonzero(names == j)[0])))
    print('in list', len(data['sel']), len(data['val']), 'features', len(keys))
    out = {}
    def place(w, s):
        return [int(((X @ w) > (X @ w)[y]).sum()) for X, y in s]
    for ridge in (1, 3, 10):
        # leave-one-out on selection, the only honest read on so few positives
        loo = []
        for i in range(len(data['sel'])):
            w = fit(data['sel'][:i] + data['sel'][i + 1:], len(keys), ridge, steps=150)
            loo += place(w, [data['sel'][i]])
        w = fit(data['sel'], len(keys), ridge)
        v = place(w, data['val'])
        hit = lambda p, n: round(float(np.mean(np.array(p) < n)), 2)
        out[ridge] = dict(loo={n: hit(loo, n) for n in (4, 10, 20)}, val={n: hit(v, n) for n in (4, 10, 20)}, w=dict(sorted(zip(keys, w.round(2).tolist()), key=lambda kv: -abs(kv[1]))[:10]))
        print('ridge', ridge, 'LOO', out[ridge]['loo'], 'val', out[ridge]['val'], 'random', {n: n / K for n in (4, 10, 20)}, out[ridge]['w'], flush=True)
    RV.write('pick_model_martin.json', {str(k): v for k, v in out.items()})




def scores(A, rk, F, keys, w):
    s = np.full(rk.shape, np.nan)
    for d in range(1, len(rk)):
        names = np.flatnonzero(rk[d] < K)
        if len(names) >= 10:
            s[d, names] = day_matrix(F, keys, names, d) @ w
    return s


def train(A, base, rk, F, keys, ridge=3.0, upto='2025-12-31'):
    di = {str(d): i for i, d in enumerate(A['days'])}
    data = []
    for t, j, a, z in base.located(A, base.trades()):
        if t.side == 'long' and t.dated and '2024-01-02' <= t.entry_date <= upto and t.entry_date in di and rk[di[t.entry_date], j] < K:
            d = di[t.entry_date]
            names = np.flatnonzero(rk[d] < K)
            data.append((day_matrix(F, keys, names, d), int(np.flatnonzero(names == j)[0])))
    return fit(data, len(keys), ridge)


def book(A, s, n, gate, width):
    c, l = A['close'].astype(float), A['low'].astype(float)
    out = []
    for d in range(len(c)):
        row = []
        if (gate is None or gate[d]) and np.isfinite(s[d]).any():
            order = np.argsort(-np.nan_to_num(s[d], nan=-1e9))[:n]
            for j in order:
                j = int(j)
                st = min(max(l[d, j], c[d, j] * (1 - width)), c[d, j] * .99)
                row.append((-float(s[d, j]), j, 1, float(c[d, j]), float(st), 'list'))
        out.append(row)
    return out


def account():
    from dataclasses import replace
    from . import panels
    W, cfg = SY.get('martin_luk').load()
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    reg, rules, mask, pool = W.build(A, cfg)
    rk = T4.ranks(A, pool)
    F = features(A, rk)
    keys = NAMES + DAY
    w = train(A, base, rk, F, keys)
    s = scores(A, rk, F, keys, w)
    np.save('/tmp/martin_score.npy', s.astype(np.float32))
    gate = base.market_gate(A, cfg)
    shorts = [[((0.0,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:]) for e in lst if e[2] <= 0] for lst in reg]
    his = [x for x in base.located(A, base.trades()) if x[0].side == 'long' and x[0].dated and x[0].entry_date >= '2024-01-02']
    sel = [x for x in his if x[0].entry_date <= '2025-12-31']
    val = [x for x in his if x[0].entry_date > '2025-12-31']
    res = {}
    for k, (n, g, width) in dict(n1=(1, gate, .05), n2=(2, gate, .05), n4=(4, gate, .05), n4free=(4, None, .05), n2t3=(2, gate, .03), n4t3=(4, gate, .03)).items():
        e = [[((x[0],),) + tuple(x[1:]) for x in a] + b for a, b in zip(book(A, s, n, g, width), shorts)]
        st, tr = base.run(A, e, panels.WINDOW, pool, rules, placebo=0, audit=True)
        st.pop('_curve', None)
        b = st['behaviour']
        o = {(t['code'], t['entry']) for t in tr if t['side'] > 0}
        got = lambda rows: sum(any((str(A['codes'][j]), str(A['days'][d])) in o for d in range(a, z + 1)) for t, j, a, z in rows)
        r = res[k] = dict(by_year=st['by_year'], maxdd=st['maxdd'], per_year=b['per_year'], win=b['win'], avg_win=b['avg_win'], avg_loss=b['avg_loss'], days_win=b['days_win'], sel=got(sel), val=got(val))
        print(k, {y: round(v, 2) for y, v in st['by_year'].items()}, f"dd {st['maxdd']:.2f} n/y {b['per_year']:.0f} win {b['win']:.3f} aw {b['avg_win']:+.3f} al {b['avg_loss']:+.3f} dw {b['days_win']:.1f} bought {r['sel']}/{len(sel)} 2026 {r['val']}/{len(val)}", flush=True)
        RV.write('pick_account_martin.json', res)


if __name__ == '__main__':
    import sys
    account() if sys.argv[1:] == ['account'] else main()
