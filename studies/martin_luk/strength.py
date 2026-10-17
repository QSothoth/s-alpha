"""Pipeline step 2: compare definitions of 'strongest' (notes/PIPELINE_CN.md, PREREG_R13.md).

    nice -n 19 /opt/futu-opend/venv/bin/python -m studies.martin_luk.strength r13
"""
from __future__ import annotations

import json
import sys

import numpy as np

from . import intraday as I, luk, selection as S


def base_arrays():
    b = S.broad()
    A = dict(days=b['days'], codes=b['codes'])
    for k in ('close', 'open', 'high', 'low'):
        A[k] = b[k].astype(float)
    A['raw'] = b['raw_close'].astype(float)
    A['to20'] = luk.rolling_mean(b['turnover'].astype(float), 20)
    A['turnover'] = b['turnover'].astype(float)
    c, h, l = A['close'], A['high'], A['low']
    A['adr'] = luk.rolling_mean(h / l - 1, 20) * 100
    A['e9'], A['e21'], A['e50'] = luk.ema(c, 9), luk.ema(c, 21), luk.ema(c, 50)
    with np.errstate(invalid='ignore', divide='ignore'):
        A['pool'] = (A['raw'] >= 1) & (A['to20'] >= 2e6)
        A['tradeable'] = (A['raw'] >= 5) & (A['to20'] >= 20e6) & (A['adr'] >= 4)
        A['stack'] = (A['e9'] > A['e21']) & (A['e21'] > A['e50'])
        tight = ((h <= luk.lag(h)) & (l >= luk.lag(l))) | ((h / l - 1) * 100 <= .5 * A['adr'])
        e21p, e9p = luk.lag(A['e21']), luk.lag(A['e9'])
        A['setup'] = (((l < e21p) & (c > e21p)) | ((l < e9p) & (c > e9p))
                      | ((luk.lag(tight.astype(float)) == 1) & (c > luk.lag(h))))
    outcomes(A)
    return A


def outcomes(A):
    """fwd10 from the next open, and 'hit +20% before -7%' within 20 days (a same-day tie counts as -7%)."""
    c, o, h, l = A['close'], A['open'], A['high'], A['low']
    T = len(c)
    o1 = np.full_like(c, np.nan)
    o1[:-1] = o[1:]
    fwd = np.full_like(c, np.nan)
    win = np.full_like(c, np.nan)
    for t in range(T - 20):
        fwd[t] = c[t + 10] / o1[t] - 1
        decided = np.zeros(c.shape[1], bool)
        res = np.zeros(c.shape[1])
        for k in range(1, 21):
            dn = (l[t + k] / o1[t] - 1 <= -.07) & ~decided
            res[dn] = 0
            decided |= dn
            up = (h[t + k] / o1[t] - 1 >= .20) & ~decided
            res[up] = 1
            decided |= up
        win[t] = np.where(np.isnan(o1[t]), np.nan, res)
    A['fwd'], A['win'], A['o1'] = fwd, win, o1


def deciles(A, m):
    dec = np.full(A['close'].shape, -1, np.int8)
    for t in np.flatnonzero(m):
        a = np.where(A['tradeable'][t], A['adr'][t], np.nan)
        if np.isfinite(a).sum() >= 20:
            edges = np.nanquantile(a, np.linspace(0, 1, 11)[1:-1])
            dec[t] = np.where(A['tradeable'][t], np.searchsorted(edges, np.nan_to_num(A['adr'][t])), -1)
    return dec


def evaluate(A, watch, lo, hi, dec):
    """Same-day, same-ADR-decile excess of watchlist setups over other setups."""
    days = A['days']
    ev = A['tradeable'] & A['stack'] & A['setup'] & ~np.isnan(A['fwd']) & ~np.isnan(A['adr'])
    m = (days >= lo) & (days <= hi)
    rows = []
    for t in np.flatnonzero(m):
        inside, outside = ev[t] & watch[t], ev[t] & ~watch[t]
        if not inside.any():
            continue
        d1, d2, wts = [], [], []
        for k in range(10):
            a, z = inside & (dec[t] == k), outside & (dec[t] == k)
            if a.any() and z.any():
                d1.append(A['fwd'][t, a].mean() - A['fwd'][t, z].mean())
                d2.append(A['win'][t, a].mean() - A['win'][t, z].mean())
                wts.append(a.sum())
        if wts:
            w = np.array(wts, float)
            rows.append((float(np.average(d1, weights=w)), float(np.average(d2, weights=w)), int(inside.sum()),
                         float(A['fwd'][t, inside].mean()), float(A['win'][t, inside].mean())))
    if not rows:
        return dict(days=0)
    ex = np.array([r[0] for r in rows])
    boots = np.random.default_rng(0).choice(ex, (2000, len(ex))).mean(axis=1)
    return dict(days=len(rows), events_per_day=float(np.mean([r[2] for r in rows])),
                fwd10_inside=float(np.mean([r[3] for r in rows])), fwd10_excess=float(ex.mean()),
                ci=[float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))],
                win_inside=float(np.mean([r[4] for r in rows])), win_excess=float(np.mean([r[1] for r in rows])))


