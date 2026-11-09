"""STRONG rounds S3-S25: lists, the strong set, the layered book and its controls.  PREREG_STRONG.md

    $PY -m studies.trader_replication.martin_strong_scan s23     # the F1 candidates
    $PY -m studies.trader_replication.martin_strong_scan s25     # random-set and same-pool controls
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np

from . import review as RV, watchlist as WL
from .martin_strong import CUT, Data, bars_since, in_list, lag, library, pct, roll_ext, seg, self_pct
from .martin_words import words

L = 300
CACHE = Path('/tmp/msum/strong_extra.pkl')


def extra(D):
    """Slow character, scanner history and peers, each known at the close of its row."""
    c, h, l, o, t, adr, raw = D.c, D.h, D.l, D.o, D.t, D.adr, D.raw
    F = {}
    with np.errstate(all='ignore'):
        r = c / lag(c) - 1
        F['price'] = np.log(raw)
        F['fast250'] = WL.roll_mean((np.abs(r) >= .05).astype(np.float32), 250)
        F['fast60'] = WL.roll_mean((np.abs(r) >= .05).astype(np.float32), 60)
        gp = o / lag(c) - 1
        F['gaps60'] = WL.roll_mean((np.abs(gp) >= .03).astype(np.float32), 60)
        F['adr120'] = WL.roll_mean(h / l - 1, 120)
        act = np.log(t * (h / l - 1))
        F['act1'] = act
        F['act3'] = np.log(WL.roll_mean(t, 3) * WL.roll_mean(h / l - 1, 3))
        F['actmax5'] = roll_ext(act, 5, np.nanmax)
        F['stay20'] = WL.roll_mean((D.rk < 100).astype(np.float32), 20)
        F['stay60'] = WL.roll_mean((D.rk < 100).astype(np.float32), 60)
        F['stay250'] = WL.roll_mean((D.rk < 100).astype(np.float32), 250)
        ok = (np.nan_to_num(D.to20) >= 5e7) & (np.nan_to_num(WL.roll_mean(h / l - 1, 5)) >= .035)
        pot = np.zeros(c.shape, bool)
        led = np.zeros(c.shape, bool)
        g21 = c / lag(c, 21) - 1
        for d in range(len(c)):
            f = np.flatnonzero(ok[d] & np.isfinite(r[d]))
            if len(f) > 60:
                pot[d, f[np.argsort(-r[d, f])[:50]]] = True
            f = np.flatnonzero(ok[d] & np.isfinite(g21[d]))
            if len(f) > 120:
                led[d, f[np.argsort(-g21[d, f])[:100]]] = True
        F['pot20'] = WL.roll_mean(pot.astype(np.float32), 20)
        F['since_pot'] = bars_since(pot)
        F['led20'] = WL.roll_mean(led.astype(np.float32), 20)
        F['since_led'] = bars_since(led)
        big = gp / lag(adr) >= 2
        F['since_gap'] = bars_since(big)
        n_days = len(c)
        rr = np.nan_to_num(r - np.nanmedian(np.where(D.rk < L, r, np.nan), axis=1, keepdims=True)).astype(np.float32)
        rank_peer, heat, pot5, size, g5 = (np.full(c.shape, np.nan, dtype=np.float32) for _ in range(5))
        potroll = WL.roll_mean(pot.astype(np.float32), 5)
        g5s = c / lag(c, 5) - 1
        near, names = None, None
        for d in range(60, n_days):
            cur = np.flatnonzero(D.rk[d] < L)
            if len(cur) < 30:
                continue
            if near is None or d % 5 == 0:
                w = rr[d - 39:d + 1][:, cur]
                w = w - w.mean(0)
                sd = w.std(0) + 1e-6
                near = ((w.T @ w) / len(w) / np.outer(sd, sd)) >= .5
                names = cur
            g = g21[d, names]
            g = np.where(np.isfinite(g), g, -9)
            n = near.sum(1)
            rank_peer[d, names] = ((g[None, :] <= g[:, None]) & near).sum(1) / n
            size[d, names] = n
            heat[d, names] = (near * np.nan_to_num(g5s[d, names])).sum(1) / n
            pot5[d, names] = (near * potroll[d, names]).sum(1) / n
        F['peer_rank'], F['peer_size'], F['peer_g5'], F['peer_pot'] = rank_peer, size, heat, pot5
    return {k: v.astype(np.float32) for k, v in F.items()}


def s3():
    D = Data()
    F = library(D)
    if CACHE.exists():
        G = pickle.loads(CACHE.read_bytes())
    else:
        G = extra(D)
        G.update({'w_' + k: v.astype(np.float32) for k, v in words(D.A, D.rk).items()})
        CACHE.write_bytes(pickle.dumps(G))
    F.update(G)
    print('factors', len(F), flush=True)
    # list coverage at the close: rank by activity read that day, against the 20-day list
    p1 = lambda s: s <= CUT
    p2 = lambda s: s > CUT
    def cover(m, shift, sizes=(50, 100, 150)):
        out = []
        for n in sizes:
            hit = {}
            for tag, f in (('p1', p1), ('p2', p2)):
                k = 0
                for h in seg(D.his, f):
                    v = np.where(D.U[h[0]], m[h[0] - shift], np.nan)
                    if np.isfinite(v[h[1]]) and (v > v[h[1]]).sum() < n:
                        k += 1
                hit[tag] = k
            big = sum(1 for h in D.big if np.isfinite(np.where(D.U[h[0]], m[h[0] - shift], np.nan)[h[1]]) and (np.where(D.U[h[0]], m[h[0] - shift], np.nan) > m[h[0] - shift, h[1]]).sum() < n)
            out.append(f"{n}: {hit['p1']}/{hit['p2']} big {big}")
        return ' | '.join(out)
    print('coverage of 30 / 47, big of 25', flush=True)
    for name, m, sh in (('act20 evening', F['act20'], 1), ('act5 evening', F['act5'], 1), ('act3 evening', F['act3'], 1), ('act1 evening', F['act1'], 1), ('act20 close', F['act20'], 0), ('act5 close', F['act5'], 0), ('act3 close', F['act3'], 0), ('act1 close', F['act1'], 0), ('actmax5 close', F['actmax5'], 0)):
        print(f'  {name:14s} {cover(m, sh)}', flush=True)
    rows = {}
    keys = ('price', 'fast250', 'fast60', 'gaps60', 'adr120', 'act1', 'act3', 'actmax5', 'stay20', 'stay60', 'stay250', 'pot20', 'since_pot', 'led20', 'since_led', 'since_gap', 'peer_rank', 'peer_size', 'peer_g5', 'peer_pot') + tuple(k for k in F if k.startswith('w_'))
    for k in keys:
        x = F[k]
        rec = {}
        for tag, shift in (('c', 0), ('e', 1)):
            for p, f in (('p1', p1), ('p2', p2)):
                a, b = [], []
                for h in seg(D.his, f):
                    d, j = h[0] - shift, h[1]
                    names = np.flatnonzero(D.rk[h[0]] < L)
                    w = np.flatnonzero(names == j)
                    if len(w):
                        u = in_list(x[d], names, int(w[0]))
                        if u is not None:
                            a.append(u)
                    v = self_pct(x, d, j)
                    if v is not None:
                        b.append(v)
                rec[f'{tag}x_{p}'] = float(np.mean(a)) if a else .5
                rec[f'{tag}s_{p}'] = float(np.mean(b)) if b else .5
        rows[k] = rec
    print(f"{'factor':12s} close-list  evening-list  close-self  evening-self", flush=True)
    show = lambda r, a: f"{r[a + '_p1']:.2f}/{r[a + '_p2']:.2f}"
    for k, r in rows.items():
        print(f"{k:12s} {show(r, 'cx')}   {show(r, 'ex')}   {show(r, 'cs')}   {show(r, 'es')}", flush=True)
    RV.write('strong_s3.json', rows)


def load_all():
    D = Data()
    F = library(D)
    if CACHE.exists():
        G = pickle.loads(CACHE.read_bytes())
    else:
        G = extra(D)
        G.update({'w_' + k: v.astype(np.float32) for k, v in words(D.A, D.rk).items()})
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_bytes(pickle.dumps(G))
    F.update(G)
    return D, F


def close_list(D, F, a=100, b=100):
    """Names active today or over the last month: known at the close of the day."""
    m = np.zeros(D.c.shape, bool)
    for d in range(1, len(m)):
        for x, n in ((F['act1'][d], a), (F['act20'][d - 1], b)):
            v = np.where(D.U[d], x, np.nan)
            f = np.flatnonzero(np.isfinite(v))
            if len(f) > n:
                m[d, f[np.argsort(-v[f])[:n]]] = True
    return m


# concept -> ((factor, sign, rows back), ...): each concept is one vote
CONCEPTS = dict(today=(('act1', 1, 0),),
                char=(('stay250', 1, 1), ('fast250', 1, 1), ('adr120', 1, 1)),
                turn=(('overpdh', 1, 0), ('gain', 1, 0)),
                month=(('g21', 1, 0), ('rs_pos60', 1, 0), ('led20', 1, 0)),
                struct=(('stack', 1, 1), ('w_hl', 1, 0), ('w_wk_above', 1, 0)),
                coil=(('squeeze', -1, 1), ('range10', -1, 1), ('vc5', -1, 1)),
                theme=(('peer_pot', 1, 0), ('peer_rank', 1, 0)))


def concept(D, F, M, keys):
    s = np.zeros(D.c.shape, dtype=np.float32)
    for c in keys:
        part = np.zeros(D.c.shape, dtype=np.float32)
        for k, sign, back in CONCEPTS[c]:
            x = F[k] if back == 0 else lag(F[k], back)
            part += np.nan_to_num(pct(sign * x, M) - .5)
        s += part / len(CONCEPTS[c])
    return np.where(M, s, np.nan)


def judge(D, S, name, n=4):
    res = dict(name=name)
    parts = (('p1', lambda d: d <= CUT), ('p2', lambda d: d > CUT))
    txt = []
    for tag, rows in (('all', D.his), ('big', D.big)):
        for p, f in parts:
            R = seg(rows, f)
            P = []
            for x in R:
                v = S[x[0]]
                P.append(int((v > v[x[1]]).sum()) if np.isfinite(v[x[1]]) else None)
            res[f'{tag}_{p}'] = {str(k): sum(1 for q in P if q is not None and q < k) for k in (4, 8, 10, 20, 999)}
            r = res[f'{tag}_{p}']
            txt.append(f"{r['4']}/{r['8']}/{r['20']}/{r['999']} of {len(R)}")
    for p, f in parts:
        fp, fc, g = [], [], []
        for d in D.window:
            if not f(D.days[d]):
                continue
            v = np.nan_to_num(S[d], nan=-1e9)
            top = np.argsort(-v)[:n]
            top = top[v[top] > -1e8]
            fp += D.fp[d, top].tolist()
            fc += D.fc[d, top].tolist()
            g += D.fwd[d, top].tolist()
        g = np.array(g)
        res[p] = dict(fp=round(float(np.nanmedian(fp)) * 100), fc=round(float(np.nanmedian(fc)) * 100), big=round(float(np.nanmean(g >= .5)) * 100, 1))
    print(f"{name:9s} all {txt[0]} | {txt[1]}  big {txt[2]} | {txt[3]}  top{n} max {res['p1']['fp']}/{res['p2']['fp']} close {res['p1']['fc']}/{res['p2']['fc']} >=50% {res['p1']['big']}/{res['p2']['big']}", flush=True)
    return res


def forward_close(D):
    with np.errstate(all='ignore'):
        f = np.vstack([D.c[20:] / D.c[:-20] - 1, np.full((20, D.c.shape[1]), np.nan, dtype=np.float32)])
    D.fc = np.full(D.c.shape, np.nan, dtype=np.float32)
    for d in range(len(f)):
        ok = np.flatnonzero(np.isfinite(f[d]))
        if len(ok) > 100:
            D.fc[d, ok] = np.argsort(np.argsort(f[d, ok])) / (len(ok) - 1)


def s4():
    D, F = load_all()
    forward_close(D)
    a = np.array([(D.fp[x[0], x[1]], D.fc[x[0], x[1]]) for x in D.his])
    print('his forward max / close', np.round(np.nanmedian(a, axis=0) * 100), flush=True)
    M = close_list(D, F)
    print('list size median', int(np.median(M[D.window].sum(1))), 'covers', sum(M[x[0], x[1]] for x in D.his), 'big', sum(M[x[0], x[1]] for x in D.big), flush=True)
    res = {}
    for k, keys in dict(C0=('today',), C1=('today', 'turn'), C2=('today', 'char', 'turn'), C3=('today', 'char', 'turn', 'month', 'struct'), C4=tuple(CONCEPTS), E1=('char', 'month', 'struct', 'coil', 'theme')).items():
        res[k] = judge(D, concept(D, F, M, keys), k)
    RV.write('strong_s4.json', res)


def look():
    """Who sits above his name on his days in 2026."""
    D, F = load_all()
    M = close_list(D, F)
    S = concept(D, F, M, tuple(CONCEPTS))
    code = [str(x)[3:] for x in D.A['codes']]
    ext = F['ext21']
    for x in [h for h in D.his if h[4] > CUT][:47]:
        d, j = x[0], x[1]
        v = np.nan_to_num(S[d], nan=-1e9)
        top = np.argsort(-v)[:6]
        place = int((v > v[j]).sum())
        f = lambda q: f"{code[q]}(e{ext[d, q]:.1f},g{F['g1'][d, q] * 100:.0f},m{F['g21'][d, q] * 100:.0f})"
        print(f"{x[4]} {x[2]:5s} {x[3]:8s} #{place:3d} {f(j)} top: " + ' '.join(f(q) for q in top), flush=True)


def shape():
    """Where his names sit on each measure, by setup, against the rest of the close list."""
    D, F = load_all()
    M = close_list(D, F)
    keys = ('ext21', 'ext9', 'gain', 'overpdh', 'cpos', 'to1_20', 'lowe9', 'lowe21', 'gap', 'g21', 'pos60', 'adr')
    for st in ('pullback', 'breakout', 'ep'):
        R = [x for x in D.his if x[3] == st]
        print(st, len(R), flush=True)
        for k in keys:
            a = np.array([F[k][x[0], x[1]] for x in R])
            print(f"  {k:8s} his q25/50/75 {np.nanpercentile(a, 25):6.2f} {np.nanmedian(a):6.2f} {np.nanpercentile(a, 75):6.2f}", flush=True)
    for k in keys:
        b = F[k][D.window][M[D.window]]
        print(f"list {k:8s} q25/50/75 {np.nanpercentile(b, 25):6.2f} {np.nanmedian(b):6.2f} {np.nanpercentile(b, 75):6.2f}", flush=True)


PF = ('ext9', 'lowe9', 'gain', 'cpos', 'to1_20', 'gap', 'g21', 'pos60', 'stack', 'adr', 'act20', 'stay250')
FOLDS = (('2024-01-01', '2024-12-31'), ('2025-01-01', '2025-06-30'), ('2025-07-01', '2025-12-31'), ('2026-01-01', '2026-06-30'), ('2026-07-01', '2026-12-31'))


def binned(D, F, M, keys, nb=4):
    """Each measure as its quartile of the close list; the same edges for every day."""
    out = {}
    for k in keys:
        x = F[k]
        v = x[M]
        edges = np.unique(np.nanpercentile(v[np.isfinite(v)], np.arange(1, nb) * 100 / nb))
        b = np.searchsorted(edges, np.nan_to_num(x, nan=np.nanmedian(v)))
        out[k] = (b.astype(np.int8), len(edges) + 1)
    return out


def profile(D, F, M, keys=PF, classes=(('pullback',), ('breakout',), ('ep',)), folds=FOLDS, smooth=1.0, nb=4):
    B = binned(D, F, M, keys, nb)
    base = {k: np.bincount(b[M], minlength=n) / M.sum() for k, (b, n) in B.items()}
    S = np.full(D.c.shape, np.nan, dtype=np.float32)
    pos = [x for x in D.his if M[x[0], x[1]]]
    for a, z in folds:
        tr = [x for x in pos if not a <= x[4] <= z]
        ds = [d for d, x in enumerate(D.days) if a <= x <= z]
        best = None
        for cl in classes:
            R = [x for x in tr if x[3] in cl]
            total = np.zeros(D.c[ds].shape, dtype=np.float32)
            for k, (b, n) in B.items():
                cnt = np.bincount([b[x[0], x[1]] for x in R], minlength=n).astype(float) + smooth * base[k] * n
                lr = np.log(cnt / cnt.sum() / np.maximum(base[k], 1e-6))
                total += lr[b[ds]].astype(np.float32)
            total += np.log(max(len(R), 1) / max(len(tr), 1))
            best = total if best is None else np.maximum(best, total)
        S[ds] = best
    return np.where(M, S, np.nan)


def s5():
    D, F = load_all()
    forward_close(D)
    M = close_list(D, F)
    res = {}
    res['P3'] = judge(D, profile(D, F, M), 'P3')
    res['P2'] = judge(D, profile(D, F, M, classes=(('pullback', 'breakout'), ('ep',))), 'P2')
    res['P1'] = judge(D, profile(D, F, M, classes=(('pullback', 'breakout', 'ep'),)), 'P1')
    res['P3s3'] = judge(D, profile(D, F, M, smooth=3.0), 'P3s3')
    res['P3b3'] = judge(D, profile(D, F, M, nb=3), 'P3b3')
    RV.write('strong_s5.json', res)


HOLD = dict(H0=(('act20',),),
            H1=(('act20',), ('g21',)),
            H2=(('act20',), ('g21',), ('stay250', 'fast250'), ('stack', 'w_wk_above')),
            H3=(('act20',), ('g21', 'led20', 'rs_pos60'), ('stay250', 'fast250'), ('stack', 'w_wk_above'), ('peer_pot', 'peer_rank')),
            H4=(('act20',), ('g21', 'led20', 'rs_pos60'), ('stay250', 'fast250'), ('stack', 'w_wk_above'), ('peer_pot', 'peer_rank'), ('nsq', 'nr10')))


def active(D, F, n=300):
    """Top n of the 20-day activity, read the evening before."""
    m = np.zeros(D.c.shape, bool)
    for d in range(1, len(m)):
        v = np.where(D.U[d], F['act20'][d - 1], np.nan)
        f = np.flatnonzero(np.isfinite(v))
        if len(f) > n:
            m[d, f[np.argsort(-v[f])[:n]]] = True
    return m


def name_score(D, F, M, groups):
    """Evening score: read from the row before, ranked among the active names, one vote per group."""
    s = np.zeros(D.c.shape, dtype=np.float32)
    for g in groups:
        part = np.zeros(D.c.shape, dtype=np.float32)
        for k in g:
            part += np.nan_to_num(pct(lag(F[k]), M) - .5)
        s += part / len(g)
    return np.where(M, s, np.nan)


def hold_sim(S, K, out):
    """Enter on a rank within K, leave on a rank beyond out or when the name leaves the universe."""
    H = np.zeros(S.shape, bool)
    cur = np.zeros(S.shape[1], bool)
    for d in range(len(S)):
        v = np.nan_to_num(S[d], nan=-1e9)
        o = np.argsort(-v)
        rk = np.empty(len(v), int)
        rk[o] = np.arange(len(v))
        cur = (cur & (rk < out) & (v > -1e8)) | ((rk < K) & (v > -1e8))
        H[d] = cur
    return H


def overlap(D, H, name):
    p1 = [x for x in D.his if x[4] <= CUT]
    p2 = [x for x in D.his if x[4] > CUT]
    on = lambda R: sum(H[x[0], x[1]] for x in R)
    board, share = 0, []
    for x in D.big:
        d, j = x[0], x[1]
        seg_ = D.h[d + 1:d + 21, j]
        peak = d + 1 + int(np.nanargmax(seg_))
        run = H[d:peak + 1, j]
        board += bool(run.any())
        share.append(float(run.mean()))
    new = H & ~lag(H.astype(np.float32)).astype(bool)
    new[0] = False
    w = np.zeros(len(H), bool)
    w[D.window] = True
    fp, fc, g = D.fp[w][new[w]], D.fc[w][new[w]], D.fwd[w][new[w]]
    size = float(H[D.window].sum(1).mean())
    print(f"{name:10s} size {size:5.1f} new/yr {new[w].sum() / (w.sum() / 252):5.0f} on-date {on(p1)}/30 {on(p2)}/47 board {board}/25 run {np.mean(share):.0%} new max {np.nanmedian(fp) * 100:.0f} close {np.nanmedian(fc) * 100:.0f} >=50% {np.nanmean(g >= .5) * 100:.1f}", flush=True)
    return dict(size=size, on1=int(on(p1)), on2=int(on(p2)), board=board, run=float(np.mean(share)))


def s6():
    D, F = load_all()
    forward_close(D)
    with np.errstate(all='ignore'):
        F['nsq'], F['nr10'] = -F['squeeze'], -F['range10']
    M = active(D, F)
    print('active 300 covers', sum(M[x[0], x[1]] for x in D.his), flush=True)
    res = {}
    for k, groups in HOLD.items():
        S = name_score(D, F, M, groups)
        for K in (8, 12, 20):
            res[f'{k}_{K}'] = overlap(D, hold_sim(S, K, 3 * K), f'{k}_{K}')
    RV.write('strong_s6.json', res)


def pool_book(D, F, H, S, trigger=True, max_ext=3.0):
    """Close entries inside the strong set: a touch of the 9 EMA held, or a close over yesterday's high in the upper half of the day."""
    c, l, h = D.c, D.l, D.h
    tr = (F['lowe9'] <= .1) & (c > D.e9) | (c > lag(h)) & (F['cpos'] >= .5)
    ok = np.nan_to_num(F['ext21'], nan=99) <= max_ext
    out = [[] for _ in range(len(c))]
    for d in range(1, len(c)):
        m = H[d] & ok[d] & (tr[d] if trigger else True) & np.isfinite(c[d]) & np.isfinite(l[d])
        for j in np.flatnonzero(m):
            cc = float(c[d, j])
            out[d].append(((1.0, -float(np.nan_to_num(S[d, j]))), int(j), 1, cc, float(min(max(float(l[d, j]), cc * .95), cc * .99)), 'list'))
    return out


