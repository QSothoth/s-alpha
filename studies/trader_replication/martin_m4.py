"""M4, no limits: his intraday entries on the 5-minute bars we hold.  notes/M4_UNCONSTRAINED.md

    $PY -m studies.trader_replication.martin_m4
"""
from dataclasses import replace
import csv
import gzip
from pathlib import Path
import sys

import numpy as np

from . import panels, review as RV, systems as SY, ticket_t4 as T4, watchlist as WL
from .martin_m1 import report

ROOT = Path(__file__).resolve().parents[2]
NB = 78
CACHE = ROOT / 'data' / 'martin-luk-cache' / 'm4_fires.npy'


def bars():
    """{symbol: {day: 4 x 78 raw OHLC}} streamed per file, kept float32."""
    z = np.load(ROOT / 'data' / 'martin-luk-cache' / 'k5.npz', allow_pickle=True)
    days, syms, arr = z['days'].astype(str), z['syms'].astype(str), z['arr']
    for s, sym in enumerate(syms):
        yield sym, days, arr[:4, s]
    del arr
    for f in sorted((ROOT / 'data' / 'martin-luk-k5-r8').glob('*.csv.gz')):
        sym = f.name.split('.')[0]
        if sym in set(syms):
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
                    a.append(np.full((4, NB), np.nan, np.float32))
                a[k][:, b] = [float(x) for x in v[:4]]
        if a:
            yield sym, np.array(dl), np.stack(a, 1)


def trigger(o, h, l, c, kind, pc, adr):
    fin = np.flatnonzero(np.isfinite(c))
    if len(fin) < 20:
        return None
    o, h, l, c = o[fin], h[fin], l[fin], c[fin]
    orh, orl = h[:3].max(), l[:3].min()
    if kind == 'E':
        if o[0] / pc - 1 < max(adr, .05):
            return None
        for t in range(3, len(c)):
            if h[t] > orh:
                fill = max(o[t], orh)
                low = l[:t].min()               # only bars finished before the fill
                if 1 - low / fill > .05:
                    return None
                return fill, low, (l[t:] <= low).any()
        return None
    armed = False
    for t in range(3, len(c) - 1):
        if kind == 'U':
            armed = armed or l[t] < orl
        else:
            armed = armed or (c[t] < c[t - 1] < c[t - 2])
        if armed and h[t] > h[t - 1] and t >= 4:
            fill = max(o[t], h[t - 1])
            low = l[:t].min()                   # only bars finished before the fill
            w = 1 - low / fill
            if w > .03 or w < .003:
                armed = False
                continue
            return fill, low, (l[t:] <= low).any()
    return None


def fires(A):
    days = {str(d): i for i, d in enumerate(A['days'])}
    code = {str(c).replace('US.', ''): j for j, c in enumerate(A['codes'])}
    C, H, L = (A[k].astype(float) for k in ('close', 'high', 'low'))
    rng = WL.roll_mean(H / L - 1, 20)
    rows, seen = [], []
    for sym, ds, a in bars():
        j = code.get(sym)
        if j is None:
            continue
        seen.append(j)
        for i, day in enumerate(ds):
            d = days.get(str(day))
            if d is None or day < '2024-01-02' or d < 1 or not np.isfinite(a[3, i]).any():
                continue
            cl = a[3, i][np.isfinite(a[3, i])][-1]
            s = C[d, j] / cl
            if not np.isfinite(s):
                continue
            pc, ad = C[d - 1, j], rng[d - 1, j]
            for ki, kind in enumerate('UPE'):
                x = trigger(a[0, i] * s, a[1, i] * s, a[2, i] * s, a[3, i] * s, kind, pc, ad if np.isfinite(ad) else .05)
                if x:
                    rows.append((d, j, ki, x[0], x[1], float(x[2])))
    out = np.array(rows, float)
    np.save(CACHE, out)
    np.save(str(CACHE) + '.seen.npy', np.array(seen))
    return out


def book(A, F, kinds, rk, n, score=None):
    out = [[] for _ in A['days']]
    for d, j, k, fill, low, stopped in F:
        d, j, k = int(d), int(j), int(k)
        if k not in kinds or (rk is not None and rk[d, j] >= 100):
            continue
        pr = -(score[d, j] if score is not None and np.isfinite(score[d, j]) else -9.0)
        e = ((pr, k), j, 1, float(fill), float(low), 'his')
        out[d].append(e + ((float(low),) if stopped else ()))
    best = []
    for lst in out:
        u = {}
        for e in sorted(lst, key=lambda x: x[0]):
            u.setdefault(e[1], e)
        best.append(list(u.values())[:n] if n else list(u.values()))
    return best