def top_watch(A, score, top=.02, lookback=20):
    """Watchlist: in the top `top` of the ranking pool on `score` on any of the past `lookback` days."""
    with np.errstate(invalid='ignore'):
        s = np.where(A['pool'], score, np.nan)
        cut = np.nanquantile(s, 1 - top, axis=1)
        on = A['pool'] & (s >= cut[:, None])
    return S._past_any(on, lookback)


def scores_r13(A):
    c, h = A['close'], A['high']
    lag = luk.lag
    with np.errstate(invalid='ignore', divide='ignore'):
        r63 = c / lag(c, 63) - 1
        ibd = (2 * r63 + (lag(c, 63) / lag(c, 126) - 1) + (lag(c, 126) / lag(c, 189) - 1)
               + (lag(c, 189) / lag(c, 252) - 1))
        lr = np.log(c / lag(c))
        sd = np.sqrt(np.maximum(luk.rolling_mean(lr ** 2, 63) - luk.rolling_mean(lr, 63) ** 2, 0))
        volmom = r63 / (sd * np.sqrt(63))
        hh = np.full_like(h, np.nan)
        for t in range(251, len(h)):
            hh[t] = np.nanmax(h[t - 251:t + 1], axis=0)
        nearhigh = np.where(c >= .85 * hh, r63, np.nan)
        y = np.log(c)
        n = 63
        x = np.arange(n, dtype=float)
        sx, sxx = x.sum(), (x ** 2).sum()
        sy = luk.rolling_mean(y, n) * n
        syy = luk.rolling_mean(y ** 2, n) * n
        idx = np.arange(len(y), dtype=float)[:, None]
        sxy_abs = luk.rolling_mean(y * idx, n) * n
        sxy = sxy_abs - (idx - (n - 1)) * sy
        cov = sxy - sx * sy / n
        varx = sxx - sx ** 2 / n
        vary = syy - sy ** 2 / n
        slope = cov / varx
        r2 = cov ** 2 / (varx * vary)
        quality = (np.exp(slope * 252) - 1) * r2
    ind = S.industries([str(x) for x in A['codes']])
    g = np.array([ind.get(str(x), '') for x in A['codes']])
    grp = np.full_like(r63, np.nan)
    with np.errstate(invalid='ignore'):
        rp = np.where(A['pool'], r63, np.nan)
        for t in range(len(c)):
            row = rp[t]
            ok = np.isfinite(row) & (g != '')
            if ok.sum() < 50:
                continue
            gs = g[ok]
            uniq, inv = np.unique(gs, return_inverse=True)
            med = np.array([np.median(row[ok][inv == k]) for k in range(len(uniq))])
            gpct = (np.argsort(np.argsort(med)) + .5) / len(med)
            spct = (np.argsort(np.argsort(row[ok])) + .5) / ok.sum()
            grp[t, np.flatnonzero(ok)] = gpct[inv] + spct
    return {'A_ibd': ibd, 'B_volmom': volmom, 'C_nearhigh': nearhigh, 'D_quality': quality, 'E_industry': grp}


def w2(A):
    c = A['close']
    with np.errstate(invalid='ignore', divide='ignore'):
        n = np.zeros(c.shape, np.int8)
        for hz in (21, 63, 126):
            r = np.where(A['pool'], c / luk.lag(c, hz) - 1, np.nan)
            n += (A['pool'] & (r >= np.nanquantile(r, .98, axis=1)[:, None])).astype(np.int8)
    return S._past_any(n >= 2, 20)


def r13():
    A = base_arrays()
    sel, val = ('2024-01-02', '2024-12-31'), ('2025-01-02', '2026-10-16')
    dec = deciles(A, (A['days'] >= sel[0]) & (A['days'] <= val[1]))
    watches = {k: top_watch(A, s) for k, s in scores_r13(A).items()}
    watches['ref_W2'] = w2(A)
    out = {'select': {}, 'validate': {}}
    for k, w in watches.items():
        out['select'][k] = evaluate(A, w, *sel, dec)
        print('select', k, {a: (round(v, 4) if isinstance(v, float) else v) for a, v in out['select'][k].items()}, flush=True)
    best = max((k for k in watches if not k.startswith('ref')), key=lambda k: out['select'][k].get('fwd10_excess', -9))
    for k in (best, 'ref_W2'):
        out['validate'][k] = evaluate(A, watches[k], *val, dec)
        print('validate', k, {a: (round(v, 4) if isinstance(v, float) else v) for a, v in out['validate'][k].items()}, flush=True)
    out['chosen'] = best
    out['passed'] = bool(out['validate'][best]['ci'][0] > 0)
    print('chosen', best, 'passed', out['passed'])
    (I.OUT / 'r13_strength.json').write_text(json.dumps(out, indent=1))