def stage(D, H):
    """His entries whose name we held at some point from 5 days before to 10 days after his buy."""
    f = lambda R: int(sum(H[max(x[0] - 5, 0):x[0] + 11, x[1]].any() for x in R))
    return f([x for x in D.his if x[4] <= CUT]), f([x for x in D.his if x[4] > CUT])


def account(D, entries, ru, name, placebo=0):
    from . import panels
    from .martin_m1 import report
    his = [x for x in D.base.located(D.A, D.base.trades()) if x[0].side == 'long' and x[0].dated and x[0].entry_date >= '2024-01-02']
    st, tr = D.base.run(D.A, entries, panels.WINDOW, D.pool, ru, placebo=placebo, audit=True)
    r = report(D.base, D.A, st, tr, his)
    idx = {str(x): i for i, x in enumerate(D.A['codes'])}
    H = np.zeros(D.c.shape, bool)
    new = []
    for t in tr:
        if t['side'] > 0 and t['entry'] in D.di and t['exit'] in D.di:
            a, b = D.di[t['entry']], D.di[t['exit']]
            H[a:b + 1, idx[str(t['code'])]] = True
            new.append((a, idx[str(t['code'])]))
    board, share = 0, []
    for x in D.big:
        d, j = x[0], x[1]
        peak = d + 1 + int(np.nanargmax(D.h[d + 1:d + 21, j]))
        run = H[d:peak + 1, j]
        board += bool(run.any())
        share.append(float(run.mean()))
    stage1, stage2 = stage(D, H)
    held1 = sum(H[x[0], x[1]] for x in D.his if x[4] <= CUT)
    held2 = sum(H[x[0], x[1]] for x in D.his if x[4] > CUT)
    a = np.array([(D.fp[d, j], D.fc[d, j], D.fwd[d, j]) for d, j in new if d + 20 < len(D.c)])
    pnl = {}
    for t in tr:
        if t['side'] > 0:
            pnl[t['code']] = pnl.get(t['code'], 0) + t['pnl']
    gross = sum(v for v in pnl.values() if v > 0) or 1
    top = sorted(pnl.items(), key=lambda kv: -kv[1])[:5]
    mine = {str(D.A['codes'][x[1]]) for x in D.his}
    bigp, seen = 0.0, set()
    lon = [t for t in tr if t['side'] > 0 and t['entry'] in D.di and t['exit'] in D.di]
    for x in D.big:
        d, j = x[0], x[1]
        peak = d + 1 + int(np.nanargmax(D.h[d + 1:d + 21, j]))
        for k, t in enumerate(lon):
            if k not in seen and idx[str(t['code'])] == j and D.di[t['entry']] <= peak and D.di[t['exit']] >= d:
                bigp += t['pnl']
                seen.add(k)
    r.update(big_profit=bigp / gross, stage1=stage1, stage2=stage2, board=board, run=float(np.mean(share)), held1=int(held1), held2=int(held2), size=float(H[D.window].sum(1).mean()), max_rank=float(np.nanmedian(a[:, 0]) * 100), close_rank=float(np.nanmedian(a[:, 1]) * 100), big=float(np.nanmean(a[:, 2] >= .5) * 100),
             his_profit=sum(v for k, v in pnl.items() if k in mine and v > 0) / gross, top=[(k[3:], round(v / gross, 2)) for k, v in top])
    y = r['by_year']
    print(f"{name:10s} {y['2024']:+.2f}/{y['2025']:+.2f}/{y['2026']:+.2f} dd {r['maxdd']:.2f} n/y {r['per_year']:.0f} win {r['win']:.3f} aw {r['avg_win']:+.3f} al {r['avg_loss']:+.3f} dw {r['days_win']:.1f} strict {r['strict']}/{r['of']} {r['strict26']}/{r['of26']} held {held1}/30 {held2}/47 stage {stage1}/30 {stage2}/47 board {board}/25 run {np.mean(share):.0%} size {r['size']:.1f} newmax {r['max_rank']:.0f} newclose {r['close_rank']:.0f} >=50 {r['big']:.1f} hisprofit {r['his_profit']:.0%} bigprofit {r['big_profit']:.0%} top {r['top']} {r.get('placebo') or ''}", flush=True)
    return r


def setup7():
    from dataclasses import replace
    D, F = load_all()
    forward_close(D)
    with np.errstate(all='ignore'):
        F['nsq'], F['nr10'] = -F['squeeze'], -F['range10']
    from .martin_list import ema
    D.e9 = ema(D.c.astype(float), 9).astype(np.float32)
    M = active(D, F)
    shorts = [[((0.0,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:]) for e in lst if e[2] <= 0] for lst in D.reg]
    return D, F, M, shorts, replace


def s7():
    D, F, M, shorts, replace = setup7()
    res = dict(REG=account(D, D.reg, D.rules, 'REG'))
    for k, (grp, K, trig) in dict(X1=('H2', 8, True), X2=('H3', 12, True), X3=('H3', 20, True), X4=('H1', 8, True), X5=('H2', 8, False)).items():
        S = name_score(D, F, M, HOLD[grp])
        H = hold_sim(S, K, 3 * K)
        e = [a + b for a, b in zip(pool_book(D, F, H, S, trig), shorts)]
        ru = replace(D.rules, max_new_long=4, max_new_by_kind={})
        res[k] = account(D, e, ru, k)
        RV.write('strong_s7.json', res)


def pool_book2(D, F, H, S, trigger=True, max_ext=3.0, gate=None, cap=True):
    """As pool_book, with his stop: the day's low, at most half the ADR and 5%, at least 1%."""
    c, l, h = D.c, D.l, D.h
    tr = (F['lowe9'] <= .1) & (c > D.e9) | (c > lag(h)) & (F['cpos'] >= .5)
    ok = np.nan_to_num(F['ext21'], nan=99) <= max_ext
    out = [[] for _ in range(len(c))]
    for d in range(1, len(c)):
        if gate is not None and not gate[d - 1]:
            continue
        m = H[d] & ok[d] & (tr[d] if trigger else True) & np.isfinite(c[d]) & np.isfinite(l[d])
        for j in np.flatnonzero(m):
            cc = float(c[d, j])
            a = D.adr[d - 1, j]
            w = min(.05, float(a) / 2) if cap and np.isfinite(a) else .05
            stop = min(max(float(l[d, j]), cc * (1 - w)), cc * .99)
            out[d].append(((1.0, -float(np.nan_to_num(S[d, j]))), int(j), 1, cc, float(stop), 'list'))
    return out


def breadth_scale(D, F, floor=.25):
    from .martin_list import ema
    e21 = ema(D.c.astype(float), 21).astype(np.float32)
    top = np.zeros(D.c.shape, bool)
    for d in range(len(D.c)):
        v = np.where(D.U[d], F['act20'][max(d - 1, 0)], np.nan)
        f = np.flatnonzero(np.isfinite(v))
        if len(f) > 100:
            top[d, f[np.argsort(-v[f])[:100]]] = True
    br = (top & (D.c > e21)).sum(1) / np.maximum(top.sum(1), 1)
    br = np.concatenate([[.5], br[:-1]])                     # known at the previous close
    return np.clip(br / .5, floor, 1.0).astype(np.float32), br


def s8():
    D, F, M, shorts, replace = setup7()
    gate = D.base.market_gate(D.A, D.cfg)
    S = name_score(D, F, M, HOLD['H2'])
    H = hold_sim(S, 8, 24)
    scale, br = breadth_scale(D, F)
    print('breadth q10/50/90', np.round(np.nanpercentile(br[D.window], [10, 50, 90]), 2), flush=True)
    idx = D.base.R.index_risk_scale(D.A, D.pool, pb=1.6)
    D.A['br_scale'] = (np.asarray(idx, dtype=np.float64) * scale).astype(np.float64)
    weak = ~H
    D.A['weak_exit'] = weak
    ru = replace(D.rules, max_new_long=4, max_new_by_kind={})
    res = {}
    for k, (g, cap, rs, ex) in dict(Y1=(True, False, False, False), Y2=(False, True, False, False), Y3=(True, True, False, False), Y4=(False, True, True, False), Y5=(False, True, True, True)).items():
        e = [a + b for a, b in zip(pool_book2(D, F, H, S, True, 3.0, gate if g else None, cap), shorts)]
        r2 = ru
        if rs:
            r2 = replace(r2, risk_scale='br_scale')
        if ex:
            r2 = replace(r2, exit_signal='weak_exit')
        res[k] = account(D, e, r2, k)
        RV.write('strong_s8.json', res)