def main():
    W, cfg = SY.get('martin_luk').load()
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    reg, rules, mask, pool = W.build(A, cfg)
    rk = T4.ranks(A, pool)
    F = np.load(CACHE) if CACHE.exists() else fires(A)
    seen = set(np.load(str(CACHE) + '.seen.npy').tolist())
    score = np.load(ROOT / 'data' / 'martin-luk-cache' / 'm1_score.npy').astype(float)
    his = [x for x in base.located(A, base.trades()) if x[0].side == 'long' and x[0].dated and x[0].entry_date >= '2024-01-02']
    inu = [x for x in his if x[1] in seen]
    print('fires', len(F), 'his', len(his), 'in 5m', len(inu), flush=True)
    key = {(int(d), int(j), int(k)) for d, j, k, *_ in F}
    res = dict(trigger={})
    for name, ks in (('U', (0,)), ('P', (1,)), ('E', (2,)), ('UPE', (0, 1, 2))):
        hit = sum(any((d, j, k) in key for d in range(a, z + 1) for k in ks) for t, j, a, z in inu)
        hl = sum(any((d, j, k) in key and rk[d, j] < 100 for d in range(a, z + 1) for k in ks) for t, j, a, z in inu)
        pd_all = np.mean([len({int(r[1]) for r in F[np.isin(F[:, 2], ks) & (F[:, 0] == d)]}) for d in sorted(set(F[:, 0].astype(int)))[::10]])
        pd_list = np.mean([len({int(r[1]) for r in F[np.isin(F[:, 2], ks) & (F[:, 0] == d)] if rk[d, int(r[1])] < 100}) for d in sorted(set(F[:, 0].astype(int)))[::10]])
        res['trigger'][name] = dict(his=hit, his_list=hl, of=len(inu), per_day=float(pd_all), per_day_list=float(pd_list))
        print(name, res['trigger'][name], flush=True)
    show = lambda k, r: print(k, {y: round(v, 2) for y, v in r['by_year'].items()}, f"dd {r['maxdd']:.2f} n/y {r['per_year']:.0f} win {r['win']:.3f} aw {r['avg_win']:+.3f} al {r['avg_loss']:+.3f} dw {r['days_win']:.1f} strict {r['strict']}/{r['of']} 2026 {r['strict26']}/{r['of26']}", flush=True)
    ru0 = replace(rules, max_new_long=0, max_new_by_kind={}, max_position=.25, max_gross=2.8, intraday_kinds=('his',), trail='e9', stop_ema_buffer=.03)
    z = np.load(ROOT / 'data' / 'martin-luk-cache' / 'k5.npz', allow_pickle=True)
    first = {str(c).replace('US.', ''): j for j, c in enumerate(A['codes'])}
    j87 = {first[str(s)] for s in z['syms'] if str(s) in first}
    def go(k, e, ru=ru0, top=False):
        st, tr = base.run(A, e, panels.WINDOW, pool, ru, placebo=0, audit=True)
        r = res[k] = report(base, A, st, tr, his)
        show(k, r)
        if top:
            pnl = {}
            for t in tr:
                y = t['entry'][:4]
                pnl.setdefault((y, t['code']), 0.0)
                pnl[(y, t['code'])] += t.get('pnl', t.get('r', 0))
            for y in ('2024', '2025', '2026'):
                x = sorted(((v, c) for (yy, c), v in pnl.items() if yy == y), reverse=True)
                print(' top', y, [(c[3:], round(v, 1)) for v, c in x[:8]], 'sum', round(sum(v for v, c in x), 1), flush=True)
        RV.write('martin_m4b.json', res)
    n8 = book(A, F, (0, 1, 2), rk, 8, score)
    go('list_n8', n8, top=True)
    go('list_n4', book(A, F, (0, 1, 2), rk, 4, score))
    go('cost3', n8, replace(ru0, buy_cost=.0015, sell_cost=.0015))
    go('only87', [[x for x in l if x[1] in j87] for l in n8])
    Fr = F[~np.isin(F[:, 1].astype(int), list(j87))]
    go('onlyR8', book(A, Fr, (0, 1, 2), rk, 8, score))
    rng = np.random.default_rng(1)
    for i in range(5):
        go(f'random{i}', book(A, F, (0, 1, 2), rk, 8, rng.random(rk.shape) - .5))
    mine = np.zeros(rk.shape)
    for t, j, a, b in his:
        mine[a:b + 1, j] = 99
    go('god_his_first', book(A, F, (0, 1, 2), rk, 8, np.nan_to_num(score) + mine))


if __name__ == '__main__':
    main()