if __name__ == '__main__' and sys.argv[1] == 'r13':
    r13()


def lists_count(A):
    c = A['close']
    with np.errstate(invalid='ignore', divide='ignore'):
        n = np.zeros(c.shape, np.int8)
        for hz in (21, 63, 126):
            r = np.where(A['pool'], c / luk.lag(c, hz) - 1, np.nan)
            n += (A['pool'] & (r >= np.nanquantile(r, .98, axis=1)[:, None])).astype(np.int8)
    return n


def _past_max(x, k):
    out = np.zeros_like(x)
    for j in range(1, k + 1):
        out[j:] = np.maximum(out[j:], x[:-j])
    return out


def r14():
    A = base_arrays()
    sel, val = ('2024-01-02', '2024-12-31'), ('2025-01-02', '2026-10-16')
    dec = deciles(A, (A['days'] >= sel[0]) & (A['days'] <= val[1]))
    n = lists_count(A)
    base = S._past_any(n >= 2, 20)
    recent = _past_max(n, 5)
    before = luk.lag(_past_max(n, 5).astype(float), 20)
    ind = S.industries([str(x) for x in A['codes']])
    g = np.array([ind.get(str(x), '') for x in A['codes']])
    theme = np.zeros_like(base)
    for t in range(len(A['days'])):
        js = np.flatnonzero(base[t] & (g != ''))
        if len(js) >= 3:
            u, cnt = np.unique(g[js], return_counts=True)
            hot = u[cnt >= 3]
            if len(hot):
                theme[t] = base[t] & np.isin(g, hot)
    watches = {'N1_three': S._past_any(n >= 3, 20), 'N2_keep10': S._past_any(n >= 2, 10),
               'N3_keep40': S._past_any(n >= 2, 40),
               'N4_upgrade': base & (recent > np.nan_to_num(before, nan=0)), 'N5_theme': theme, 'ref_W2': base}
    out = {'select': {}, 'validate': {}}
    for k, w in watches.items():
        out['select'][k] = evaluate(A, w, *sel, dec)
        print('select', k, {a: (round(v, 4) if isinstance(v, float) else v) for a, v in out['select'][k].items()}, flush=True)
    best = max((k for k in watches if not k.startswith('ref')), key=lambda k: out['select'][k].get('fwd10_excess', -9))
    for k in (best, 'ref_W2'):
        out['validate'][k] = evaluate(A, watches[k], *val, dec)
        print('validate', k, {a: (round(v, 4) if isinstance(v, float) else v) for a, v in out['validate'][k].items()}, flush=True)
    v = out['validate']
    out['chosen'] = best
    out['better_than_W2'] = bool(v[best]['ci'][0] > 0 and v[best]['fwd10_excess'] > v['ref_W2']['fwd10_excess'])
    print('chosen', best, 'better than W2', out['better_than_W2'])
    (I.OUT / 'r14_watchlist.json').write_text(json.dumps(out, indent=1))


if __name__ == '__main__' and sys.argv[1] == 'r14':
    r14()