def diag(tr, D, name):
    import collections
    q = collections.defaultdict(lambda: [0, 0, 0.0, 0.0, 0.0, 0.0])
    for t in tr:
        y = t['entry'][:4] + 'Q' + str((int(t['entry'][5:7]) - 1) // 3 + 1)
        k = (y, 'L' if t['side'] > 0 else 'S')
        r = q[k]
        r[0] += 1
        r[1] += t['pnl'] > 0
        r[2] += t['pnl']
        r[3] += float(t.get('r') or 0)
        r[4] += float(t.get('risk_pct') or 0)
        r[5] += t['days']
    print(name, flush=True)
    for k in sorted(q):
        r = q[k]
        print(f"  {k[0]} {k[1]} n {r[0]:3d} win {r[1] / r[0]:.2f} pnl {r[2]:+9.0f} avgR {r[3] / r[0]:+.2f} stop {r[4] / r[0] * 100:.1f}% days {r[5] / r[0]:.1f}", flush=True)


def s9():
    from . import panels
    D, F, M, shorts, replace = setup7()
    S = name_score(D, F, M, HOLD['H2'])
    H = hold_sim(S, 8, 24)
    st, tr = D.base.run(D.A, D.reg, panels.WINDOW, D.pool, D.rules, placebo=0, audit=True)
    diag(tr, D, 'REG')
    ru = replace(D.rules, max_new_long=4, max_new_by_kind={})
    e = [a + b for a, b in zip(pool_book2(D, F, H, S), shorts)]
    st, tr = D.base.run(D.A, e, panels.WINDOW, D.pool, ru, placebo=0, audit=True)
    diag(tr, D, 'Y2')
    print('rules', D.rules.trims, D.rules.trim_frac, D.rules.trail, D.rules.trail_after_trim, D.rules.risk, D.rules.risk_low, D.rules.risk_high, D.rules.feedback, D.rules.max_position, D.rules.max_gross, D.rules.max_new_by_kind, D.rules.add_levels, flush=True)
    import collections
    why = collections.Counter(); wr = collections.defaultdict(float)
    for t in tr:
        if t['side'] > 0:
            why[t['why']] += 1
            wr[t['why']] += float(t.get('r') or 0)
    print({k: (v, round(wr[k] / v, 2)) for k, v in why.items()}, flush=True)


def pdh_book(D, F, H, S, path='p', max_ext=3.0, wmax=.03):
    """A buy stop at yesterday's high for the names of the strong set, placed the evening before."""
    o, h, l, c = D.o, D.h, D.l, D.c
    ext = np.nan_to_num(F['ext21'], nan=99)
    out = [[] for _ in range(len(c))]
    for d in range(2, len(c)):
        m = H[d] & (ext[d - 1] <= max_ext) & np.isfinite(h[d]) & np.isfinite(h[d - 1]) & (h[d] >= h[d - 1])
        for j in np.flatnonzero(m):
            L = float(h[d - 1, j])
            op = float(o[d, j])
            fill = max(op, L)
            a = D.adr[d - 1, j]
            w = max(.01, min(wmax, float(a) / 2 if np.isfinite(a) else wmax))
            stop = fill * (1 - w)
            e = ((1.0, -float(np.nan_to_num(S[d, j]))), int(j), 1, fill, float(stop), 'list')
            hit = float(l[d, j]) <= stop
            if hit and path == 'a' and op < fill and float(c[d, j]) >= fill:
                hit = False
            out[d].append(e + ((float(stop),) if hit else ()))
    return out


def s10():
    D, F, M, shorts, replace = setup7()
    res = {}
    base = replace(D.rules, max_new_long=4, max_new_by_kind={}, intraday_kinds=tuple(D.rules.intraday_kinds) + ('list',))
    fb = replace(base, risk_low=.0025)
    for k, (grp, K, path, ru) in dict(Z1p=('H2', 8, 'p', base), Z1a=('H2', 8, 'a', base), Z2p=('H2', 8, 'p', fb), Z2a=('H2', 8, 'a', fb), Z3a=('H3', 12, 'a', fb)).items():
        S = name_score(D, F, M, HOLD[grp])
        H = hold_sim(S, K, 3 * K)
        e = [a + b for a, b in zip(pdh_book(D, F, H, S, path), shorts)]
        res[k] = account(D, e, ru, k)
        RV.write('strong_s10.json', res)


def resort(entries, S, H, n, ep_first=True):
    """The system's own signals, cut to n a day by the strength score; an empty H keeps every name."""
    out = []
    for d, lst in enumerate(entries):
        lon = [e for e in lst if e[2] > 0 and (H is None or H[d, e[1]])]
        key = lambda e: (0 if ep_first and str(e[5]).lower().startswith('ep') else 1, -float(np.nan_to_num(S[d, e[1]], nan=-99)))
        top = sorted(lon, key=key)[:n]
        out.append([((1.0,) + key(e),) + tuple(e[1:]) for e in top] + [((0.0,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:]) for e in lst if e[2] <= 0])
    return out


def s11():
    D, F, M, shorts, replace = setup7()
    wide, rules, *_ = D.W.build(D.A, {**D.cfg, 'max_new': 0})
    free, rules2, *_ = D.W.build(D.A, {**D.cfg, 'max_new': 0, 'filter': 'NONE'})
    print('signals a day', int(np.median([sum(e[2] > 0 for e in x) for x in wide])), int(np.median([sum(e[2] > 0 for e in x) for x in free])), {str(e[5]) for x in wide[300:320] for e in x}, flush=True)
    nocap = replace(D.rules, max_new_long=0, max_new_by_kind={})
    res = {}
    sets = {}
    for grp, K in (('H2', 8), ('H3', 20)):
        S = name_score(D, F, M, HOLD[grp])
        sets[grp] = (S, hold_sim(S, K, 3 * K))
    plan = dict(W1=(wide, 'H2', True), W2=(wide, 'H3', True), W3=(wide, 'H2', False), W4=(free, 'H2', True), W5=(free, 'H3', True))
    for k, (ent, grp, use) in plan.items():
        S, H = sets[grp]
        res[k] = account(D, resort(ent, S, H if use else None, 4), nocap, k)
        RV.write('strong_s11.json', res)


def book_curve(D, H, cost=.0005, gross=1.0):
    """Equal weight on the held names, traded at the open of the day membership changes."""
    o, c = D.o.astype(float), D.c.astype(float)
    n = len(c)
    eq = np.ones(n)
    for d in range(1, n):
        y, t = H[d - 1], H[d]
        stay, new, gone = y & t, t & ~y, y & ~t
        k = t.sum()
        if k == 0:
            r = 0.0
            if gone.any():
                r = float(np.nanmean(o[d, gone] / c[d - 1, gone] - 1)) - cost
        else:
            a = np.nan_to_num(c[d, stay] / c[d - 1, stay] - 1).sum() if stay.any() else 0.0
            b = np.nan_to_num(c[d, new] / o[d, new] - 1 - cost).sum() if new.any() else 0.0
            g = np.nan_to_num(o[d, gone] / c[d - 1, gone] - 1 - cost).sum() if gone.any() else 0.0
            r = float((a + b + g) / max(k + gone.sum(), 1)) * gross
        eq[d] = eq[d - 1] * (1 + r)
    return eq


def years(D, eq):
    out = {}
    for y in ('2024', '2025', '2026'):
        ix = [i for i, x in enumerate(D.days) if x[:4] == y]
        out[y] = float(eq[ix[-1]] / eq[max(ix[0] - 1, 0)] - 1)
    w = eq[D.di['2024-01-02']:]
    out['dd'] = float((1 - w / np.maximum.accumulate(w)).max())
    return out


def s12():
    D, F, M, shorts, replace = setup7()
    from .martin_strong import bench
    qq = bench(D.days, 'QQQ')
    print('QQQ', {k: round(v, 2) for k, v in years(D, qq / qq[0]).items()}, flush=True)
    res = {}
    rng = np.random.default_rng(1)
    for grp in ('H1', 'H2', 'H3'):
        S = name_score(D, F, M, HOLD[grp])
        for K in (8, 12, 20):
            H = hold_sim(S, K, 3 * K)
            y = years(D, book_curve(D, H))
            pl = []
            for i in range(20):
                R = np.where(M, rng.random(M.shape, dtype=np.float32), np.nan)
                # the same number of names and about the same turnover: a random score that keeps its order for a while
                keep = np.where(M, np.nan_to_num(S) * 0 + R, np.nan)
                for d in range(1, len(keep)):
                    keep[d] = .97 * np.nan_to_num(keep[d - 1], nan=.5) + .03 * np.nan_to_num(keep[d], nan=.5)
                keep = np.where(M, keep, np.nan)
                pl.append(years(D, book_curve(D, hold_sim(keep, K, 3 * K))))
            med = {k: float(np.median([p[k] for p in pl])) for k in y}
            rank = float(np.mean([min(y['2024'] - p['2024'], y['2025'] - p['2025']) > 0 for p in pl]))
            print(f"{grp}_{K:<3d} {y['2024']:+.2f}/{y['2025']:+.2f}/{y['2026']:+.2f} dd {y['dd']:.2f} size {H[D.window].sum(1).mean():.1f} | random {med['2024']:+.2f}/{med['2025']:+.2f}/{med['2026']:+.2f} dd {med['dd']:.2f} beat {rank:.2f}", flush=True)
            res[f'{grp}_{K}'] = dict(y=y, placebo=med, beat=rank)
    RV.write('strong_s12.json', res)


def rank_row(x):
    o = np.argsort(np.argsort(x))
    return o / (len(x) - 1)


def s13():
    D, F, M, shorts, replace = setup7()
    with np.errstate(all='ignore'):
        fc = np.vstack([D.c[20:] / D.c[:-20] - 1, np.full((20, D.c.shape[1]), np.nan, dtype=np.float32)])
        fa = fc / D.adr
    his_c = {y: [] for y in ('p1', 'p2')}
    for x in D.his:
        his_c['p1' if x[4] <= CUT else 'p2'].append((D.fc[x[0], x[1]], D.fp[x[0], x[1]]))
    for k, v in his_c.items():
        a = np.array(v)
        print('his', k, 'close rank', round(float(np.nanmedian(a[:, 0])) * 100), 'max rank', round(float(np.nanmedian(a[:, 1])) * 100), flush=True)
    rows = []
    ys = ('2024', '2025', '2026')
    for k, x in F.items():
        rec = {}
        for y in ys:
            ic, ica = [], []
            for d in D.window[::2]:
                if D.days[d][:4] != y:
                    continue
                n = np.flatnonzero(M[d] & np.isfinite(x[d]) & np.isfinite(fc[d]))
                if len(n) < 50 or np.ptp(x[d, n]) == 0:
                    continue
                a = rank_row(x[d, n])
                ic.append(float(np.corrcoef(a, rank_row(fc[d, n]))[0, 1]))
                ica.append(float(np.corrcoef(a, rank_row(fa[d, n]))[0, 1]))
            rec[y], rec[y + 'a'] = float(np.nanmean(ic)), float(np.nanmean(ica))
        rows.append((k, rec))
    key = lambda r: min(abs(r[y]) for y in ys) if len({np.sign(r[y]) for y in ys}) == 1 else 0
    print('factor        IC 2024  2025  2026 | per ADR 2024 2025 2026', flush=True)
    for k, r in sorted(rows, key=lambda kv: -key(kv[1]))[:22]:
        print(f"{k:12s} {r['2024']:+.3f} {r['2025']:+.3f} {r['2026']:+.3f} | {r['2024a']:+.3f} {r['2025a']:+.3f} {r['2026a']:+.3f}", flush=True)
    RV.write('strong_s13.json', dict(rows))


def sized(book, mult, intraday=False):
    """(priority, j, side, fill, stop, kind, day_exit, size_risk, max_position, risk_mult)"""
    out = []
    for lst in book:
        row = []
        for e in lst:
            day_exit = e[6] if len(e) > 6 else None
            row.append(((2.0,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:6]) + (day_exit, None, None, mult))
        out.append(row)
    return out


def layered(D, sat, adds, n=4, intraday=False):
    from dataclasses import replace
    mg = {'list': dict(add_levels=adds)} if adds else {}
    kinds = tuple(D.rules.intraday_kinds) + (('list',) if intraday else ())
    return replace(D.rules, management_by_kind={**D.rules.management_by_kind, **mg}, max_new_by_kind={**D.rules.max_new_by_kind, 'list': n}, intraday_kinds=kinds)


def merge(reg, sat):
    return [list(a) + list(b) for a, b in zip(reg, sat)]


def s14():
    D, F, M, shorts, replace = setup7()
    res = {}
    plan = dict(V1=('H2', 8, 'c', .5, ()), V2=('H2', 8, 'c', .5, (3, 6)), V3=('H2', 8, 'a', .5, (3, 6)), V4=('H3', 12, 'c', .5, (3, 6)), V5=('H2', 8, 'c', .25, (3, 6)))
    for k, (grp, K, how, mult, adds) in plan.items():
        S = name_score(D, F, M, HOLD[grp])
        H = hold_sim(S, K, 3 * K)
        b = pool_book2(D, F, H, S) if how == 'c' else pdh_book(D, F, H, S, 'a')
        e = merge(D.reg, sized(b, mult))
        res[k] = account(D, e, layered(D, None, adds, intraday=how != 'c'), k)
        RV.write('strong_s14.json', res)


def s15():
    """Where each of the 25 big entries stops in V4."""
    from . import panels
    D, F, M, shorts, replace = setup7()
    S = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(S, 12, 36)
    b = pool_book2(D, F, H, S)
    e = merge(D.reg, sized(b, .5))
    ru = layered(D, None, (3, 6))
    st, tr = D.base.run(D.A, e, panels.WINDOW, D.pool, ru, placebo=0, audit=True)
    idx = {str(x): i for i, x in enumerate(D.A['codes'])}
    T = np.zeros(D.c.shape, bool)
    for t in tr:
        if t['side'] > 0 and t['entry'] in D.di and t['exit'] in D.di:
            T[D.di[t['entry']]:D.di[t['exit']] + 1, idx[str(t['code'])]] = True
    avail = [{x[1] for x in row} for row in b]
    gross = [0] * len(D.c)
    print('tk day setup rank_active inH sig_days held_share', flush=True)
    for x in sorted(D.big, key=lambda r: r[4]):
        d, j = x[0], x[1]
        peak = d + 1 + int(np.nanargmax(D.h[d + 1:d + 21, j]))
        run = range(d - 5, peak + 1)
        inh = sum(H[k, j] for k in run)
        sig = sum(j in avail[k] for k in run)
        rank = None
        v = np.nan_to_num(S[d], nan=-1e9)
        if np.isfinite(S[d, j]):
            rank = int((v > v[j]).sum())
        print(f"{x[2]:5s} {x[4]} {x[3]:8s} act {int(np.sum(np.nan_to_num(np.where(D.U[d], F['act20'][d - 1], np.nan), nan=-99) > F['act20'][d - 1, j])):4d} srank {rank} inH {inh}/{len(run)} sig {sig} held {T[d:peak + 1, j].mean():.0%} ext {F['ext21'][d, j]:.1f} gain {D.fwd[d, j]:.0%}", flush=True)


def gap_book(D, F, S, top=10):
    """Today's largest opening gaps that held: bought at the close, no strong-set or extension test."""
    c, l, o = D.c, D.l, D.o
    with np.errstate(all='ignore'):
        gp = o / lag(c) - 1
    out = [[] for _ in range(len(c))]
    for d in range(2, len(c)):
        v = np.where(D.U[d], gp[d], np.nan)
        f = np.flatnonzero(np.isfinite(v))
        if len(f) < 50:
            continue
        for j in f[np.argsort(-v[f])[:top]]:
            a = D.adr[d - 1, j]
            if not (np.isfinite(a) and gp[d, j] >= a and F['cpos'][d, j] >= .5 and np.isfinite(l[d, j])):
                continue
            cc = float(c[d, j])
            w = min(.05, float(a) / 2)
            stop = min(max(float(l[d, j]), cc * (1 - w)), cc * .99)
            out[d].append(((1.0, -10.0 - float(gp[d, j])), int(j), 1, cc, float(stop), 'list'))
    return out


def s16():
    D, F, M, shorts, replace = setup7()
    gaps = gap_book(D, F, None)
    print('gap entries a year', sum(len(x) for x in gaps) / (len(D.days) / 252), flush=True)
    res = {}
    def run(k, grp, K, n, heat=False, rotate=0.0):
        S = name_score(D, F, M, HOLD[grp])
        H = hold_sim(S, K, 3 * K)
        Sb = S
        if heat:
            Sb = S + np.nan_to_num(pct(F['peer_pot'], M) - .5) * 2
        b = pool_book2(D, F, H, Sb)
        both = [a + g for a, g in zip(b, gaps)]
        ru = layered(D, None, (3, 6), n=n)
        if rotate:
            ru = replace(ru, rotate_below=rotate, rotate_min_days=3)
        res[k] = account(D, merge(D.reg, sized(both, .5)), ru, k)
        RV.write('strong_s16.json', res)
    run('U1', 'H3', 12, 4)
    run('U2', 'H3', 12, 6)
    run('U3', 'H3', 12, 6, heat=True)
    run('U4', 'H3', 12, 6, rotate=.02)
    run('U5', 'H3', 20, 6)


def gap_strict(D, F):
    c, l, o = D.c, D.l, D.o
    with np.errstate(all='ignore'):
        gp = o / lag(c) - 1
    act = np.where(D.U, F['act1'], np.nan)
    out = [[] for _ in range(len(c))]
    n = 0
    for d in range(2, len(c)):
        v = act[d]
        f = np.flatnonzero(np.isfinite(v))
        if len(f) < 60:
            continue
        for j in f[np.argsort(-v[f])[:50]]:
            a = D.adr[d - 1, j]
            if not (np.isfinite(a) and gp[d, j] >= a and F['cpos'][d, j] >= .5 and F['to1_20'][d, j] >= 2 and F['pos60'][d, j] >= .7):
                continue
            cc = float(c[d, j])
            w = min(.05, float(a) / 2)
            stop = min(max(float(l[d, j]), cc * (1 - w)), cc * .99)
            out[d].append(((1.5, -float(v[j])), int(j), 1, cc, float(stop), 'gap'))
            n += 1
    return out, n


def s17():
    D, F, M, shorts, replace = setup7()
    gaps, n = gap_strict(D, F)
    seen = {(x[0], x[1]) for x in D.his}
    ep = [x for x in D.his if x[3] == 'ep']
    print('strict gap entries a year', round(n / (len(D.days) / 252)), 'his ep caught', sum(any(e[1] == x[1] for e in gaps[x[0]]) for x in ep), 'of', len(ep), 'big caught', sum(any(e[1] == x[1] for e in gaps[x[0]]) for x in D.big), flush=True)
    res = {}
    S = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(S, 12, 36)
    b0 = pool_book2(D, F, H, S)
    bh = pool_book2(D, F, H, S + np.nan_to_num(pct(F['peer_pot'], M) - .5) * 2)
    def run(k, book, n=4, ng=0, rotate=0.0):
        ru = layered(D, None, (3, 6), n=n)
        mg = dict(ru.management_by_kind)
        mk = dict(ru.max_new_by_kind)
        if ng:
            mg['gap'] = dict(add_levels=(3, 6))
            mk['gap'] = ng
        ru = replace(ru, management_by_kind=mg, max_new_by_kind=mk)
        if rotate:
            ru = replace(ru, rotate_below=rotate, rotate_min_days=3)
        res[k] = account(D, merge(D.reg, sized(book, .5)), ru, k)
        RV.write('strong_s17.json', res)
    both = [a + g for a, g in zip(b0, gaps)]
    run('U6', both, 4, 1)
    run('U7', both, 4, 2)
    run('U8', b0, 6)
    run('U9', bh, 4)
    run('U10', b0, 4, 0, .02)


def s18():
    D, F, M, shorts, replace = setup7()
    S = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(S, 12, 36)
    e = merge(D.reg, sized(pool_book2(D, F, H, S), .5))
    res = {}
    plan = dict(D1=(4, 5.0, None), D2=(12, 5.0, None), D3=(4, None, .30), D4=(4, None, .35), D5=(6, None, .35))
    for k, (n, gross, pos) in plan.items():
        ru = layered(D, None, (3, 6), n=n)
        if gross:
            ru = replace(ru, max_gross=gross)
        if pos:
            ru = replace(ru, max_position=pos)
        res[k] = account(D, e, ru, k)
        RV.write('strong_s18.json', res)


HOLD.update(H5=(('act20',), ('money',), ('pos250',), ('g21', 'led20', 'rs_pos60'), ('stay250', 'fast250'), ('stack', 'w_wk_above')),
            H6=(('act20',), ('money',), ('pos250',), ('stay250', 'fast250'), ('stack', 'w_wk_above')),
            H7=(('act20',), ('money',), ('pos250',), ('g21', 'led20', 'rs_pos60'), ('stay250', 'fast250'), ('stack', 'w_wk_above'), ('peer_pot', 'peer_rank')))


def d5_rules(D, n=6, adds=(3, 6), extra=None):
    from dataclasses import replace
    ru = layered(D, None, adds, n=n)
    ru = replace(ru, max_position=.35)
    if extra:
        mg = dict(ru.management_by_kind)
        mg['list'] = {**mg.get('list', {}), **extra}
        ru = replace(ru, management_by_kind=mg)
    return ru


def s19():
    D, F, M, shorts, replace = setup7()
    res = {}
    for k, (grp, K) in dict(P1=('H5', 12), P2=('H6', 12), P3=('H7', 12), P4=('H5', 20), P5=('H7', 20)).items():
        S = name_score(D, F, M, HOLD[grp])
        H = hold_sim(S, K, 3 * K)
        overlap(D, H, 'set ' + k)
        res[k] = account(D, merge(D.reg, sized(pool_book2(D, F, H, S), .5)), d5_rules(D), k)
        RV.write('strong_s19.json', res)


def s20():
    D, F, M, shorts, replace = setup7()
    S = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(S, 12, 36)
    e = merge(D.reg, sized(pool_book2(D, F, H, S), .5))
    res = {}
    t915 = dict(trims=(3, 5), trim_frac=.15)
    plan = dict(M1=(6, (3, 6), dict(trail='e9')), M2=(6, (3, 6), t915), M3=(6, (3, 6), dict(trail='e9', **t915)), M4=(6, (), dict(trail='e9', **t915)), M5=(8, (3, 6), dict(trail='e9', **t915)))
    for k, (n, adds, ex) in plan.items():
        res[k] = account(D, e, d5_rules(D, n, adds, ex), k)
        RV.write('strong_s20.json', res)


def tilt_core(D, H, mult):
    """Registered longs outside the strong set at a lower risk; shorts and strong names untouched; mult 0 drops them."""
    out = []
    for d, lst in enumerate(D.reg):
        row = []
        for e in lst:
            if e[2] > 0 and not H[d, e[1]]:
                if mult == 0:
                    continue
                e = tuple(e[:6]) + ((e[6] if len(e) > 6 else None), (e[7] if len(e) > 7 else None), (e[8] if len(e) > 8 else None), mult)
            row.append(e)
        out.append(row)
    return out


def s21():
    D, F, M, shorts, replace = setup7()
    S = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(S, 12, 36)
    b = pool_book2(D, F, H, S)
    res = {}
    for k, (core, sat) in dict(R1=(.5, .5), R2=(.75, .5), R3=(0, .5), R4=(.5, .75), R5=(.5, 1.0)).items():
        res[k] = account(D, merge(tilt_core(D, H, core), sized(b, sat)), d5_rules(D), k)
        RV.write('strong_s21.json', res)


def s22():
    D, F, M, shorts, replace = setup7()
    S = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(S, 12, 36)
    L = close_list(D, F)
    P = profile(D, F, L, classes=(('pullback', 'breakout'), ('ep',)))
    Px = np.where(np.isfinite(P), P, -20.0) + np.nan_to_num(S) * .01
    print('profile rank on his entries inside the set days', sum(np.isfinite(P[x[0], x[1]]) for x in D.his), flush=True)
    res = {}
    b3 = pool_book2(D, F, H, S)
    b2 = pool_book2(D, F, H, S, True, 2.0)
    bp = pool_book2(D, F, H, Px)
    bpp = pool_book2(D, F, H, Px, True, 2.0)
    fb = lambda: replace(d5_rules(D), risk_low=.0025)
    res['T1'] = account(D, merge(D.reg, sized(b3, .5)), fb(), 'T1')
    res['T2'] = account(D, merge(D.reg, sized(b2, .5)), d5_rules(D), 'T2')
    res['T3'] = account(D, merge(D.reg, sized(bp, .5)), d5_rules(D), 'T3')
    res['T4'] = account(D, merge(D.reg, sized(bpp, .5)), d5_rules(D), 'T4')
    res['T5'] = account(D, merge(tilt_core(D, H, .75), sized(bpp, .5)), d5_rules(D), 'T5')
    RV.write('strong_s22.json', res)


def s23():
    D, F, M, shorts, replace = setup7()
    S = name_score(D, F, M, HOLD['H3'])
    H12, H20 = hold_sim(S, 12, 36), hold_sim(S, 20, 60)
    fb = lambda n=6: replace(d5_rules(D, n), risk_low=.0025)
    res = {}
    plan = dict(F1=(H12, .5, 6), F2=(H12, .75, 6), F3=(H12, .5, 8), F4=(H20, 1.0, 6), F5=(H20, .5, 6))
    for k, (H, core, n) in plan.items():
        res[k] = account(D, merge(tilt_core(D, H, core) if core < 1 else D.reg, sized(pool_book2(D, F, H, S), .5)), fb(n), k)
        RV.write('strong_s23.json', res)


def f1_entries(D, F, M, K=12, out=None, core=.5, sat=.5, grp='H3'):
    S = name_score(D, F, M, HOLD[grp])
    H = hold_sim(S, K, out or 3 * K)
    return merge(tilt_core(D, H, core), sized(pool_book2(D, F, H, S), sat)), H, S


def s24():
    """F1 up close: head of the book, parts, and the neighbours."""
    from . import panels
    D, F, M, shorts, replace = setup7()
    fb = lambda n=6, adds=(3, 6): replace(d5_rules(D, n, adds), risk_low=.0025)
    e, H, S = f1_entries(D, F, M)
    st, tr = D.base.run(D.A, e, panels.WINDOW, D.pool, fb(), placebo=0, audit=True)
    idx = {str(x): i for i, x in enumerate(D.A['codes'])}
    lon = [t for t in tr if t['side'] > 0]
    gross = sum(t['pnl'] for t in lon if t['pnl'] > 0)
    print('head of the book', flush=True)
    for t in sorted(lon, key=lambda t: -t['pnl'])[:12]:
        print(f"  {t['code'][3:]:5s} {t['entry']} -> {t['exit']} kind {t['kind']} days {t['days']:3d} ret {t['ret']:+.0%} R {float(t.get('r') or 0):+.1f} share {t['pnl'] / gross:.1%} why {t['why']}", flush=True)
    by = {}
    for t in lon:
        by.setdefault(t['kind'], [0, 0.0, 0])
        by[t['kind']][0] += 1
        by[t['kind']][1] += t['pnl']
        by[t['kind']][2] += t['pnl'] > 0
    print('by layer', {k: (v[0], round(v[1] / gross, 3), round(v[2] / v[0], 3)) for k, v in by.items()}, flush=True)
    bigp, seen = 0.0, set()
    for x in D.big:
        d, j = x[0], x[1]
        peak = d + 1 + int(np.nanargmax(D.h[d + 1:d + 21, j]))
        for k, t in enumerate(lon):
            if k in seen or idx[str(t['code'])] != j or t['entry'] not in D.di:
                continue
            a, b = D.di[t['entry']], D.di[t['exit']]
            if a <= peak and b >= d:
                bigp += t['pnl']
                seen.add(k)
    print('profit on his big runs share of gross', round(bigp / gross, 3), flush=True)
    H2 = np.zeros(D.c.shape, bool)
    for t in lon:
        if t['entry'] in D.di and t['exit'] in D.di:
            H2[D.di[t['entry']]:D.di[t['exit']] + 1, idx[str(t['code'])]] = True
    for p, f in (('2024-25', lambda s: s <= CUT), ('2026', lambda s: s > CUT)):
        R = seg(D.big, f)
        b = sum(H2[x[0]:x[0] + 21, x[1]].any() for x in R)
        print(p, 'big entries', len(R), 'on board within 20 days', int(b), 'held on his date', sum(H2[x[0], x[1]] for x in seg(D.his, f)), 'of', len(seg(D.his, f)), flush=True)
    res = {}
    print('neighbours', flush=True)
    res['base'] = account(D, e, fb(), 'F1')
    for k, (K, out, core, sat, n, adds) in dict(K10=(10, None, .5, .5, 6, (3, 6)), K15=(15, None, .5, .5, 6, (3, 6)), O24=(12, 24, .5, .5, 6, (3, 6)), O48=(12, 48, .5, .5, 6, (3, 6)), C4=(12, None, .4, .5, 6, (3, 6)), C6=(12, None, .6, .5, 6, (3, 6)), S4=(12, None, .5, .4, 6, (3, 6)), S6=(12, None, .5, .6, 6, (3, 6)), A5=(12, None, .5, .5, 6, (5, 10))).items():
        ee, _, _ = f1_entries(D, F, M, K, out, core, sat)
        res[k] = account(D, ee, fb(n, adds), k)
    ru = replace(fb(), buy_cost=.001, sell_cost=.001)
    res['cost2'] = account(D, e, ru, 'cost2')
    RV.write('strong_s24.json', res)


def s25():
    from . import panels
    D, F, M, shorts, replace = setup7()
    fb = replace(d5_rules(D), risk_low=.0025)
    S = name_score(D, F, M, HOLD['H3'])
    res = dict(draws=[])
    rng = np.random.default_rng(7)
    for i in range(10):
        R = np.where(M, rng.random(M.shape, dtype=np.float32), np.nan)
        keep = np.full(R.shape, .5, dtype=np.float32)
        for d in range(1, len(R)):
            keep[d] = .97 * keep[d - 1] + .03 * np.nan_to_num(R[d], nan=.5)
        keep = np.where(M, keep, np.nan)
        H = hold_sim(keep, 12, 36)
        e = merge(tilt_core(D, H, .5), sized(pool_book2(D, F, H, keep), .5))
        r = account(D, e, fb, f'rand{i}')
        res['draws'].append({k: r[k] for k in ('by_year', 'maxdd', 'board', 'run', 'held1', 'held2', 'strict', 'strict26', 'his_profit')})
        RV.write('strong_s25.json', res)
    e, H, _ = f1_entries(D, F, M)
    res['F1_placebo'] = account(D, e, fb, 'F1pl', placebo=30).get('placebo')
    RV.write('strong_s25.json', res)
    print('placebo', res['F1_placebo'], flush=True)


def f1_rules(D, n=6, adds=(3, 6), **kw):
    from dataclasses import replace
    return replace(d5_rules(D, n, adds), risk_low=.0025, **kw)


def s26():
    import collections
    from . import panels
    D, F, M, shorts, replace = setup7()
    e, H, S = f1_entries(D, F, M)
    st, tr = D.base.run(D.A, e, panels.WINDOW, D.pool, f1_rules(D), placebo=0, audit=True)
    q = collections.defaultdict(lambda: np.zeros(4))
    for t in tr:
        if t['side'] > 0:
            r = q[(t['entry'][:4] + 'Q' + str((int(t['entry'][5:7]) - 1) // 3 + 1), t['kind'])]
            r += (1, t['pnl'] > 0, float(t.get('r') or 0), t['pnl'])
    eq = 1.0
    print('quarter layer n win avgR pnl', flush=True)
    for k in sorted(q):
        r = q[k]
        print(f"  {k[0]} {k[1]:5s} {int(r[0]):4d} {r[1] / r[0]:.2f} {r[2] / r[0]:+.2f} {r[3]:+9.2f}", flush=True)
    for kind in ('n1', 'list'):
        L = [t for t in tr if t['side'] > 0 and t['kind'] == kind]
        w = collections.defaultdict(list)
        for t in L:
            w[t['why']].append(t)
        print(kind, 'exits', {k: (len(v), round(float(np.mean([float(x.get('r') or 0) for x in v])), 2), round(float(np.mean([x['ret'] for x in v])) * 100, 1), round(float(np.mean([x['days'] for x in v])), 1)) for k, v in w.items()}, flush=True)
        los = [t for t in L if t['pnl'] <= 0]
        d = np.array([t['days'] for t in los])
        st_ = np.array([float(t.get('risk_pct') or 0) for t in L])
        print('  loser days q25/50/75', np.percentile(d, [25, 50, 75]), 'share day<=1', round(float((d <= 1).mean()), 2), 'stop q25/50/75', np.round(np.percentile(st_, [25, 50, 75]) * 100, 1), flush=True)
    # was the stop inside the entry day's own range?
    idx = {str(x): i for i, x in enumerate(D.A['codes'])}
    inside = wide = 0
    for t in tr:
        if t['kind'] == 'list' and t['side'] > 0 and t['entry'] in D.di:
            d, j = D.di[t['entry']], idx[str(t['code'])]
            if float(t['stop']) > float(D.l[d, j]) * 1.0005:
                inside += 1
            wide += 1
    print('list entries with a stop above the day low (clipped inside the bar)', inside, 'of', wide, flush=True)


def s26b():
    from . import panels
    D, F, M, shorts, replace = setup7()
    e, H, S = f1_entries(D, F, M)
    st, tr = D.base.run(D.A, e, panels.WINDOW, D.pool, f1_rules(D), placebo=0, audit=True)
    L = [t for t in tr if t['side'] > 0 and t['kind'] == 'list' and t['why'] == 'stop']
    print(sorted(L[0].keys()), flush=True)
    for t in L[:6] + sorted(L, key=lambda x: float(x.get('r') or 0))[:6]:
        print({k: (round(float(t[k]), 4) if isinstance(t[k], (float, np.floating)) else t[k]) for k in ('code', 'entry', 'exit', 'days', 'fill', 'stop', 'r', 'ret', 'ret_invested', 'risk_pct', 'add_tries')}, str(t.get('executions'))[:220], flush=True)
    a = np.array([float(t.get('r') or 0) for t in L])
    print('stop exits', len(L), 'R q10/50/90', np.round(np.percentile(a, [10, 50, 90]), 2), 'with adds', sum(1 for t in L if len(t.get('executions') or []) > 2), flush=True)


def pool_book3(D, F, H, S, max_ext=3.0, upper=False, wmax=.05, half=.5):
    """His stop as he puts it: the day's low.  A day too wide for it is not a buy."""
    c, l, h = D.c, D.l, D.h
    touch = (F['lowe9'] <= .1) & (c > D.e9)
    if upper:
        touch = touch & (F['cpos'] >= .5)
    tr = touch | (c > lag(h)) & (F['cpos'] >= .5)
    ok = np.nan_to_num(F['ext21'], nan=99) <= max_ext
    out = [[] for _ in range(len(c))]
    for d in range(1, len(c)):
        m = H[d] & ok[d] & tr[d] & np.isfinite(c[d]) & np.isfinite(l[d])
        for j in np.flatnonzero(m):
            cc, low = float(c[d, j]), float(l[d, j])
            a = D.adr[d - 1, j]
            lim = min(wmax, float(a) * half) if np.isfinite(a) else wmax
            if cc - low > cc * lim:
                continue
            out[d].append(((1.0, -float(np.nan_to_num(S[d, j]))), int(j), 1, cc, float(min(low, cc * .99)), 'list'))
    return out


def s27():
    D, F, M, shorts, replace = setup7()
    e, H, S = f1_entries(D, F, M)
    core = tilt_core(D, H, .5)
    print('entries a year: clip', round(sum(len(x) for x in pool_book2(D, F, H, S)) / (len(D.days) / 252)), 'filter', round(sum(len(x) for x in pool_book3(D, F, H, S)) / (len(D.days) / 252)), flush=True)
    b3, b4 = pool_book3(D, F, H, S), pool_book3(D, F, H, S, upper=True)
    res = {}
    res['G1'] = account(D, e, f1_rules(D, add_stop='cost'), 'G1')
    res['G2'] = account(D, merge(core, sized(b3, .5)), f1_rules(D), 'G2')
    res['G3'] = account(D, merge(core, sized(b3, .5)), f1_rules(D, add_stop='cost'), 'G3')
    res['G4'] = account(D, merge(core, sized(b4, .5)), f1_rules(D, add_stop='cost'), 'G4')
    res['G5'] = account(D, merge(core, sized(b3, .5)), f1_rules(D, add_stop='cost', feedback_opened=True), 'G5')
    RV.write('strong_s27.json', res)


def states(D, F, H):
    """Daily market states, each read at the close of the day before the entry row they are indexed by."""
    from .martin_list import ema
    from .martin_strong import bench
    c = D.c
    e21 = ema(c.astype(float), 21).astype(np.float32)
    q = bench(D.days, 'QQQ')
    qe = ema(q[:, None], 21)[:, 0]
    top = np.zeros(c.shape, bool)
    for d in range(1, len(c)):
        v = np.where(D.U[d], F['act20'][d - 1], np.nan)
        f = np.flatnonzero(np.isfinite(v))
        if len(f) > 100:
            top[d, f[np.argsort(-v[f])[:100]]] = True
    with np.errstate(all='ignore'):
        br = (top & (c > e21)).sum(1) / np.maximum(top.sum(1), 1)
        set9 = (H & (c > D.e9)).sum(1) / np.maximum(H.sum(1), 1)
        set21 = (H & (c > e21)).sum(1) / np.maximum(H.sum(1), 1)
        g5 = c / lag(c, 5) - 1
        set5 = np.array([np.nanmean(g5[d, H[d]]) if H[d].any() else 0.0 for d in range(len(c))])
    lo = np.array([np.nanargmin(q[max(0, d - 19):d + 1]) for d in range(len(q))])
    since_lo = np.array([min(d, 19) - lo[d] for d in range(len(q))], dtype=float)
    st = dict(breadth=br, set9=set9, set21=set21, set5=set5, q_ext=q / qe - 1, q_since_low=since_lo)
    return {k: np.concatenate([[np.nan], np.asarray(v, dtype=float)[:-1]]) for k, v in st.items()}


def bucket(name, x, r, win, part):
    ok = np.isfinite(x)
    a, b = np.nanpercentile(x[ok], [33.3, 66.7])
    row = []
    for p in ('p1', 'p2'):
        m = ok & (part == p)
        lo_, mi, hi = m & (x <= a), m & (x > a) & (x <= b), m & (x > b)
        row.append(f"{r[lo_].mean():+.2f}/{r[mi].mean():+.2f}/{r[hi].mean():+.2f} win {win[lo_].mean():.2f}/{win[hi].mean():.2f}")
    print(f"  {name:12s} 2024-25 {row[0]}   2026 {row[1]}", flush=True)


def s28():
    from . import panels
    D, F, M, shorts, replace = setup7()
    e, H, S = f1_entries(D, F, M)
    st, tr = D.base.run(D.A, e, panels.WINDOW, D.pool, f1_rules(D, add_stop='cost'), placebo=0, audit=True)
    idx = {str(x): i for i, x in enumerate(D.A['codes'])}
    L = sorted([t for t in tr if t['side'] > 0 and t['kind'] == 'list' and t['entry'] in D.di], key=lambda t: t['entry'])
    print('list trades', len(L), flush=True)
    dd = np.array([D.di[t['entry']] for t in L])
    jj = np.array([idx[str(t['code'])] for t in L])
    R = np.clip(np.array([float(t.get('r') or 0) for t in L]), -5, 30)
    win = np.array([t['pnl'] > 0 for t in L], float)
    part = np.array(['p1' if t['entry'] <= CUT else 'p2' for t in L])
    print('mean R', {p: round(float(R[part == p].mean()), 2) for p in ('p1', 'p2')}, flush=True)
    stx = states(D, F, H)
    print('market state, thirds low / mid / high', flush=True)
    for k, v in stx.items():
        bucket(k, v[dd], R, win, part)
    ex = np.array([D.di.get(t['exit'], D.di[t['entry']]) for t in L])
    rec = np.full(len(L), np.nan)
    for i in range(len(L)):
        done = np.flatnonzero((ex[:i] < dd[i]))[-20:]
        if len(done) >= 10:
            rec[i] = R[done].mean()
    bucket('recent20R', rec, R, win, part)
    print('name at entry', flush=True)
    rankS = np.array([float((S[d][H[d]] > S[d, j]).mean()) if H[d].any() else np.nan for d, j in zip(dd, jj)])
    bucket('rank_in_set', -rankS, R, win, part)
    for k in ('peer_pot', 'peer_rank', 'ext21', 'ext9', 'range10', 'to1_20', 'cpos', 'adr', 'gain', 'act1', 'money', 'g21', 'pos250', 'pot20', 'stack'):
        bucket(k, F[k][dd, jj], R, win, part)
    bucket('stop_dist', np.array([float(t.get('risk_pct') or 0) for t in L]), R, win, part)


QUALITY = dict(heat=(('pot20', -1), ('peer_pot', -1), ('g21', -1)), calm=(('to1_20', -1),), speed=(('adr', -1),), liquid=(('money', 1),), close=(('cpos', 1),))


def quality(D, F, M, H, S, keys=None, rank=True):
    """Entry quality at the close, one vote per group, about -0.5 to 0.5; the set rank is the evening's."""
    keys = keys or tuple(QUALITY)
    q = np.zeros(D.c.shape, dtype=np.float32)
    n = 0
    for g in keys:
        part = np.zeros(D.c.shape, dtype=np.float32)
        for k, sign in QUALITY[g]:
            part += np.nan_to_num(pct(sign * F[k], M) - .5)
        q += part / len(QUALITY[g])
        n += 1
    if rank:
        q += np.nan_to_num(pct(S, H) - .5)
        n += 1
    return q / n


def sized_q(book, Q, lo=.2, hi=1.0, base=.5, gain=2.0, skip=None, by_q=False):
    out = []
    for d, lst in enumerate(book):
        row = []
        for e in lst:
            q = float(Q[d, e[1]])
            if skip is not None and q < skip:
                continue
            pr = (2.0, -q) if by_q else (2.0,) + (e[0] if isinstance(e[0], tuple) else (e[0],))
            row.append((pr,) + tuple(e[1:6]) + ((e[6] if len(e) > 6 else None), None, None, float(np.clip(base + gain * q, lo, hi))))
        out.append(row)
    return out


def s29():
    D, F, M, shorts, replace = setup7()
    e, H, S = f1_entries(D, F, M)
    core = tilt_core(D, H, .5)
    b = pool_book2(D, F, H, S)
    Q, Qh = quality(D, F, M, H, S), quality(D, F, M, H, S, ('heat',), False)
    v = np.array([Q[d, x[1]] for d, r in enumerate(b) for x in r])
    print('Q q10/50/90', np.round(np.percentile(v, [10, 50, 90]), 3), 'mult q10/50/90', np.round(np.percentile(np.clip(.5 + 2 * v, .2, 1), [10, 50, 90]), 2), flush=True)
    cost = f1_rules(D, add_stop='cost')
    res = dict(Q1=account(D, merge(core, sized_q(b, Q)), cost, 'Q1'))
    res['Q2'] = account(D, merge(core, sized_q(b, Q)), f1_rules(D), 'Q2')
    res['Q3'] = account(D, merge(core, sized_q(b, Qh)), cost, 'Q3')
    res['Q4'] = account(D, merge(core, sized_q(b, Q, skip=-.1)), cost, 'Q4')
    res['Q5'] = account(D, merge(core, sized_q(b, Q, by_q=True)), cost, 'Q5')
    RV.write('strong_s29.json', res)


def limit_book(D, F, H, S, wmax=.03, max_ext=3.0):
    """A resting buy limit at yesterday's 9 EMA for the strong set: filled on the way down, so the low follows the fill."""
    o, l, c = D.o, D.l, D.c
    ext = np.nan_to_num(F['ext21'], nan=99)
    out = [[] for _ in range(len(c))]
    for d in range(2, len(c)):
        L = D.e9[d - 1]
        m = H[d] & (ext[d - 1] <= max_ext) & (c[d - 1] > L) & (o[d] >= L) & (l[d] <= L) & np.isfinite(l[d])
        for j in np.flatnonzero(m):
            lv = float(L[j])
            a = D.adr[d - 1, j]
            w = max(.01, min(wmax, float(a) / 2 if np.isfinite(a) else wmax))
            stop = lv * (1 - w)
            e = ((1.0, -float(np.nan_to_num(S[d, j]))), int(j), 1, lv, float(stop), 'lim')
            out[d].append(e + ((float(stop),) if float(l[d, j]) <= stop else ()))
    return out


def breakout_book(D, F, H, S, max_ext=3.0):
    """The close entries of the layer without the touch of the 9 EMA."""
    c, l, h = D.c, D.l, D.h
    tr = (c > lag(h)) & (F['cpos'] >= .5)
    ok = np.nan_to_num(F['ext21'], nan=99) <= max_ext
    out = [[] for _ in range(len(c))]
    for d in range(1, len(c)):
        for j in np.flatnonzero(H[d] & ok[d] & tr[d] & np.isfinite(l[d])):
            cc = float(c[d, j])
            a = D.adr[d - 1, j]
            w = min(.05, float(a) / 2) if np.isfinite(a) else .05
            out[d].append(((1.0, -float(np.nan_to_num(S[d, j]))), int(j), 1, cc, float(min(max(float(l[d, j]), cc * (1 - w)), cc * .99)), 'list'))
    return out


def lim_rules(D, n=6, adds=(3, 6), **kw):
    from dataclasses import replace
    ru = f1_rules(D, n, adds, **kw)
    mg = dict(ru.management_by_kind)
    if adds:
        mg['lim'] = dict(add_levels=adds)
    return replace(ru, management_by_kind=mg, max_new_by_kind={**ru.max_new_by_kind, 'lim': n}, intraday_kinds=tuple(ru.intraday_kinds) + ('lim',))


def s30():
    D, F, M, shorts, replace = setup7()
    e, H, S = f1_entries(D, F, M)
    core = tilt_core(D, H, .5)
    lim, brk = limit_book(D, F, H, S), breakout_book(D, F, H, S)
    pdh = pdh_book(D, F, H, S, 'a')
    print('a year: limit fills', round(sum(len(x) for x in lim) / (len(D.days) / 252)), 'same-day stops', round(sum(len(z) > 6 for x in lim for z in x) / (len(D.days) / 252)), 'close breakouts', round(sum(len(x) for x in brk) / (len(D.days) / 252)), flush=True)
    both = [a + b for a, b in zip(lim, brk)]
    res = dict(L1=account(D, merge(core, sized(lim, .5)), lim_rules(D), 'L1'))
    res['L2'] = account(D, merge(core, sized(both, .5)), lim_rules(D), 'L2')
    res['L3'] = account(D, merge(core, sized(both, .5)), lim_rules(D, add_stop='cost'), 'L3')
    b4 = [[((p[0],) + tuple(p[1:5]) + ('lim',) + tuple(p[6:])) for p in row] for row in pdh]
    res['L4'] = account(D, merge(core, sized([a + b for a, b in zip(lim, b4)], .5)), lim_rules(D), 'L4')
    res['L5'] = account(D, merge(core, sized(both, .5)), lim_rules(D, 6, ()), 'L5')
    RV.write('strong_s30.json', res)


SKIP = {'g1', 'gain', 'cpos', 'gap', 'opgain', 'overpdh', 'lowe9', 'lowe21', 'cross_e9', 'inside', 'nr', 'to1_20', 'act1', 'act3', 'actmax5', 'price', 'nsq', 'nr10'}


def design(D, F, M):
    """Rows: active names on every other day.  Columns: within-day percentile of each evening measure and its square."""
    keys = sorted(k for k in F if k not in SKIP)
    days = D.window[::2]
    idx = [np.flatnonzero(M[d]) for d in days]
    n = sum(len(x) for x in idx)
    X = np.zeros((n, 2 * len(keys)), dtype=np.float32)
    for c, k in enumerate(keys):
        x = F[k] if k.startswith('w_') else lag(F[k])
        p = np.nan_to_num(pct(x, M) - .5)
        pos = 0
        for d, ix in zip(days, idx):
            X[pos:pos + len(ix), c] = p[d, ix]
            pos += len(ix)
    X[:, len(keys):] = 4 * X[:, :len(keys)] ** 2 - 1 / 3
    return keys, days, idx, X


def fit_logit(X, y, ridge=30.0, steps=250, lr=.5):
    pos = y > 0
    w = np.zeros(X.shape[1], dtype=np.float32)
    b = float(np.log(pos.mean() / (1 - pos.mean())))
    wt = np.where(pos, .5 / pos.mean(), .5 / (1 - pos.mean())).astype(np.float32)
    m = len(y)
    for _ in range(steps):
        z = X @ w + b
        p = 1 / (1 + np.exp(-z))
        g = (wt * (p - y))
        w -= lr * ((X.T @ g) / m + ridge * w / m)
        b -= lr * float(g.mean())
    return w, b


def label_score(D, F, M, back=10, ridge=30.0, linear=False, built=None):
    keys, days, idx, X = built or design(D, F, M)
    if linear:
        X = X[:, :len(keys)]
    dpos = np.concatenate([[i] * len(ix) for i, ix in enumerate(idx)])
    jpos = np.concatenate(idx)
    day_arr = np.array(days)[dpos]
    y = np.zeros(len(jpos), dtype=np.float32)
    key = {}
    for i, (d, j) in enumerate(zip(day_arr, jpos)):
        key[(int(d), int(j))] = i
    for x in D.his:
        for k in range(x[0] - back, x[0] + 1):
            i = key.get((k, x[1]))
            if i is not None:
                y[i] = 1
    print('positives', int(y.sum()), 'of', len(y), flush=True)
    S = np.full(D.c.shape, np.nan, dtype=np.float32)
    ds = np.array(D.days)
    weights = []
    for a, z in FOLDS:
        lo, hi = D.di.get(a), None
        inside = np.array([a <= ds[d] <= z for d in day_arr])
        fd = np.flatnonzero([a <= x <= z for x in D.days])
        if not inside.any():
            continue
        buf = (day_arr < fd[0] - back) | (day_arr > fd[-1] + back)
        w, b = fit_logit(X[buf], y[buf], ridge)
        weights.append(w)
        S[day_arr[inside], jpos[inside]] = X[inside] @ w
    return S, keys, np.mean(weights, axis=0)


def s31():
    D, F, M, shorts, replace = setup7()
    with np.errstate(all='ignore'):
        F.pop('nsq', None), F.pop('nr10', None)
    S0 = name_score(D, F, M, HOLD['H3'])
    S1, keys, w = label_score(D, F, M)
    # the odd days the design skipped: carry the score of the day before
    for d in range(1, len(S1)):
        if not np.isfinite(S1[d]).any():
            S1[d] = np.where(M[d], S1[d - 1], np.nan)
    np.save('/tmp/msum/s31_score.npy', S1)
    top = sorted(zip(keys, w[:len(keys)], w[len(keys):]), key=lambda r: -abs(r[1]) - abs(r[2]))[:16]
    print('top weights', [(k, round(float(a), 2), round(float(b), 2)) for k, a, b in top], flush=True)
    res = {}
    for K in (5, 8, 12):
        for name, S in (('H3', S0), ('LBL', S1)):
            H = hold_sim(S, K, 3 * K)
            r = overlap(D, H, f'{name}_{K}')
            r['stage'] = stage(D, H)
            print('    stage', r['stage'], flush=True)
            res[f'{name}_{K}'] = r
    RV.write('strong_s31.json', res)


def s31b():
    D, F, M, shorts, replace = setup7()
    F.pop('nsq', None), F.pop('nr10', None)
    built = design(D, F, M)
    keys = built[0]
    res = {}
    for name, ridge, linear in (('R3k', 3e3, False), ('R30k', 3e4, False), ('R300k', 3e5, False), ('L3k', 3e3, True), ('L30k', 3e4, True)):
        S, _, w = label_score(D, F, M, ridge=ridge, linear=linear, built=built)
        for d in range(1, len(S)):
            if not np.isfinite(S[d]).any():
                S[d] = np.where(M[d], S[d - 1], np.nan)
        np.save(f'/tmp/msum/s31_{name}.npy', S)
        top = sorted(zip(keys, w[:len(keys)]), key=lambda r: -abs(r[1]))[:10]
        print(name, [(k, round(float(a), 2)) for k, a in top], flush=True)
        for K in (8, 12):
            H = hold_sim(S, K, 3 * K)
            r = overlap(D, H, f'{name}_{K}')
            r['stage'] = stage(D, H)
            print('    stage', r['stage'], flush=True)
            res[f'{name}_{K}'] = r
        RV.write('strong_s31b.json', res)


def peers_by_day(D, step=5, n=40, rho=.5):
    """Who moves with whom among the active names, refreshed every step days, from returns known at the evening before."""
    c = D.c
    with np.errstate(all='ignore'):
        r = c / lag(c) - 1
        base = np.nanmedian(np.where(D.rk < L, r, np.nan), axis=1, keepdims=True)
    rr = np.nan_to_num(r - base).astype(np.float32)
    out, cur = {}, None
    for d in range(60, len(c)):
        names = np.flatnonzero(D.rk[d] < L)
        if len(names) < 30:
            continue
        if cur is None or d % step == 0:
            w = rr[d - n:d][:, names]
            w = w - w.mean(0)
            sd = w.std(0) + 1e-6
            cur = (names, ((w.T @ w) / len(w) / np.outer(sd, sd)) >= rho)
        out[d] = cur
    return out


def hold_theme(S, K, out, peers, cap):
    """As hold_sim, with at most cap names of one group in the set: a new name stays out while cap of its peers are in."""
    H = np.zeros(S.shape, bool)
    cur = np.zeros(S.shape[1], bool)
    for d in range(len(S)):
        v = np.nan_to_num(S[d], nan=-1e9)
        o = np.argsort(-v)
        rk = np.empty(len(v), int)
        rk[o] = np.arange(len(v))
        cur = cur & (rk < out) & (v > -1e8)
        if d in peers:
            names, near = peers[d]
            pos = {int(j): i for i, j in enumerate(names)}
            inset = np.zeros(len(names), bool)
            inset[[pos[int(j)] for j in np.flatnonzero(cur) if int(j) in pos]] = True
            for j in o[:K]:
                j = int(j)
                if v[j] <= -1e8 or cur[j]:
                    continue
                i = pos.get(j)
                if i is not None and (near[i] & inset).sum() >= cap:
                    continue
                cur[j] = True
                if i is not None:
                    inset[i] = True
        H[d] = cur
    return H


def peer_mean(D, S, peers):
    out = np.full(S.shape, np.nan, dtype=np.float32)
    for d, (names, near) in peers.items():
        v = np.nan_to_num(S[d, names], nan=0.0)
        out[d, names] = (near * v).sum(1) / near.sum(1)
    return out


def s32():
    D, F, M, shorts, replace = setup7()
    S = name_score(D, F, M, HOLD['H3'])
    peers = peers_by_day(D)
    print('median peers', float(np.median([np.median(n.sum(1)) for _, n in list(peers.values())[::40]])), flush=True)
    Sb = np.where(M, np.nan_to_num(S) + np.nan_to_num(pct(peer_mean(D, S, peers), M) - .5) * 2, np.nan)
    res = {}
    cases = dict(H3_8=(S, 8, 0), H3_12=(S, 12, 0), C1=(S, 8, 2), C2=(S, 12, 2), C3=(S, 12, 3), B1=(Sb, 12, 0), B2=(Sb, 12, 2), C4=(S, 16, 2))
    for k, (s_, K, cap) in cases.items():
        H = hold_theme(s_, K, 3 * K, peers, cap) if cap else hold_sim(s_, K, 3 * K)
        r = overlap(D, H, k)
        r['stage'] = stage(D, H)
        print('    stage', r['stage'], sum(r['stage']), flush=True)
        res[k] = r
    RV.write('strong_s32.json', res)


def s33():
    D, F, M, shorts, replace = setup7()
    e, H, S = f1_entries(D, F, M)
    c = D.c.astype(float)
    res = dict(REG=account(D, D.reg, D.rules, 'REG'))
    d5 = merge(D.reg, sized(pool_book2(D, F, H, S), .5))
    res['D5'] = account(D, d5, d5_rules(D), 'D5')
    res['F1'] = account(D, e, f1_rules(D), 'F1')
    res['G1'] = account(D, e, f1_rules(D, add_stop='cost'), 'G1')
    for n in (10, 20):
        hi = roll_ext(D.c, n, np.nanmax)
        D.A[f'add_hi{n}'] = (D.c >= hi) & H & np.isfinite(D.c)
    base = lambda sig, frac, mx, stop, **kw: f1_rules(D, 6, (), add_signal=sig, add_signal_frac=frac, add_signal_max=mx, add_signal_stop=stop, add_signal_profit=True, **kw)
    res['A1'] = account(D, e, base('add_hi10', .5, 3, 'keep'), 'A1')
    res['A2'] = account(D, e, base('add_hi10', .5, 3, 'low'), 'A2')
    res['A3'] = account(D, e, base('add_hi10', 1.0, 2, 'fill'), 'A3')
    res['A4'] = account(D, e, base('add_hi20', .5, 3, 'keep'), 'A4')
    ru = replace(base('add_hi10', .5, 3, 'keep'), max_position=.5)
    res['A5'] = account(D, e, ru, 'A5')
    RV.write('strong_s33.json', res)


def s34():
    D, F, M, shorts, replace = setup7()
    e, H, S = f1_entries(D, F, M)
    res = dict(E1=account(D, e, f1_rules(D, 6, (2, 4)), 'E1'))
    res['E2'] = account(D, e, f1_rules(D, 6, (1, 3)), 'E2')
    res['E3'] = account(D, e, f1_rules(D, trim_signal='ext3', trim_signal_frac=.2), 'E3')
    res['E4'] = account(D, e, f1_rules(D, trim_signal='ext3', trim_signal_frac=.3), 'E4')
    res['E5'] = account(D, e, replace(f1_rules(D), max_position=.5), 'E5')
    RV.write('strong_s34.json', res)


NEIGH = dict(base=(12, None, .5, .5), K10=(10, None, .5, .5), K15=(15, None, .5, .5), O2=(12, 24, .5, .5), O4=(12, 48, .5, .5), S4=(12, None, .5, .4), S6=(12, None, .5, .6), C4=(12, None, .4, .5), C6=(12, None, .6, .5))


def s35():
    D, F, M, shorts, replace = setup7()
    trim = dict(trim_signal='ext3', trim_signal_frac=.2)
    conf = dict(F1=lambda: f1_rules(D), E2=lambda: f1_rules(D, 6, (1, 3)), E3=lambda: f1_rules(D, **trim), EE=lambda: f1_rules(D, 6, (1, 3), **trim))
    res = {}
    for name, ru in conf.items():
        rows = []
        for k, (K, out, core, sat) in NEIGH.items():
            e, H, S = f1_entries(D, F, M, K, out, core, sat)
            r = account(D, e, ru(), f'{name}_{k}')
            y = r['by_year']
            rows.append(dict(p=k, y24=y['2024'], y25=y['2025'], y26=y['2026'], mult=(1 + y['2024']) * (1 + y['2025']) * (1 + y['2026']), dd=r['maxdd'], board=r['board'], run=r['run'], stage=r['stage1'] + r['stage2'], strict=r['strict'] + r['strict26'], held=r['held1'] + r['held2']))
        res[name] = rows
        m = lambda k, f=np.median: float(f([x[k] for x in rows]))
        print(f"== {name} mult median {m('mult'):.1f} min {m('mult', np.min):.1f} max {m('mult', np.max):.1f} | y {m('y24'):+.2f}/{m('y25'):+.2f}/{m('y26'):+.2f} worst {m('y24', np.min):+.2f}/{m('y25', np.min):+.2f}/{m('y26', np.min):+.2f} dd {m('dd'):.2f} board {m('board'):.0f} (min {m('board', np.min):.0f}) run {m('run'):.2f} stage {m('stage'):.0f} strict {m('strict'):.0f} held {m('held'):.0f}", flush=True)
        RV.write('strong_s35.json', res)


def neighbours(D, F, M, conf, out):
    res = {}
    for name, ru in conf.items():
        rows = []
        for k, (K, o, core, sat) in NEIGH.items():
            e, H, S = f1_entries(D, F, M, K, o, core, sat)
            r = account(D, e, ru(), f'{name}_{k}')
            y = r['by_year']
            rows.append(dict(p=k, y24=y['2024'], y25=y['2025'], y26=y['2026'], mult=(1 + y['2024']) * (1 + y['2025']) * (1 + y['2026']), dd=r['maxdd'], board=r['board'], run=r['run'], stage=r['stage1'] + r['stage2'], strict=r['strict'] + r['strict26'], held=r['held1'] + r['held2'], big=r['big_profit'], his=r['his_profit'], win=r['win'], aw=r['avg_win'], al=r['avg_loss'], per=r['per_year']))
        res[name] = rows
        m = lambda k, f=np.median: float(f([x[k] for x in rows]))
        print(f"== {name} mult median {m('mult'):.1f} min {m('mult', np.min):.1f} max {m('mult', np.max):.1f} | y {m('y24'):+.2f}/{m('y25'):+.2f}/{m('y26'):+.2f} worst {m('y24', np.min):+.2f}/{m('y25', np.min):+.2f}/{m('y26', np.min):+.2f} dd {m('dd'):.2f} board {m('board'):.0f} (min {m('board', np.min):.0f}) run {m('run'):.2f} stage {m('stage'):.0f} strict {m('strict'):.0f} held {m('held'):.0f} bigprofit {m('big'):.2f} his {m('his'):.2f} win {m('win'):.3f} aw {m('aw'):+.3f} al {m('al'):+.3f} n/y {m('per'):.0f}", flush=True)
        RV.write(out, res)


def s36():
    D, F, M, shorts, replace = setup7()
    conf = dict(E6=lambda: f1_rules(D, 6, (1, 2, 3)), E7=lambda: f1_rules(D, 6, (.5, 1.5, 3)), E8=lambda: f1_rules(D, 6, (1, 3), add_levels=(3, 6)))
    neighbours(D, F, M, conf, 'strong_s36.json')


def s37():
    D, F, M, shorts, replace = setup7()
    neighbours(D, F, M, dict(E2=lambda: f1_rules(D, 6, (1, 3)), E9=lambda: f1_rules(D, 6, (1, 3), add_stop='cost')), 'strong_s37.json')


def s38():
    from . import panels
    D, F, M, shorts, replace = setup7()
    ru = f1_rules(D, 6, (1, 3))
    e, H, S = f1_entries(D, F, M)
    r0 = account(D, e, ru, 'E2')
    st, tr = D.base.run(D.A, e, panels.WINDOW, D.pool, ru, placebo=0, audit=True)
    lon = [t for t in tr if t['side'] > 0]
    gross = sum(t['pnl'] for t in lon if t['pnl'] > 0)
    for t in sorted(lon, key=lambda t: -t['pnl'])[:10]:
        print(f"  {t['code'][3:]:5s} {t['entry']} -> {t['exit']} {t['kind']} days {t['days']:3d} ret {t['ret']:+.0%} share {t['pnl'] / gross:.1%} why {t['why']}", flush=True)
    by = {}
    for t in lon:
        v = by.setdefault(t['kind'], [0, 0.0])
        v[0] += 1
        v[1] += t['pnl']
    print('by layer', {k: (v[0], round(v[1] / gross, 3)) for k, v in by.items()}, flush=True)
    res = dict(E2=r0, draws=[])
    rng = np.random.default_rng(7)
    for i in range(10):
        R = np.where(M, rng.random(M.shape, dtype=np.float32), np.nan)
        keep = np.full(R.shape, .5, dtype=np.float32)
        for d in range(1, len(R)):
            keep[d] = .97 * keep[d - 1] + .03 * np.nan_to_num(R[d], nan=.5)
        keep = np.where(M, keep, np.nan)
        Hr = hold_sim(keep, 12, 36)
        ee = merge(tilt_core(D, Hr, .5), sized(pool_book2(D, F, Hr, keep), .5))
        r = account(D, ee, ru, f'rand{i}')
        res['draws'].append({k: r[k] for k in ('by_year', 'maxdd', 'board', 'run', 'held1', 'held2', 'stage1', 'stage2', 'strict', 'strict26', 'his_profit', 'big_profit')})
        RV.write('strong_s38.json', res)
    res['placebo'] = account(D, e, ru, 'E2pl', placebo=30).get('placebo')
    RV.write('strong_s38.json', res)
    d = res['draws']
    med = lambda f: float(np.median([f(x) for x in d]))
    print(f"random median y {med(lambda x: x['by_year']['2024']):+.2f}/{med(lambda x: x['by_year']['2025']):+.2f}/{med(lambda x: x['by_year']['2026']):+.2f} dd {med(lambda x: x['maxdd']):.2f} board {med(lambda x: x['board']):.0f} run {med(lambda x: x['run']):.2f} stage {med(lambda x: x['stage1'] + x['stage2']):.0f} held {med(lambda x: x['held1'] + x['held2']):.0f} strict {med(lambda x: x['strict'] + x['strict26']):.0f}", flush=True)
    print('placebo', res['placebo'], flush=True)


def monthly(D, tr, days_from='2025-01-01', days_to='2025-12-31'):
    """Long and short result by entry month, and the book on the first day of each month is not needed: R and pnl share only."""
    import collections
    q = collections.defaultdict(lambda: [0, 0, 0.0, 0.0, 0.0])
    for t in tr:
        if days_from <= t['entry'] <= days_to:
            r = q[(t['entry'][:7], 'L' if t['side'] > 0 else 'S')]
            r[0] += 1
            r[1] += t['pnl'] > 0
            r[2] += float(t.get('r') or 0)
            r[3] += t['pnl']
    return q


def s39():
    """2025, month by month: equity path of the registered book and E2, positions on his 2025 names."""
    from . import panels
    D, F, M, shorts, replace = setup7()
    e, H, S = f1_entries(D, F, M)
    idx = {str(x): i for i, x in enumerate(D.A['codes'])}
    for name, ent, ru in (('REG', D.reg, D.rules), ('E2', e, f1_rules(D, 6, (1, 3)))):
        st, tr = D.base.run(D.A, ent, panels.WINDOW, D.pool, ru, placebo=0, audit=True)
        curve = st.get('_curve')
        print(name, 'curve type', type(curve), (len(curve) if curve is not None and hasattr(curve, '__len__') else None), flush=True)
        if curve is not None:
            c = np.asarray(curve, dtype=float)
            ds = [x for x in D.days if panels.WINDOW[0] <= x <= panels.WINDOW[1]][-len(c):]
            out = []
            for m in range(1, 13):
                k = f'2025-{m:02d}'
                ix = [i for i, x in enumerate(ds) if x[:7] == k]
                if ix:
                    prev = c[ix[0] - 1] if ix[0] > 0 else c[ix[0]]
                    out.append(f"{m}:{c[ix[-1]] / prev - 1:+.0%}")
            print(' ', ' '.join(out), flush=True)
        q = monthly(D, tr)
        for k in sorted(q):
            r = q[k]
            print(f"  {k[0]} {k[1]} n {r[0]:3d} win {r[1] / r[0]:.2f} sumR {r[2]:+7.1f}", flush=True)
        print('  his 2025 longs, what this book did', flush=True)
        for x in [h for h in D.his if h[4][:4] == '2025']:
            d, j = x[0], x[1]
            hit = [t for t in tr if t['side'] > 0 and idx[str(t['code'])] == j and D.di.get(t['entry'], 10 ** 6) <= d + 10 and D.di.get(t['exit'], -1) >= d - 5]
            txt = ' '.join(f"{t['entry'][5:]}>{t['exit'][5:]} {t['kind']} ret {t['ret']:+.0%} R {float(t.get('r') or 0):+.1f}" for t in hit[:3])
            print(f"   {x[2]:5s} {x[4]} {x[3]:8s} fwd {D.fwd[d, j]:+.0%} inset {bool(H[d, j])} | {txt}", flush=True)


def shadow(D, book, top=6, wait=5, target=2.0):
    """How the newest trial entries are doing, without the account: for each day's first few candidates, did the price reach
    target R within wait days before the stop.  A result counts from the day it is known; stops are checked first."""
    n = len(D.c)
    ok = np.zeros(n)
    bad = np.zeros(n)
    for d, lst in enumerate(book):
        for e in sorted(lst, key=lambda x: x[0])[:top]:
            j, fill, stop = e[1], float(e[3]), float(e[4])
            goal = fill + target * (fill - stop)
            res, day = 0, min(d + wait, n - 1)
            for k in range(d + 1, min(d + wait + 1, n)):
                if float(D.l[k, j]) <= stop:
                    res, day = -1, k
                    break
                if float(D.h[k, j]) >= goal:
                    res, day = 1, k
                    break
            if res > 0:
                ok[day] += 1
            else:
                bad[day] += 1
    return ok, bad


def roll_sum(x, n):
    c = np.concatenate([[0.0], np.cumsum(x)])
    return np.array([c[i + 1] - c[max(0, i + 1 - n)] for i in range(len(x))])


def s40():
    from . import panels
    D, F, M, shorts, replace = setup7()
    e, H, S = f1_entries(D, F, M)
    act = np.full(D.c.shape, 9999.0)
    for d in range(1, len(act)):
        v = np.where(D.U[d], F['act20'][d - 1], np.nan)
        f = np.flatnonzero(np.isfinite(v))
        act[d, f[np.argsort(-v[f])]] = np.arange(len(f))
    print('his big entries of 2025-26: evening values, then the day', flush=True)
    keys = ('g21', 'g63', 'range10', 'squeeze', 'pos60', 'stay250', 'fast250', 'adr')
    print('name day setup actRank Srank ' + ' '.join(keys) + ' | wk_near wk_tight | gain overpdh to1_20 cpos', flush=True)
    for x in sorted([h for h in D.big if h[4] >= '2025'], key=lambda r: r[4]):
        d, j = x[0], x[1]
        v = np.nan_to_num(S[d], nan=-1e9)
        sr = int((v > v[j]).sum()) if np.isfinite(S[d, j]) else -1
        pr = lambda k, b=1: f"{np.nan_to_num(np.mean(F[k][d - b][M[d]] < F[k][d - b, j])):.2f}"
        print(f"{x[2]:5s} {x[4]} {x[3]:8s} {int(act[d, j]):4d} {sr:4d} " + ' '.join(pr(k) for k in keys) + f" | {pr('w_wk_near', 0)} {pr('w_wk_tight', 0)} | {F['gain'][d, j]:+.1f} {F['overpdh'][d, j]:+.1f} {F['to1_20'][d, j]:.1f} {F['cpos'][d, j]:.2f}", flush=True)
    b = pool_book2(D, F, H, S)
    ok, bad = shadow(D, b)
    for n in (5, 10, 20):
        rate = roll_sum(ok, n) / np.maximum(roll_sum(ok, n) + roll_sum(bad, n), 1)
        rate = np.concatenate([[np.nan], rate[:-1]])
        by = {}
        for i, x in enumerate(D.days):
            if '2024-01-02' <= x:
                by.setdefault(x[:7], []).append(rate[i])
        if n == 10:
            print('shadow rate (10 days) by month', ' '.join(f"{k[2:]}:{np.nanmean(v):.2f}" for k, v in by.items()), flush=True)
        st, tr = D.base.run(D.A, e, panels.WINDOW, D.pool, f1_rules(D, 6, (1, 3)), placebo=0, audit=True)
        L = [t for t in tr if t['side'] > 0 and t['entry'] in D.di]
        x = np.array([rate[D.di[t['entry']]] for t in L])
        R = np.array([float(t.get('r') or 0) for t in L])
        W = np.array([t['pnl'] for t in L])
        P = np.array([t['entry'] > CUT for t in L])
        qs = np.nanpercentile(x, [25, 50, 75])
        row = []
        for p in (False, True):
            cells = []
            for lo, hi in ((-1, qs[0]), (qs[0], qs[1]), (qs[1], qs[2]), (qs[2], 2)):
                m = (x > lo) & (x <= hi) & (P == p)
                cells.append(f"{int(m.sum())}:{R[m].mean():+.2f}R win {np.mean(W[m] > 0):.2f}")
            row.append(' '.join(cells))
        print(f"window {n}: cuts {np.round(qs, 2)} 2024-25 {row[0]} || 2026 {row[1]}", flush=True)


def coil_book(D, F, top=3, min_gain=.8, min_cpos=.7, max_ext=3.0):
    """Names that sat still and started today: tight on the evening before, a strong close above yesterday's high today."""
    c, l, h = D.c, D.l, D.h
    V = D.U & (np.nan_to_num(lag(D.adr)) >= .04)
    parts = [pct(lag(-F['squeeze']), V), pct(lag(-F['range10']), V), pct(-F['w_wk_tight'], V), pct(lag(F['fast250']), V)]
    C = sum(np.nan_to_num(p - .5) for p in parts) / len(parts)
    go = V & (np.nan_to_num(F['gain']) >= min_gain) & (np.nan_to_num(F['cpos']) >= min_cpos) & (c > lag(h)) & (np.nan_to_num(F['ext21'], nan=99) <= max_ext)
    out = [[] for _ in range(len(c))]
    for d in range(2, len(c)):
        f = np.flatnonzero(go[d])
        if not len(f):
            continue
        for j in f[np.argsort(-C[d, f])[:top]]:
            cc = float(c[d, j])
            a = float(D.adr[d - 1, j])
            w = min(.05, a / 2)
            out[d].append(((1.5, -float(C[d, j])), int(j), 1, cc, float(min(max(float(l[d, j]), cc * (1 - w)), cc * .99)), 'coil'))
    return out, C, go


def coil_rules(D, n=3, adds=(1, 3), **kw):
    from dataclasses import replace
    ru = f1_rules(D, 6, adds, **kw)
    return replace(ru, management_by_kind={**ru.management_by_kind, 'coil': dict(add_levels=adds)}, max_new_by_kind={**ru.max_new_by_kind, 'coil': n})


def s41():
    D, F, M, shorts, replace = setup7()
    e, H, S = f1_entries(D, F, M)
    for top in (2, 3, 5):
        b, C, go = coil_book(D, F, top)
        got = lambda R: sum(any(x[1] == z[1] for z in b[x[0]]) for x in R)
        near = lambda R: sum(any(any(x[1] == z[1] for z in b[k]) for k in range(max(x[0] - 5, 0), min(x[0] + 6, len(b)))) for x in R)
        n = sum(len(x) for x in b) / (len(D.days) / 252)
        print(f"top {top}: {n:.0f} a year, same day his 77 {got(D.his)} big25 {got(D.big)}; within 5 days his 77 {near(D.his)} big25 {near(D.big)}; 2025 big {near([x for x in D.big if x[4][:4] == '2025'])}/{sum(x[4][:4] == '2025' for x in D.big)}", flush=True)
    res = {}
    def run(k, top, mult, **kw):
        b, _, _ = coil_book(D, F, top)
        res[k] = account(D, merge(e, sized(b, mult)), coil_rules(D, top, **kw), k)
        RV.write('strong_s41.json', res)
    run('K1', 2, .5)
    run('K2', 3, .5)
    run('K3', 2, 1.0)
    run('K4', 3, .5, risk_scale='idx_both')
    res['K5'] = account(D, e, f1_rules(D, 6, (1, 3), risk_scale='idx_both'), 'K5')
    RV.write('strong_s41.json', res)


def s42():
    D, F, M, shorts, replace = setup7()
    b, C, go = coil_book(D, F, 999)
    print('ignition candidates a day median', int(np.median(go[D.window].sum(1))), 'his days', int(np.median([go[x[0]].sum() for x in D.his])), flush=True)
    for tag, R in (('his', D.his), ('big', D.big), ('big25', [x for x in D.big if x[4][:4] == '2025'])):
        print(tag, 'in candidates same day', sum(go[x[0], x[1]] for x in R), 'of', len(R), [x[2] for x in R if not go[x[0], x[1]]][:14], flush=True)
    # ignition on any of the 3 days around his buy, for the record
    V = D.U & (np.nan_to_num(lag(D.adr)) >= .04)
    P = lambda k, s=1, back=1: np.nan_to_num(pct(s * (lag(F[k], back) if back else F[k]), V) - .5)
    base = P('act20') + P('stay250') + P('fast250')
    sc = dict(R1=P('act20'), R2=base, R3=base + P('squeeze', -1) + P('range10', -1), R4=base + P('squeeze', -1) + P('w_wk_tight', -1, 0), R5=base + P('act1', 1, 0))
    res = {}
    for k, s_ in sc.items():
        row = {}
        for tag, R in (('his', D.his), ('big', D.big), ('big25', [x for x in D.big if x[4][:4] == '2025'])):
            cells = []
            for n in (1, 2, 3, 5):
                hit = 0
                for x in R:
                    d, j = x[0], x[1]
                    if go[d, j] and (s_[d][go[d]] > s_[d, j]).sum() < n:
                        hit += 1
                cells.append(hit)
            row[tag] = cells
        print(k, row, flush=True)
        res[k] = row
    RV.write('strong_s42.json', res)


def ignite_book(D, F, M, H, top=2, exclude=True, min_gain=.8, min_cpos=.7, max_ext=3.0):
    """Active names that were tight and started today, ranked activity first, the strong set left to its own entries."""
    c, l, h = D.c, D.l, D.h
    P = lambda x: np.nan_to_num(pct(x, M) - .5)
    R4 = P(lag(F['act20'])) + P(lag(F['stay250'])) + P(lag(F['fast250'])) + P(lag(-F['squeeze'])) + P(-F['w_wk_tight'])
    go = M & (np.nan_to_num(F['gain']) >= min_gain) & (np.nan_to_num(F['cpos']) >= min_cpos) & (c > lag(h)) & (np.nan_to_num(F['ext21'], nan=99) <= max_ext)
    if exclude:
        go = go & ~H
    out = [[] for _ in range(len(c))]
    for d in range(2, len(c)):
        f = np.flatnonzero(go[d])
        if not len(f):
            continue
        for j in f[np.argsort(-R4[d, f])[:top]]:
            cc = float(c[d, j])
            a = float(D.adr[d - 1, j])
            w = min(.05, a / 2) if np.isfinite(a) else .05
            out[d].append(((1.5, -float(R4[d, j])), int(j), 1, cc, float(min(max(float(l[d, j]), cc * (1 - w)), cc * .99)), 'coil'))
    return out


def print_2025(D, ent, ru, name):
    from . import panels
    st, tr = D.base.run(D.A, ent, panels.WINDOW, D.pool, ru, placebo=0, audit=True)
    c = np.asarray(st.get('_curve'), dtype=float)
    ds = [x for x in D.days if panels.WINDOW[0] <= x <= panels.WINDOW[1]][-len(c):]
    out = []
    for m in range(1, 13):
        ix = [i for i, x in enumerate(ds) if x[:7] == f'2025-{m:02d}']
        out.append(f"{m}:{c[ix[-1]] / c[ix[0] - 1] - 1:+.0%}")
    print(f"  {name} 2025 by month", ' '.join(out), flush=True)


def s43():
    D, F, M, shorts, replace = setup7()
    e, H, S = f1_entries(D, F, M)
    res = {}
    for k, (top, mult, ex) in dict(B1=(1, .5, True), B2=(2, .5, True), B3=(2, 1.0, True), B4=(1, 1.0, True), B5=(2, .5, False)).items():
        b = ignite_book(D, F, M, H, top, ex)
        n = sum(len(x) for x in b) / (len(D.days) / 252)
        near = lambda R: sum(any(any(x[1] == z[1] for z in b[q]) for q in range(max(x[0] - 1, 0), min(x[0] + 6, len(b)))) for x in R)
        print(f"{k} signals {n:.0f} a year; in the 6 days from his buy: his {near(D.his)} big {near(D.big)} big2025 {near([x for x in D.big if x[4][:4] == '2025'])}", flush=True)
        ent = merge(e, sized(b, mult))
        ru = coil_rules(D, top)
        res[k] = account(D, ent, ru, k)
        print_2025(D, ent, ru, k)
        RV.write('strong_s43.json', res)


def s45():
    """Which trades cost the bad months of 2025, in percent of equity at the exit, and were they new or old positions."""
    from . import panels
    D, F, M, shorts, replace = setup7()
    e, H, S = f1_entries(D, F, M)
    st, tr = D.base.run(D.A, e, panels.WINDOW, D.pool, f1_rules(D, 6, (1, 3)), placebo=0, audit=True)
    c = np.asarray(st.get('_curve'), dtype=float)
    ds = [x for x in D.days if panels.WINDOW[0] <= x <= panels.WINDOW[1]][-len(c):]
    eq = {x: c[i] for i, x in enumerate(ds)}
    for lab, a, z in (('Jan', '2025-01-01', '2025-01-31'), ('Feb', '2025-02-01', '2025-02-28'), ('Nov', '2025-11-01', '2025-11-30')):
        ix = [i for i, x in enumerate(ds) if a <= x <= z]
        e0 = c[ix[0] - 1]
        L = [t for t in tr if a <= t['exit'] <= z]
        rows = [(t['pnl'] / e0, t) for t in L]
        tot = sum(p for p, _ in rows)
        groups = {}
        for p, t in rows:
            new = t['entry'] >= a
            k = (('new' if new else 'old'), ('L' if t['side'] > 0 else 'S'), t['kind'] if t['side'] > 0 else '', t['why'])
            g = groups.setdefault(k, [0, 0.0])
            g[0] += 1
            g[1] += p
        print(f"{lab}: equity {c[ix[-1]] / e0 - 1:+.0%}, closed pnl {tot:+.0%} of equity, still open at month end change not shown", flush=True)
        for k, g in sorted(groups.items(), key=lambda kv: kv[1][1])[:9]:
            print(f"   {k} n {g[0]:3d} {g[1]:+.1%}", flush=True)
        for p, t in sorted(rows, key=lambda r: r[0])[:9]:
            print(f"     {t['code'][3:]:5s} {t['entry']}>{t['exit']} {t['kind']:4s} {t['why']:8s} days {t['days']:3d} ret {t['ret']:+.0%} invested {t['ret_invested']:+.0%} R {float(t.get('r') or 0):+.1f} {p:+.1%}", flush=True)


def e2_with(D, list_extra=None, **kw):
    from dataclasses import replace
    ru = f1_rules(D, 6, (1, 3), **kw)
    if list_extra:
        mg = dict(ru.management_by_kind)
        mg['list'] = {**mg.get('list', {}), **list_extra}
        ru = replace(ru, management_by_kind=mg)
    return ru


def s46():
    D, F, M, shorts, replace = setup7()
    t915 = dict(trims=(3, 5), trim_frac=.15)
    conf = dict(Y1=lambda: e2_with(D, dict(trail='e9')), Y2=lambda: e2_with(D, t915), Y3=lambda: e2_with(D, trail_alt='e9', trail_alt_dd=.10), Y4=lambda: e2_with(D, trail_alt='e9', trail_alt_dd=.15), Y5=lambda: e2_with(D, dict(trail='e9'), stop_ema_buffer=.03))
    neighbours(D, F, M, conf, 'strong_s46.json')


def tiered(D, F, H, S, book, rank=True, cluster=True, base=.5):
    """Trial risk by the place in the strong set and by how many of the set started today; both known at the close."""
    strong = H & (np.nan_to_num(F['gain']) >= 1) & (np.nan_to_num(F['cpos']) >= .7)
    n = strong.sum(1)
    out = []
    for d, lst in enumerate(book):
        row = []
        day = float(np.clip(n[d] / 3, .5, 2)) if cluster else 1.0
        set_names = np.flatnonzero(H[d])
        order = None
        if rank and len(set_names):
            v = np.nan_to_num(S[d, set_names], nan=-9)
            o = np.argsort(-v)
            order = {int(set_names[k]): i for i, k in enumerate(o)}
        for e in lst:
            m = base
            if order is not None:
                i = order.get(int(e[1]), len(set_names))
                m = 1.0 if i < 4 else (.25 if i >= 2 * len(set_names) / 3 else .5)
            row.append(((2.0,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:6]) + ((e[6] if len(e) > 6 else None), None, None, float(m * day)))
        out.append(row)
    return out


def s47():
    D, F, M, shorts, replace = setup7()
    res = {}
    for name, (rk, cl) in dict(C1=(True, False), C2=(False, True), C3=(True, True)).items():
        rows = []
        for k, (K, o, core, sat) in NEIGH.items():
            S = name_score(D, F, M, HOLD['H3'])
            H = hold_sim(S, K, o or 3 * K)
            ent = merge(tilt_core(D, H, core), tiered(D, F, H, S, pool_book2(D, F, H, S), rk, cl, sat))
            r = account(D, ent, f1_rules(D, 6, (1, 3)), f'{name}_{k}')
            y = r['by_year']
            rows.append(dict(p=k, y24=y['2024'], y25=y['2025'], y26=y['2026'], mult=(1 + y['2024']) * (1 + y['2025']) * (1 + y['2026']), dd=r['maxdd'], board=r['board'], run=r['run'], stage=r['stage1'] + r['stage2'], strict=r['strict'] + r['strict26'], held=r['held1'] + r['held2'], big=r['big_profit'], his=r['his_profit']))
        res[name] = rows
        m = lambda q, f=np.median: float(f([x[q] for x in rows]))
        print(f"== {name} mult median {m('mult'):.1f} min {m('mult', np.min):.1f} max {m('mult', np.max):.1f} | y {m('y24'):+.2f}/{m('y25'):+.2f}/{m('y26'):+.2f} worst {m('y24', np.min):+.2f}/{m('y25', np.min):+.2f}/{m('y26', np.min):+.2f} dd {m('dd'):.2f} board {m('board'):.0f} run {m('run'):.2f} stage {m('stage'):.0f} strict {m('strict'):.0f} held {m('held'):.0f} bigprofit {m('big'):.2f} his {m('his'):.2f}", flush=True)
        RV.write('strong_s47.json', res)


def winners(D, a, z, n, floor=5e7):
    """The n largest gainers between two dates among names that traded at least floor a day at some point: hindsight."""
    ix = [i for i, x in enumerate(D.days) if a <= x <= z]
    c = D.c[ix]
    first = np.array([c[np.flatnonzero(np.isfinite(c[:, j]))[0], j] if np.isfinite(c[:, j]).any() else np.nan for j in range(c.shape[1])])
    last = np.array([c[np.flatnonzero(np.isfinite(c[:, j]))[-1], j] if np.isfinite(c[:, j]).any() else np.nan for j in range(c.shape[1])])
    live = np.nan_to_num(np.nanmax(D.to20[ix], axis=0)) >= floor
    g = np.where(live, last / first - 1, np.nan)
    o = np.argsort(-np.nan_to_num(g, nan=-9))[:n]
    return o, g


def s48():
    from . import panels
    D, F, M, shorts, replace = setup7()
    code = [str(x)[3:] for x in D.A['codes']]
    idx = {c: i for i, c in enumerate(code)}
    y25 = [i for i, x in enumerate(D.days) if x[:4] == '2025']
    # 1. data
    print('names with a bar: 2024-12-31', int(np.isfinite(D.c[D.di['2024-12-31']]).sum()), '2025-12-31', int(np.isfinite(D.c[D.di['2025-12-31']]).sum()), flush=True)
    miss = [t for t in ('CRCL', 'CRWV', 'FIG', 'CHYM', 'BULL', 'KLAR', 'SNDK', 'NBIS', 'OPEN', 'MP', 'UUUU', 'IREN', 'CIFR', 'APLD', 'BMNR', 'SBET', 'LITE', 'BE', 'ASTS', 'RKLB') if t not in idx]
    print('not in the panel', miss, flush=True)
    for t in ('RGTI', 'QBTS', 'IONQ', 'ASTS', 'OKLO', 'HOOD', 'PLTR', 'AMD', 'SNDK', 'CRCL'):
        if t in idx:
            j = idx[t]
            x = D.c[y25, j]
            first = next((D.days[i] for i in range(len(D.days)) if np.isfinite(D.c[i, j])), None)
            print(f"  {t:5s} first bar {first} holes in 2025 {int(np.isnan(x).sum())} active-list days {int(M[y25, j].sum())}/{len(y25)} in-set days {0}", flush=True)
    holes = np.isnan(D.c[y25]).sum(0)
    act = np.nanmax(D.to20[y25], axis=0) >= 5e7
    print('active names with any hole inside their life in 2025', int(((holes > 0) & (holes < len(y25)) & act & np.isfinite(D.c[y25[-1]])).sum()), 'of', int((act & np.isfinite(D.c[y25[-1]])).sum()), flush=True)
    # 2. exposure
    e, H, S = f1_entries(D, F, M)
    ru = f1_rules(D, 6, (1, 3))
    tk = {}
    st, tr = D.base.run(D.A, e, panels.WINDOW, D.pool, ru, placebo=0, audit=True, track=tk)
    print('track keys', list(tk.keys()), flush=True)
    ds = [x for x in D.days if panels.WINDOW[0] <= x <= panels.WINDOW[1]]
    g = np.array(tk.get('gross', []), dtype=float)[-len(ds):]
    op = np.array(tk.get('open', []), dtype=float)[-len(ds):]
    for y in ('2024', '2025', '2026'):
        m = np.array([x[:4] == y for x in ds])
        print(f"  {y}: mean gross {g[m].mean():.2f} days at cap (>=2.6) {np.mean(g[m] >= 2.6):.0%} mean open {op[m].mean():.1f}", flush=True)
    print('  2025 month gross', ' '.join(f"{k}:{g[[x[:7] == f'2025-{k:02d}' for x in ds]].mean():.1f}" for k in range(1, 13)), flush=True)
    # 3. ceiling: hindsight names as the strong set, everything else E2
    res = {}
    def ceiling(name, Hx):
        ent = merge(tilt_core(D, Hx, .5), sized(pool_book2(D, F, Hx, S), .5))
        res[name] = account(D, ent, ru, name)
    for n in (30, 100):
        Hx = np.zeros(D.c.shape, bool)
        for a, z in (('2024-01-01', '2024-12-31'), ('2025-01-01', '2025-12-31'), ('2026-01-01', '2026-12-31')):
            o, _ = winners(D, a, z, n)
            for i, x in enumerate(D.days):
                if a <= x <= z:
                    Hx[i, o] = True
        ceiling(f'YEAR{n}', Hx)
    Hq = np.zeros(D.c.shape, bool)
    for y in ('2024', '2025', '2026'):
        for a, z in (('01-01', '03-31'), ('04-01', '06-30'), ('07-01', '09-30'), ('10-01', '12-31')):
            aa, zz = f'{y}-{a}', f'{y}-{z}'
            if aa > D.days[-1]:
                continue
            o, _ = winners(D, aa, zz, 30)
            for i, x in enumerate(D.days):
                if aa <= x <= zz:
                    Hq[i, o] = True
    ceiling('QTR30', Hq)
    Hh = np.zeros(D.c.shape, bool)
    for j in {x[1] for x in D.his}:
        Hh[:, j] = True
    ceiling('HIS47', Hh)
    # 4. capture of the biggest winners of 2025
    o, g25 = winners(D, '2025-01-01', '2025-12-31', 30)
    gross = sum(t['pnl'] for t in tr if t['side'] > 0 and t['pnl'] > 0)
    print('top 2025 gainers: gain, days in set, trades, pnl share of gross, best ret', flush=True)
    for j in o:
        L = [t for t in tr if t['side'] > 0 and idx[str(t['code'])[3:]] == j and '2025-01-01' <= t['entry'] <= '2025-12-31']
        print(f"  {code[j]:6s} {g25[j]:+6.0%} set {int(H[y25, j].sum()):3d} active {int(M[y25, j].sum()):3d} trades {len(L):2d} pnl {sum(t['pnl'] for t in L) / gross:+.1%} best {max([t['ret'] for t in L], default=0):+.0%}", flush=True)
    RV.write('strong_s48.json', res)


QUARTERS = tuple((f'{y}-{a}', f'{y}-{z}') for y in ('2024', '2025', '2026') for a, z in (('01-01', '03-31'), ('04-01', '06-30'), ('07-01', '09-30'), ('10-01', '12-31')))


def reach(D, M, n=30):
    """Each quarter's largest gainers among the names on the active list when the quarter began: hindsight."""
    out = []
    for a, z in QUARTERS:
        ix = [i for i, x in enumerate(D.days) if a <= x <= z]
        if not ix:
            continue
        cand = np.flatnonzero(M[ix[0]])
        if not len(cand):
            continue
        with np.errstate(all='ignore'):
            g = D.c[ix[-1], cand] / D.c[ix[0], cand] - 1
        out.append((ix, cand[np.argsort(-np.nan_to_num(g, nan=-9))[:n]]))
    return out


def s49():
    D, F, M, shorts, replace = setup7()
    e, H, S = f1_entries(D, F, M)
    ru = f1_rules(D, 6, (1, 3))
    Q = reach(D, M)
    res = {}
    run = lambda k, Hx: res.__setitem__(k, account(D, merge(tilt_core(D, Hx, .5), sized(pool_book2(D, F, Hx, S), .5)), ru, k))
    Hx = np.zeros(D.c.shape, bool)
    for ix, names in Q:
        Hx[np.ix_(ix, names)] = True
    print('reachable winners set size', round(float(Hx[D.window].sum(1).mean()), 1), flush=True)
    run('REACH30', Hx)
    for p in (.1, .25, .5):
        rng = np.random.default_rng(3)
        Hp = H.copy()
        for ix, names in Q:
            k = max(1, int(round(p * len(names))))
            Hp[np.ix_(ix, rng.choice(names, k, replace=False))] = True
        run(f'MIX{int(p * 100)}', Hp)
    RV.write('strong_s49.json', res)


def forward_label(D, F, M, built, horizon=60, top=.1, ridge=3e3, linear=False):
    """Cross-fitted score for 'among the top tenth of the active list over the next horizon days'; no ledger."""
    keys, days, idx, X = built
    Xu = X[:, :len(keys)] if linear else X
    day_arr = np.concatenate([[d] * len(ix) for d, ix in zip(days, idx)])
    jpos = np.concatenate(idx)
    y = np.zeros(len(jpos), dtype=np.float32)
    known = np.zeros(len(jpos), bool)
    pos = 0
    with np.errstate(all='ignore'):
        for d, ix in zip(days, idx):
            if d + horizon < len(D.c):
                g = D.c[d + horizon, ix] / D.c[d, ix] - 1
                ok = np.isfinite(g)
                if ok.sum() > 50:
                    cut = np.nanquantile(g[ok], 1 - top)
                    y[pos:pos + len(ix)] = (np.nan_to_num(g, nan=-9) >= cut)
                    known[pos:pos + len(ix)] = True
            pos += len(ix)
    S = np.full(D.c.shape, np.nan, dtype=np.float32)
    ds = np.array(D.days)
    W = []
    for a, z in FOLDS:
        inside = np.array([a <= ds[d] <= z for d in day_arr])
        fd = np.flatnonzero([a <= x <= z for x in D.days])
        if not inside.any():
            continue
        tr = known & ((day_arr < fd[0] - horizon) | (day_arr > fd[-1] + horizon))
        w, b = fit_logit(Xu[tr], y[tr], ridge)
        W.append(w)
        S[day_arr[inside], jpos[inside]] = Xu[inside] @ w
    for d in range(1, len(S)):
        if not np.isfinite(S[d]).any():
            S[d] = np.where(M[d], S[d - 1], np.nan)
    return S, np.mean(W, axis=0)


def s50():
    D, F, M, shorts, replace = setup7()
    F.pop('nsq', None), F.pop('nr10', None)
    built = design(D, F, M)
    keys = built[0]
    e, H0, S0 = f1_entries(D, F, M)
    ru = f1_rules(D, 6, (1, 3))
    with np.errstate(all='ignore'):
        f60 = np.vstack([D.c[60:] / D.c[:-60] - 1, np.full((60, D.c.shape[1]), np.nan, dtype=np.float32)])
    def quality(S, name):
        out = {}
        for y in ('2024', '2025', '2026'):
            ic, top, base = [], [], []
            for d in D.window[::3]:
                if D.days[d][:4] != y or d + 60 >= len(D.c):
                    continue
                n = np.flatnonzero(M[d] & np.isfinite(S[d]) & np.isfinite(f60[d]))
                if len(n) < 50:
                    continue
                ic.append(float(np.corrcoef(rank_row(S[d, n]), rank_row(f60[d, n]))[0, 1]))
                t = n[np.argsort(-S[d, n])[:12]]
                cut = np.nanquantile(f60[d, n], .9)
                top.append(float(np.mean(f60[d, t] >= cut)))
                base.append(float(np.nanmedian(f60[d, t]) - np.nanmedian(f60[d, n])))
            out[y] = (round(float(np.mean(ic)), 3), round(float(np.mean(top)), 3), round(float(np.mean(base)), 3))
        print(f"{name}: year (IC, share of top 12 in the best tenth, median excess 60d) {out}", flush=True)
    quality(S0, 'H3')
    res = {}
    for name, ridge, lin in (('F3k', 3e3, False), ('L3k', 3e3, True), ('L300', 3e2, True)):
        S, w = forward_label(D, F, M, built, ridge=ridge, linear=lin)
        np.save(f'/tmp/msum/s50_{name}.npy', S)
        print(name, 'top weights', [(k, round(float(a), 2)) for k, a in sorted(zip(keys, w[:len(keys)]), key=lambda r: -abs(r[1]))[:10]], flush=True)
        quality(S, name)
        H = hold_sim(S, 12, 36)
        res[name] = account(D, merge(tilt_core(D, H, .5), sized(pool_book2(D, F, H, S), .5)), ru, name)
        RV.write('strong_s50.json', res)


def s51():
    D, F, M, shorts, replace = setup7()
    e, H, S = f1_entries(D, F, M)
    Q = reach(D, M)
    W = np.zeros(D.c.shape, bool)
    for ix, names in Q:
        W[np.ix_(ix, names)] = True
    y = lambda x: x[:4]
    for tag, f in (('2024', lambda s: s[:4] == '2024'), ('2025', lambda s: s[:4] == '2025'), ('2026', lambda s: s[:4] == '2026')):
        R = [x for x in D.his if f(x[4])]
        d = [i for i, x in enumerate(D.days) if f(x) and i in set(D.window)]
        his = sum(W[x[0], x[1]] for x in R)
        hs = float(np.mean([(W[i] & H[i]).sum() / max(H[i].sum(), 1) for i in d]))
        ms = float(np.mean([(W[i] & M[i]).sum() / max(M[i].sum(), 1) for i in d]))
        cov = float(np.mean([(W[i] & H[i]).sum() / max(W[i].sum(), 1) for i in d]))
        print(f"{tag}: his entries in the quarter's top 30 of the active list {his}/{len(R)} = {his / max(len(R), 1):.0%}; strong set precision {hs:.0%}, it covers {cov:.0%} of the 30; active list base {ms:.0%}", flush=True)


def s52():
    """Same winners of the quarter: how much of the quarter's rise was still ahead when he bought and when we did."""
    from . import panels
    D, F, M, shorts, replace = setup7()
    e, H, S = f1_entries(D, F, M)
    st, tr = D.base.run(D.A, e, panels.WINDOW, D.pool, f1_rules(D, 6, (1, 3)), placebo=0, audit=True)
    idx = {str(x): i for i, x in enumerate(D.A['codes'])}
    Q = reach(D, M)
    lon = [(D.di[t['entry']], idx[str(t['code'])], t['kind']) for t in tr if t['side'] > 0 and t['entry'] in D.di]
    rows = {'his': [], 'set': [], 'buy': []}
    for ix, names in Q:
        a, z = ix[0], ix[-1]
        y = D.days[a][:4]
        for j in names:
            j = int(j)
            total = float(D.c[z, j] / D.c[a, j] - 1)
            if not np.isfinite(total) or total <= .2:
                continue
            left = lambda d: float((D.c[z, j] / D.c[d, j] - 1) / total)
            age = lambda d: (d - a) / max(z - a, 1)
            his = [x[0] for x in D.his if x[1] == j and a <= x[0] <= z]
            if his:
                rows['his'].append((y, left(min(his)), age(min(his)), total))
            s_ = np.flatnonzero(H[a:z + 1, j])
            if len(s_):
                rows['set'].append((y, left(a + int(s_[0])), age(a + int(s_[0])), total))
            b = [d for d, k, _ in lon if k == j and a <= d <= z]
            if b:
                rows['buy'].append((y, left(min(b)), age(min(b)), total))
    for k, v in rows.items():
        for y in ('2024', '2025', '2026', 'all'):
            r = [x for x in v if y == 'all' or x[0] == y]
            if r:
                print(f"{k:4s} {y}: names {len(r):3d} rise still ahead at first buy, median {np.median([x[1] for x in r]):.0%}; share of the quarter gone {np.median([x[2] for x in r]):.0%}; quarter gain {np.median([x[3] for x in r]):+.0%}", flush=True)


def first_book(D, F, H, S, max_ext=None):
    """A trial at the close of the day a name joins the strong set, without waiting for a pullback."""
    c, l = D.c, D.l
    out = [[] for _ in range(len(c))]
    new = H & ~lag(H.astype(np.float32)).astype(bool)
    ext = np.nan_to_num(F['ext21'], nan=99)
    for d in range(1, len(c)):
        m = new[d] & np.isfinite(c[d]) & np.isfinite(l[d])
        if max_ext is not None:
            m = m & (ext[d] <= max_ext)
        for j in np.flatnonzero(m):
            cc = float(c[d, j])
            a = D.adr[d - 1, j]
            w = min(.05, float(a) / 2) if np.isfinite(a) else .05
            out[d].append(((.5, -float(np.nan_to_num(S[d, j]))), int(j), 1, cc, float(min(max(float(l[d, j]), cc * (1 - w)), cc * .99)), 'list'))
    return out


def s53():
    D, F, M, shorts, replace = setup7()
    e, H, S = f1_entries(D, F, M)
    core = tilt_core(D, H, .5)
    ru = f1_rules(D, 6, (1, 3))
    b3, b5, b8 = (pool_book2(D, F, H, S, True, x) for x in (3.0, 5.0, 8.0))
    f0, f3 = first_book(D, F, H, S), first_book(D, F, H, S, 3.0)
    plan = dict(T1=[a + b for a, b in zip(f0, b3)], T2=[a + b for a, b in zip(f3, b3)], T3=b5, T4=[a + b for a, b in zip(f0, b5)], T5=b8)
    res = {}
    for k, book in plan.items():
        ent = merge(core, sized(book, .5))
        res[k] = account(D, ent, ru, k)
        print_2025(D, ent, ru, k)
        RV.write('strong_s53.json', res)


def s54():
    D, F, M, shorts, replace = setup7()
    ru = f1_rules(D, 6, (1, 3))
    rows = []
    for k, (K, o, core, sat) in NEIGH.items():
        S = name_score(D, F, M, HOLD['H3'])
        H = hold_sim(S, K, o or 3 * K)
        ent = merge(tilt_core(D, H, core), sized(pool_book2(D, F, H, S, True, 8.0), sat))
        r = account(D, ent, ru, f'T5_{k}')
        y = r['by_year']
        rows.append(dict(p=k, y24=y['2024'], y25=y['2025'], y26=y['2026'], mult=(1 + y['2024']) * (1 + y['2025']) * (1 + y['2026']), dd=r['maxdd'], board=r['board'], run=r['run'], stage=r['stage1'] + r['stage2'], strict=r['strict'] + r['strict26'], held=r['held1'] + r['held2']))
    m = lambda q, f=np.median: float(f([x[q] for x in rows]))
    print(f"== T5 mult median {m('mult'):.1f} min {m('mult', np.min):.1f} max {m('mult', np.max):.1f} | y {m('y24'):+.2f}/{m('y25'):+.2f}/{m('y26'):+.2f} worst {m('y24', np.min):+.2f}/{m('y25', np.min):+.2f}/{m('y26', np.min):+.2f} dd {m('dd'):.2f} board {m('board'):.0f} (min {m('board', np.min):.0f}) run {m('run'):.2f} stage {m('stage'):.0f} strict {m('strict'):.0f} held {m('held'):.0f}", flush=True)
    RV.write('strong_s54.json', rows)


def risk_audit(D, st, tr, name):
    """Equity risked at entry on the trades that became winners and on the losers, by year."""
    c = np.asarray(st.get('_curve'), dtype=float)
    from . import panels
    ds = [x for x in D.days if panels.WINDOW[0] <= x <= panels.WINDOW[1]][-len(c):]
    eq = dict(zip(ds, c))
    for y in ('2024', '2025', '2026'):
        L = [t for t in tr if t['side'] > 0 and t['entry'][:4] == y and t['entry'] in eq and abs(float(t.get('r') or 0)) > .05]
        rk = np.array([t['pnl'] / float(t['r']) / eq[t['entry']] for t in L])
        R = np.array([float(t['r']) for t in L])
        big = R >= 5
        los = R < 0
        print(f"  {name} {y}: n {len(L)} sum R {R.sum():+.0f} | risk per R of equity: all {np.median(rk) * 100:.2f}% winners>=5R {np.median(rk[big]) * 100:.2f}% losers {np.median(rk[los]) * 100:.2f}% | sum R x risk {np.sum(R * rk) * 100:+.0f}%", flush=True)


def s55():
    from . import panels
    D, F, M, shorts, replace = setup7()
    S = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(S, 12, 36)
    book = pool_book2(D, F, H, S, True, 8.0)
    core = tilt_core(D, H, .5)
    base = lambda **kw: f1_rules(D, 6, (1, 3), **kw)
    e0 = merge(core, sized(book, .5))
    free, *_ = D.W.build(D.A, {**D.cfg, 'filter': 'NONE'})
    st, tr = D.base.run(D.A, e0, panels.WINDOW, D.pool, base(), placebo=0, audit=True)
    risk_audit(D, st, tr, 'T5')
    res = dict(A=account(D, e0, base(), 'A'))
    res['B'] = account(D, e0, base(feedback=0), 'B')
    res['C'] = account(D, e0, base(risk_scale=''), 'C')
    res['D'] = account(D, merge(tilt_core(replace_reg(D, free), H, .5), sized(book, .5)), base(), 'D')
    res['E'] = account(D, merge(D.reg, sized(book, .5)), base(), 'E')
    res['F'] = account(D, e0, replace(base(), max_position=.5), 'F')
    res['G'] = account(D, e0, base(max_gross=4.0), 'G')
    res['H'] = account(D, merge(core, sized(book, 1.0)), base(), 'H')
    res['I'] = account(D, e0, base(trims=()), 'I')
    res['J'] = account(D, merge(core, sized(pool_book2(D, F, H, S, True, 8.0, None, False), .5)), base(), 'J')
    nosh = [[x for x in r if x[2] > 0] for r in e0]
    res['K'] = account(D, nosh, base(), 'K')
    res['L'] = account(D, e0, base(margin_rate=0.0), 'L')
    res['M'] = account(D, e0, base(nft_days=2), 'M')
    res['N'] = account(D, e0, base(nft_days=3), 'N')
    RV.write('strong_s55.json', res)


def replace_reg(D, reg):
    from types import SimpleNamespace
    return SimpleNamespace(reg=reg)


def s56():
    from . import panels
    D, F, M, shorts, replace = setup7()
    S = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(S, 12, 36)
    H8 = hold_sim(S, 8, 24)
    wide = pool_book2(D, F, H, S, True, 8.0, None, False)
    wide8 = pool_book2(D, F, H8, S, True, 8.0, None, False)
    r0 = lambda **kw: f1_rules(D, 6, (1, 3), **kw)
    plan = dict(U1=(wide, .5, r0()), U2=(wide, .5, r0(feedback=0)), U3=(wide, 1.0, r0(feedback=0)), U4=(wide8, 1.0, r0(feedback=0)), U5=(wide, 1.0, r0(feedback=0, max_gross=3.5)))
    res = {}
    for k, (book, mult, ru) in plan.items():
        ent = merge(D.reg, sized(book, mult))
        res[k] = account(D, ent, ru, k)
        st, tr = D.base.run(D.A, ent, panels.WINDOW, D.pool, ru, placebo=0, audit=True)
        risk_audit(D, st, tr, k)
        print_2025(D, ent, ru, k)
        RV.write('strong_s56.json', res)


def s57():
    D, F, M, shorts, replace = setup7()
    S = name_score(D, F, M, HOLD['H3'])
    r1, r4 = f1_rules(D, 6, (1, 3)), f1_rules(D, 6, (1, 3), feedback=0)
    conf = dict(U1=(r1, 12, .5, ((12, 3, 1), (10, 3, 1), (15, 3, 1), (12, 2, 1), (12, 4, 1), (12, 3, .8), (12, 3, 1.2))),
                U4=(r4, 8, 1.0, ((8, 3, 1), (6, 3, 1), (10, 3, 1), (8, 2, 1), (8, 4, 1), (8, 3, .8), (8, 3, 1.2))))
    res = {}
    for name, (ru, _, base, grid) in conf.items():
        rows = []
        for K, o, m in grid:
            H = hold_sim(S, K, o * K)
            r = account(D, merge(D.reg, sized(pool_book2(D, F, H, S, True, 8.0, None, False), base * m)), ru, f'{name}_{K}_{o}_{m}')
            y = r['by_year']
            rows.append(dict(y24=y['2024'], y25=y['2025'], y26=y['2026'], mult=(1 + y['2024']) * (1 + y['2025']) * (1 + y['2026']), dd=r['maxdd'], board=r['board'], run=r['run'], stage=r['stage1'] + r['stage2'], held=r['held1'] + r['held2'], strict=r['strict'] + r['strict26']))
        res[name] = rows
        q = lambda k, f=np.median: float(f([x[k] for x in rows]))
        print(f"== {name} mult median {q('mult'):.1f} min {q('mult', np.min):.1f} max {q('mult', np.max):.1f} | y {q('y24'):+.2f}/{q('y25'):+.2f}/{q('y26'):+.2f} worst {q('y24', np.min):+.2f}/{q('y25', np.min):+.2f}/{q('y26', np.min):+.2f} dd {q('dd'):.2f} board {q('board'):.0f} run {q('run'):.2f} stage {q('stage'):.0f} held {q('held'):.0f} strict {q('strict'):.0f}", flush=True)
        RV.write('strong_s57.json', res)


def u1_entries(D, F, H, S):
    return merge(D.reg, sized(pool_book2(D, F, H, S, True, 8.0, None, False), .5))


def s58():
    from . import panels
    D, F, M, shorts, replace = setup7()
    S = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(S, 12, 36)
    ru = f1_rules(D, 6, (1, 3))
    e = u1_entries(D, F, H, S)
    res = dict(U1=account(D, e, ru, 'U1'), draws=[])
    print_2025(D, e, ru, 'U1')
    st, tr = D.base.run(D.A, e, panels.WINDOW, D.pool, ru, placebo=0, audit=True)
    lon = [t for t in tr if t['side'] > 0]
    gross = sum(t['pnl'] for t in lon if t['pnl'] > 0)
    for t in sorted(lon, key=lambda t: -t['pnl'])[:8]:
        print(f"  {t['code'][3:]:5s} {t['entry']} -> {t['exit']} {t['kind']} days {t['days']:3d} ret {t['ret']:+.0%} share {t['pnl'] / gross:.1%} why {t['why']}", flush=True)
    rng = np.random.default_rng(7)
    for i in range(10):
        R = np.where(M, rng.random(M.shape, dtype=np.float32), np.nan)
        keep = np.full(R.shape, .5, dtype=np.float32)
        for d in range(1, len(R)):
            keep[d] = .97 * keep[d - 1] + .03 * np.nan_to_num(R[d], nan=.5)
        keep = np.where(M, keep, np.nan)
        Hr = hold_sim(keep, 12, 36)
        r = account(D, u1_entries(D, F, Hr, keep), ru, f'rand{i}')
        res['draws'].append({k: r[k] for k in ('by_year', 'maxdd', 'board', 'run', 'held1', 'held2', 'stage1', 'stage2', 'strict', 'strict26')})
        RV.write('strong_s58.json', res)
    res['placebo'] = account(D, e, ru, 'U1pl', placebo=30).get('placebo')
    RV.write('strong_s58.json', res)
    d = res['draws']
    med = lambda f: float(np.median([f(x) for x in d]))
    print(f"random median y {med(lambda x: x['by_year']['2024']):+.2f}/{med(lambda x: x['by_year']['2025']):+.2f}/{med(lambda x: x['by_year']['2026']):+.2f} dd {med(lambda x: x['maxdd']):.2f} board {med(lambda x: x['board']):.0f} stage {med(lambda x: x['stage1'] + x['stage2']):.0f} held {med(lambda x: x['held1'] + x['held2'])}", flush=True)
    print('placebo', res['placebo'], flush=True)


def nl_rules(D, N, adds=(), n=0, **kw):
    """No leverage: long book at most 100% of equity, at most N names, equal weight unless a smaller first size is asked for."""
    from dataclasses import replace
    mg = {k: dict(add_levels=adds) for k in ('list', 'n1', 'cand')} if adds else {}
    ru = replace(D.rules, max_gross=1.0, max_open=N, max_position=1.0 / N, risk=.05, risk_low=.05, risk_high=0.0, feedback=0, risk_scale='', margin_rate=0.0,
                 add_levels=(), add_r=0.0, management_by_kind=mg, max_new_by_kind={}, max_new_long=n or N, intraday_kinds=tuple(D.rules.intraday_kinds))
    return replace(ru, **kw)


def longs(book):
    return [[e for e in r if e[2] > 0] for r in book]


def s59():
    D, F, M, shorts, replace = setup7()
    S = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(S, 12, 36)
    sat = pool_book2(D, F, H, S, True, 8.0, None, False)
    plain = lambda book, pr: [[((pr,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:6]) for e in r] for r in book]
    reg = plain(longs(D.reg), 1.0)
    s2 = plain(sat, 2.0)
    res = {}
    for N in (4, 6, 8):
        for name, ent in (('REG', reg), ('SAT', s2), ('BOTH', merge(reg, s2))):
            k = f'{name}{N}'
            res[k] = account(D, ent, nl_rules(D, N), k)
            print_2025(D, ent, nl_rules(D, N), k)
            RV.write('strong_s59.json', res)


def candidates(D, F, M, max_ext=8.0):
    """Every buy point on the active list: day, name, fill at the close, stop at the day's low kept within 1% to 5%."""
    c, l, h = D.c, D.l, D.h
    tr = (F['lowe9'] <= .1) & (c > D.e9) | (c > lag(h)) & (F['cpos'] >= .5)
    ok = M & tr & (np.nan_to_num(F['ext21'], nan=99) <= max_ext) & np.isfinite(c) & np.isfinite(l)
    d, j = np.nonzero(ok)
    keep = (d >= D.window[0])
    d, j = d[keep], j[keep]
    fill = c[d, j].astype(float)
    stop = np.minimum(np.maximum(l[d, j].astype(float), fill * .95), fill * .99)
    return d, j, fill, stop


def walk(D, e21, d, j, fill, stop, maxd=120):
    """Close entry; out at the stop (or the open below it) or on a close under the 21 EMA.  Returns ret, days, and days to +30%."""
    o, h, l, c = D.o, D.h, D.l, D.c
    n = len(c)
    fast = -1
    for k in range(d + 1, min(d + maxd + 1, n)):
        if not np.isfinite(l[k, j]):
            continue
        if fast < 0 and float(h[k, j]) >= fill * 1.3 and float(l[k, j]) > stop:
            fast = k - d
        if float(o[k, j]) <= stop:
            return float(o[k, j]) / fill - 1, k - d, fast
        if float(l[k, j]) <= stop:
            return stop / fill - 1, k - d, fast
        if float(c[k, j]) < float(e21[k, j]):
            return float(c[k, j]) / fill - 1, k - d, fast
    last = min(d + maxd, n - 1)
    return float(c[last, j]) / fill - 1, last - d, fast


def s60():
    from .martin_list import ema
    D, F, M, shorts, replace = setup7()
    e21 = ema(D.c.astype(float), 21).astype(np.float32)
    d, j, fill, stop = candidates(D, F, M)
    print('candidates', len(d), 'a day', round(len(d) / len(set(d.tolist())), 1), flush=True)
    out = np.array([walk(D, e21, a, b, x, y) for a, b, x, y in zip(d.tolist(), j.tolist(), fill.tolist(), stop.tolist())])
    ret, days, fast = out[:, 0], out[:, 1], out[:, 2]
    big = ret >= .30
    quick = (fast > 0) & (fast <= 20)
    yr = np.array([D.days[x][:4] for x in d])
    for y in ('2024', '2025', '2026'):
        m = yr == y
        print(f"{y}: n {m.sum()} win {np.mean(ret[m] > 0):.2f} mean {ret[m].mean():+.2%} big {big[m].mean():.1%} quick {quick[m].mean():.1%} days {days[m].mean():.1f} return per day {ret[m].sum() / days[m].sum():+.3%}", flush=True)
    np.savez('/tmp/msum/s60.npz', d=d, j=j, fill=fill, stop=stop, ret=ret, days=days, fast=fast)
    keys = [k for k in sorted(F) if k not in ('nsq', 'nr10')]
    rows = []
    for k in keys:
        back = 0 if k in ('act1', 'act3', 'gain', 'cpos', 'gap', 'opgain', 'overpdh', 'lowe9', 'lowe21', 'to1_20', 'g1', 'nr', 'inside', 'cross_e9') or k.startswith('w_') else 0
        p = pct(F[k], M)[d, j]
        rec = {}
        for y in ('2024', '2025', '2026'):
            m = (yr == y) & np.isfinite(p)
            a, b = np.nanpercentile(p[m], [33.3, 66.7])
            lo, hi = m & (p <= a), m & (p > b)
            rec[y] = (big[hi].mean() - big[lo].mean(), quick[hi].mean() - quick[lo].mean(), ret[hi].mean() - ret[lo].mean())
        rows.append((k, rec))
    def key(r, i):
        v = [r[y][i] for y in ('2024', '2025', '2026')]
        return min(abs(x) for x in v) if len({np.sign(x) for x in v}) == 1 else 0
    for i, title in ((1, 'quick: high third minus low third'), (0, 'big'), (2, 'mean return')):
        print('==', title, flush=True)
        for k, r in sorted(rows, key=lambda kv: -key(kv[1], i))[:12]:
            print(f"  {k:11s} " + ' '.join(f"{r[y][i] * 100:+.1f}" for y in ('2024', '2025', '2026')), flush=True)


def cand_matrix(D, F, M, d, j):
    keys = [k for k in sorted(F) if k not in ('nsq', 'nr10')]
    X = np.zeros((len(d), len(keys)), dtype=np.float32)
    for c, k in enumerate(keys):
        X[:, c] = np.nan_to_num(pct(F[k], M)[d, j] - .5)
    return keys, X


def s61():
    D, F, M, shorts, replace = setup7()
    z = np.load('/tmp/msum/s60.npz')
    d, j, fill, stop, ret, days, fast = (z[k] for k in ('d', 'j', 'fill', 'stop', 'ret', 'days', 'fast'))
    keys, X = cand_matrix(D, F, M, d, j)
    print('matrix', X.shape, flush=True)
    y = ((ret >= .30) | ((fast > 0) & (fast <= 20))).astype(np.float32)
    print('label rate', round(float(y.mean()), 3), flush=True)
    ds = np.array(D.days)[d]
    cf = np.full(len(d), np.nan, dtype=np.float32)
    W = []
    for a, b in FOLDS:
        inside = (ds >= a) & (ds <= b)
        if not inside.any():
            continue
        fd = np.flatnonzero([a <= x <= b for x in D.days])
        tr = (d < fd[0] - 60) | (d > fd[-1] + 60)
        w, _ = fit_logit(X[tr], y[tr], 300.0)
        W.append(w)
        cf[inside] = X[inside] @ w
    wf = np.full(len(d), np.nan, dtype=np.float32)
    for a, b in (('2025-01-01', '2025-06-30'), ('2025-07-01', '2025-12-31'), ('2026-01-01', '2026-06-30'), ('2026-07-01', '2026-12-31')):
        inside = (ds >= a) & (ds <= b)
        fd = np.flatnonzero([a <= x <= b for x in D.days])
        tr = d < fd[0] - 60
        w, _ = fit_logit(X[tr], y[tr], 300.0)
        wf[inside] = X[inside] @ w
    w = np.mean(W, axis=0)
    print('top weights', [(k, round(float(a), 2)) for k, a in sorted(zip(keys, w), key=lambda r: -abs(r[1]))[:14]], flush=True)
    np.savez('/tmp/msum/s61.npz', cf=cf, wf=wf)
    yr = ds.astype('U4')
    def top(score, n):
        pick = []
        for day in np.unique(d):
            ix = np.flatnonzero((d == day) & np.isfinite(score))
            if len(ix):
                pick += ix[np.argsort(-score[ix])[:n]].tolist()
        return np.array(pick, dtype=int)
    for name, sc in (('CF', cf), ('WF', wf)):
        for n in (2, 6):
            p = top(sc, n)
            txt = []
            for yy in ('2024', '2025', '2026'):
                m = p[yr[p] == yy]
                if len(m):
                    txt.append(f"{yy}: n {len(m)} mean {ret[m].mean():+.2%} win {np.mean(ret[m] > 0):.2f} big {np.mean(ret[m] >= .3):.1%} quick {np.mean((fast[m] > 0) & (fast[m] <= 20)):.1%} perday {ret[m].sum() / days[m].sum():+.3%}")
            print(name, f'top {n}', ' | '.join(txt), flush=True)
    res = {}
    def book(score):
        out = [[] for _ in range(len(D.c))]
        o = np.argsort(-np.nan_to_num(score, nan=-99))
        for i in o:
            if np.isfinite(score[i]) and len(out[d[i]]) < 8:
                out[d[i]].append(((1.0, -float(score[i])), int(j[i]), 1, float(fill[i]), float(stop[i]), 'cand'))
        return out
    for name, sc in (('CF', cf), ('WF', np.where(np.isfinite(wf), wf, cf))):
        b = book(sc)
        for N in (4, 6, 8):
            k = f'{name}{N}'
            res[k] = account(D, b, nl_rules(D, N), k)
            print_2025(D, b, nl_rules(D, N), k)
            RV.write('strong_s61.json', res)


def his_list(D, F, M, days=20):
    """His scans into his lists: seen on a scan lately and still leading; read the evening before."""
    from .martin_list import ema
    c = D.c.astype(float)
    e21, e50 = ema(c, 21).astype(np.float32), ema(c, 50).astype(np.float32)
    lead = (D.e9 > e21) & (e21 > e50)
    seen = (np.nan_to_num(F['since_pot'], nan=999) <= days) | (np.nan_to_num(F['since_led'], nan=999) <= days)
    return lag((seen & lead).astype(np.float32)).astype(bool) & D.U


def book_by(D, F, L, order, max_ext=8.0):
    b = pool_book2(D, F, L, order, True, max_ext, None, False)
    return [[((1.0,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:6]) for e in r] for r in b]


def s62():
    D, F, M, shorts, replace = setup7()
    L = his_list(D, F, M)
    print('list size median', int(np.median(L[D.window].sum(1))), 'q10/90', np.percentile(L[D.window].sum(1), [10, 90]).astype(int), 'his entries on the list', sum(L[x[0], x[1]] for x in D.his), 'big', sum(L[x[0], x[1]] for x in D.big), flush=True)
    H = np.where(L, 1.0, np.nan)
    S = name_score(D, F, M, HOLD['H3'])
    act = lag(F['act20'])
    money = lag(F['money'])
    res = {}
    def run(k, order, N, extra=None):
        ent = book_by(D, F, L, order)
        if extra is not None:
            ent = [a + b for a, b in zip(ent, extra)]
        res[k] = account(D, ent, nl_rules(D, N), k)
        print_2025(D, ent, nl_rules(D, N), k)
        RV.write('strong_s62.json', res)
    run('P1', act, 6)
    run('P2', money, 6)
    run('P3', S, 6)
    run('P4', act, 4)
    gaps, _ = gap_strict(D, F)
    run('P5', act, 6, [[((1.5,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:5]) + ('list',) for e in r[:1]] for r in gaps])


def s63():
    D, F, M, shorts, replace = setup7()
    S = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(S, 12, 36)
    sat = pool_book2(D, F, H, S, True, 8.0, None, False)
    plain = lambda book, pr: [[((pr,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:6]) for e in r] for r in book]
    reg, s2 = plain(longs(D.reg), 1.0), plain(sat, 2.0)
    base = lambda **kw: nl_rules(D, 6, trail='e9', **kw)
    res = {}
    for k, ent, ru in (('C1', s2, base()), ('C2', s2, base(trims=(3, 5), trim_frac=.15)), ('C3', s2, base(nft_days=2)), ('C4', s2, base(rotate_below=.02, rotate_min_days=3)), ('C5', reg, base()), ('C6', merge(reg, s2), base())):
        res[k] = account(D, ent, ru, k)
        print_2025(D, ent, ru, k)
        RV.write('strong_s63.json', res)


def s64():
    D, F, M, shorts, replace = setup7()
    S = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(S, 12, 36)
    plain = lambda book: [[((1.0,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:]) for e in r] for r in book]
    b3, b25 = plain(pool_book3(D, F, H, S, 8.0, False, .03)), plain(pool_book3(D, F, H, S, 8.0, False, .025))
    lim = plain(limit_book(D, F, H, S, .025, 8.0))
    print('a year', round(sum(len(x) for x in b3) / (len(D.days) / 252)), round(sum(len(x) for x in b25) / (len(D.days) / 252)), round(sum(len(x) for x in lim) / (len(D.days) / 252)), flush=True)
    both = [a + b for a, b in zip(b3, lim)]
    def ru(N=6, **kw):
        from dataclasses import replace as rp
        x = nl_rules(D, N, trail='e9', **kw)
        return rp(x, intraday_kinds=tuple(x.intraday_kinds) + ('lim',))
    res = {}
    for k, ent, r in (('D1', b3, ru()), ('D2', b25, ru()), ('D3', lim, ru()), ('D4', both, ru()), ('D5', b3, ru(8))):
        res[k] = account(D, ent, r, k)
        print_2025(D, ent, r, k)
        RV.write('strong_s64.json', res)


def s65():
    from . import panels
    from dataclasses import replace as rp
    D, F, M, shorts, replace = setup7()
    S = name_score(D, F, M, HOLD['H3'])
    H = hold_sim(S, 12, 36)
    plain = lambda book: [[((1.0,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:]) for e in r] for r in book]
    ent = plain(pool_book3(D, F, H, S, 8.0, False, .03))
    def fixed(N, pos=.25):
        return rp(nl_rules(D, N, trail='e9'), max_position=pos, max_gross=N * pos, margin_rate=.07)
    def his(risk):
        return rp(nl_rules(D, 11, trail='e9'), risk=risk, risk_low=risk, max_position=.30, max_gross=2.8, margin_rate=.07)
    res = {}
    for k, ru in (('V1', fixed(4)), ('V2', fixed(7)), ('V3', fixed(11)), ('V4', his(.005)), ('V5', his(.01))):
        res[k] = account(D, ent, ru, k)
        tk = {}
        st, tr = D.base.run(D.A, ent, panels.WINDOW, D.pool, ru, placebo=0, audit=True, track=tk)
        ds = [x for x in D.days if panels.WINDOW[0] <= x <= panels.WINDOW[1]]
        g = np.array(tk['gross'], dtype=float)[-len(ds):]
        op = np.array(tk['open'], dtype=float)[-len(ds):]
        print('   ' + ' '.join(f"{y}: gross {g[[x[:4] == y for x in ds]].mean():.2f} open {op[[x[:4] == y for x in ds]].mean():.1f}" for y in ('2024', '2025', '2026')), flush=True)
        print_2025(D, ent, ru, k)
        RV.write('strong_s65.json', res)


if __name__ == '__main__':
    globals()[sys.argv[1]]()