def r15():
    A = base_arrays()
    sel, val = ('2024-01-02', '2024-12-31'), ('2025-01-02', '2026-10-16')
    dec = deciles(A, (A['days'] >= sel[0]) & (A['days'] <= val[1]))
    w = w2(A)
    c, h, l, adr = A['close'], A['high'], A['low'], A['adr']
    b = S.broad()
    vol = b['turnover'].astype(float) / np.where(b['close'] > 0, b['close'], np.nan)
    lag = luk.lag
    with np.errstate(invalid='ignore', divide='ignore'):
        adr5 = luk.rolling_mean(h / l - 1, 5) * 100
        v5, v50 = luk.rolling_mean(vol, 5), luk.rolling_mean(vol, 50)
        hh20 = np.full_like(h, np.nan)
        hh5 = np.full_like(h, np.nan)
        ll5 = np.full_like(h, np.nan)
        for t in range(19, len(h)):
            hh20[t] = np.nanmax(h[t - 19:t + 1], axis=0)
        for t in range(4, len(h)):
            hh5[t] = np.nanmax(h[t - 4:t + 1], axis=0)
            ll5[t] = np.nanmin(l[t - 4:t + 1], axis=0)
        e21p = lag(A['e21'])
        extra = {
            'F1_shallow': (l - e21p) / c * 100 <= adr,
            'F2_contract': lag(adr5) <= .7 * lag(adr),
            'F3_dryup': lag(v5) <= .7 * lag(v50),
            'F4_converge': np.abs(lag(A['e9']) - e21p) / lag(c) <= .01,
            'F5_flag': ((lag(c) >= .9 * lag(hh20)) & ((lag(hh5) - lag(ll5)) / lag(c) * 100 <= 1.5 * lag(adr))
                        & (c > lag(hh5))),
        }
    setup0 = A['setup'].copy()
    out = {'select': {}, 'validate': {}}
    res = {}
    for k, x in extra.items():
        A['setup'] = setup0 & x if k != 'F5_flag' else x
        res[k] = A['setup'].copy()
        out['select'][k] = evaluate(A, w, *sel, dec)
        print('select', k, {a: (round(v, 4) if isinstance(v, float) else v) for a, v in out['select'][k].items()}, flush=True)
    A['setup'] = setup0
    out['select']['ref_base'] = evaluate(A, w, *sel, dec)
    print('select ref_base', {a: (round(v, 4) if isinstance(v, float) else v) for a, v in out['select']['ref_base'].items()})
    best = max(extra, key=lambda k: out['select'][k].get('fwd10_inside', -9))
    A['setup'] = res[best]
    out['validate'][best] = evaluate(A, w, *val, dec)
    A['setup'] = setup0
    out['validate']['ref_base'] = evaluate(A, w, *val, dec)
    for k in (best, 'ref_base'):
        print('validate', k, {a: (round(v, 4) if isinstance(v, float) else v) for a, v in out['validate'][k].items()}, flush=True)
    v = out['validate']
    out['chosen'] = best
    out['better'] = bool(v[best]['ci'][0] > 0 and v[best]['fwd10_inside'] > v['ref_base']['fwd10_inside'])
    print('chosen', best, 'better than base setup', out['better'])
    (I.OUT / 'r15_setup.json').write_text(json.dumps(out, indent=1))


if __name__ == '__main__' and sys.argv[1] == 'r15':
    r15()


def r18():
    A = base_arrays()
    sel, val = ('2024-01-02', '2024-12-31'), ('2025-01-02', '2026-10-16')
    dec = deciles(A, (A['days'] >= sel[0]) & (A['days'] <= val[1]))
    n = lists_count(A)
    base = S._past_any(n >= 2, 20)
    upgrade = base & (_past_max(n, 5) > np.nan_to_num(luk.lag(_past_max(n, 5).astype(float), 20), nan=0))
    codes = [str(x) for x in A['codes']]
    union = sorted({codes[j] for j in np.flatnonzero(base.any(0))})
    cp = S.concepts(union)
    names = sorted({c for u in union for c in cp.get(u, [])})
    ci = {c: k for k, c in enumerate(names)}
    M = np.zeros((len(codes), len(names)), bool)                 # stock x concept membership
    for j, code in enumerate(codes):
        for c in cp.get(code, []):
            M[j, ci[c]] = True
    fresh5 = S._past_any(base & ~S._past_any(base, 60), 5)
    T = len(A['days'])
    t2 = np.zeros_like(base)
    t4 = np.zeros_like(base)
    t5 = np.zeros_like(base)
    for t in range(T):
        on = base[t]
        if on.sum() < 3:
            continue
        cnt = M[on].sum(0)                                       # W2 members per concept today
        others = (M & on[:, None]).sum(0)
        t2[t] = on & ((M & (cnt[None, :] - 1 >= 2)).any(1))
        hot = np.argsort(-cnt)[:5]
        hot = hot[cnt[hot] >= 3]
        if len(hot):
            t4[t] = on & M[:, hot].any(1)
        fc = M[fresh5[t]].sum(0)
        new = np.flatnonzero(fc >= 3)
        if len(new):
            t5[t] = on & M[:, new].any(1)
    watches = {'T1_upgrade': upgrade, 'T2_concept': t2, 'T3_both': upgrade & t2, 'T4_hottest': t4, 'T5_emerging': t5,
               'ref_W2': base}
    out = {'select': {}, 'validate': {}}
    for k, w in watches.items():
        out['select'][k] = evaluate(A, w, *sel, dec)
        print('select', k, {a: (round(v, 4) if isinstance(v, float) else v) for a, v in out['select'][k].items()}, flush=True)
    best = max((k for k in watches if not k.startswith('ref')), key=lambda k: out['select'][k].get('fwd10_excess', -9))
    for k in (best, 'ref_W2'):
        out['validate'][k] = evaluate(A, watches[k], *val, dec)
        print('validate', k, {a: (round(v, 4) if isinstance(v, float) else v) for a, v in out['validate'][k].items()}, flush=True)
    out['chosen'] = best
    out['passed'] = bool(out['validate'][best]['ci'][0] > 0)
    print('chosen', best, 'passed', out['passed'])
    (I.OUT / 'r18_theme.json').write_text(json.dumps(out, indent=1))


if __name__ == '__main__' and sys.argv[1] == 'r18':
    r18()
