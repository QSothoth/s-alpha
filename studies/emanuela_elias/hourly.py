"""Emanuela Elias on hourly bars (notes/PREREG_H1.md): hourly key levels, a broken level reclaimed ("buyers show up"),
a retest of it, out at the next level / 2R / three sessions.  Bars come only from the data interface
(studies.trader_data.load_hourly, release trader-hourly-v1).

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/opend-us-options/.venv/bin/python"
    $PY -m studies.emanuela_elias.hourly round H1
    $PY -m studies.emanuela_elias.hourly validate h1.json

Every decision reads closed bars only: a pivot is known k bars after it, the list as of the prior session, an entry
at the close of the retest bar, exits on the following bars (stop first when a bar reaches both).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPORTS = HERE / 'reports'
ROUNDS = HERE / 'notes' / 'rounds'
SELECT = ('2024-01-02', '2025-12-31')
VALIDATE = ('2020-01-02', '2023-12-29')
USED = ('2026-01-02', '2026-10-23')
INDEX = ('US.QQQ', 'US.SPY')

BASE = dict(levels='pivot', k=5, lookback=70, reclaim=7, retest=14, band=.005, stop_pad=.002, min_stop=.005,
            target='level', hold=21, top=15, min_price=5.0, cost=.0005, qqq=False, sides=['long', 'short'])


class Data:
    """The hourly panel, its daily rebuild and the daily list."""

    def __init__(self, mode='frozen'):
        from studies import trader_data as TD
        from studies.trader_data import hourly as H
        p = TD.load_hourly('us', mode=mode)
        self.p = p
        self.codes = [str(c) for c in p['codes']]
        self.times = p['times'].astype(str)
        self.o, self.h, self.l, self.c = (p[k].astype(float) for k in ('open', 'high', 'low', 'close'))
        d = H.daily(p)
        self.days = d['days'].astype(str)
        self.bar_day = np.searchsorted(self.days, p['days'].astype(str))
        self.d_close, self.d_low, self.d_high = d['close'], d['low'], d['high']
        to = d['turnover']
        to20 = np.full_like(to, np.nan)
        for i in range(19, len(to)):
            with np.errstate(invalid='ignore'), np.errstate(all='ignore'):
                w = to[i - 19:i + 1]
                to20[i] = np.where(np.isfinite(w).sum(0) >= 15, np.nanmean(np.where(np.isfinite(w), w, np.nan), 0), np.nan)
        self.to20 = to20

    def listed(self, top, min_price):
        """(days x codes) bool: in the top `top` by 20-day turnover as of the prior session (price >= min_price)."""
        out = np.zeros(self.to20.shape, bool)
        idx = [j for j, c in enumerate(self.codes) if c not in INDEX]
        for i in range(1, len(self.days)):
            v = self.to20[i - 1].copy()
            ok = np.isfinite(v) & (self.d_close[i - 1] >= min_price)
            ok[[j for j in range(len(self.codes)) if j not in idx]] = False
            v[~ok] = -1
            pick = np.argsort(-v)[:top]
            out[i, [j for j in pick if v[j] > 0]] = True
        return out


def pivots(lo, hi, k):
    """Confirmed pivots of one stock: (confirm bar, level, 'low' | 'high') sorted by confirm bar."""
    out = []
    n = len(lo)
    for b in range(k, n - k):
        wl, wh = lo[b - k:b + k + 1], hi[b - k:b + k + 1]
        if np.isfinite(lo[b]) and np.all(np.isfinite(wl)) and lo[b] <= wl.min():
            out.append((b + k, float(lo[b]), 'low', b))
        if np.isfinite(hi[b]) and np.all(np.isfinite(wh)) and hi[b] >= wh.max():
            out.append((b + k, float(hi[b]), 'high', b))
    out.sort()
    return out


class Levels:
    """Pivots of one kind as time moves forward: `at(t)` = levels confirmed by bar t, made within `lookback` bars."""

    def __init__(self, piv, kind, lookback):
        self.piv = [(cb, lv, b) for cb, lv, kd, b in piv if kd == kind]
        self.lookback, self.p, self.active, self.t = lookback, 0, [], -1

    def at(self, t):
        if t < self.t:
            raise ValueError('Levels.at goes forward only')
        self.t = t
        while self.p < len(self.piv) and self.piv[self.p][0] <= t:
            self.active.append(self.piv[self.p][1:])
            self.p += 1
        self.active = [(lv, b) for lv, b in self.active if b >= t - self.lookback]
        return [lv for lv, _ in self.active]


def simulate_exit(o, h, l, c, t0, side, entry, stop, target, hold, cost):
    """Walk the bars after t0: stop (gap through it: the open), target, or the close of the `hold`-th bar.
    Returns (exit bar, exit price, why, return net of costs)."""
    n = len(c)
    for t in range(t0 + 1, min(t0 + hold, n - 1) + 1):
        if not np.isfinite(c[t]):
            continue
        if side > 0:
            if o[t] <= stop:
                px, why = o[t], 'stop'
            elif l[t] <= stop:
                px, why = stop, 'stop'
            elif o[t] >= target:
                px, why = o[t], 'target'
            elif h[t] >= target:
                px, why = target, 'target'
            else:
                px, why = None, None
        else:
            if o[t] >= stop:
                px, why = o[t], 'stop'
            elif h[t] >= stop:
                px, why = stop, 'stop'
            elif o[t] <= target:
                px, why = o[t], 'target'
            elif l[t] <= target:
                px, why = target, 'target'
            else:
                px, why = None, None
        if px is None and t == min(t0 + hold, n - 1):
            px, why = c[t], 'time'
        if px is not None:
            return t, float(px), why, side * (px / entry - 1) - 2 * cost
    return None


def trades(D, cfg, seg):
    """All trades of the configuration with entries in seg (stock level)."""
    listed = D.listed(cfg['top'], cfg['min_price'])
    lo_t, hi_t = np.searchsorted(D.times, seg[0]), np.searchsorted(D.times, seg[1] + ' 99', side='right')
    qi = D.codes.index('US.QQQ') if 'US.QQQ' in D.codes else None
    if cfg['qqq'] and qi is not None:
        qc = D.c[:, qi]
        ema = np.full(len(qc), np.nan)
        a, e = 2 / 51, np.nan
        for t, x in enumerate(qc):
            if np.isfinite(x):
                e = x if not np.isfinite(e) else a * x + (1 - a) * e
            ema[t] = e
    out = []
    for j, code in enumerate(D.codes):
        if code in INDEX:
            continue
        o, h, l, c = D.o[:, j], D.h[:, j], D.l[:, j], D.c[:, j]
        piv = pivots(l, h, cfg['k']) if cfg['levels'] == 'pivot' else None
        mine = []
        for side in (1, -1):
            if ('long' if side > 0 else 'short') not in cfg['sides']:
                continue
            if piv is not None:
                sup_lv = Levels(piv, 'low' if side > 0 else 'high', cfg['lookback'])
                res_lv = Levels(piv, 'high' if side > 0 else 'low', cfg['lookback'])
            state, L, since = None, None, 0
            for t in range(max(lo_t, 1), hi_t):
                if piv is not None:
                    sup, res = sup_lv.at(t - 1), res_lv.at(t)
                else:
                    pd = D.bar_day[t] - 1
                    if pd < 0:
                        continue
                    sup = [float(D.d_low[pd, j] if side > 0 else D.d_high[pd, j])]
                    res = [float(D.d_high[pd, j] if side > 0 else D.d_low[pd, j])]
                if not np.isfinite(c[t]):
                    continue
                di = D.bar_day[t]
                prev_c = c[t - 1]
                if state is None:
                    cand = [x for x in sup if np.isfinite(x) and (x < prev_c if side > 0 else x > prev_c)]
                    if cand and np.isfinite(prev_c):
                        L0 = max(cand) if side > 0 else min(cand)
                        if (l[t] < L0) if side > 0 else (h[t] > L0):
                            state, L, since = 'broken', L0, t
                    continue
                if state == 'broken':
                    if t - since > cfg['reclaim']:
                        state = None
                    elif (c[t] > L) if side > 0 else (c[t] < L):
                        state, since = 'reclaimed', t
                    continue
                if t - since > cfg['retest']:                       # state 'reclaimed'
                    state = None
                    continue
                if (c[t] < L) if side > 0 else (c[t] > L):          # closed back through: broken again
                    state, since = 'broken', t
                    continue
                touch = (l[t] <= L * (1 + cfg['band'])) if side > 0 else (h[t] >= L * (1 - cfg['band']))
                if not touch:
                    continue
                state = None
                if not listed[di, j]:
                    continue
                if cfg['qqq'] and qi is not None and np.isfinite(ema[t]):
                    if (side > 0 and qc[t] < ema[t]) or (side < 0 and qc[t] > ema[t]):
                        continue
                entry = float(c[t])
                if side > 0:
                    stop = min(float(l[t]) * (1 - cfg['stop_pad']), entry * (1 - cfg['min_stop']))
                else:
                    stop = max(float(h[t]) * (1 + cfg['stop_pad']), entry * (1 + cfg['min_stop']))
                tgt = entry + side * 2 * abs(entry - stop)
                if cfg['target'] == 'level':
                    rr = [x for x in res if np.isfinite(x) and (x > entry * 1.001 if side > 0 else x < entry * .999)]
                    if rr:
                        tgt = min(rr) if side > 0 else max(rr)
                ex = simulate_exit(o, h, l, c, t, side, entry, stop, tgt, cfg['hold'], cfg['cost'])
                if ex is None:
                    continue
                te, px, why, r = ex
                mine.append(dict(code=code, j=j, side=side, t=t, entry_time=D.times[t], exit_time=D.times[te], te=te,
                                 entry=entry, stop=stop, target=tgt, exit=px, why=why, ret=r, level=L))
        last = -1                                                   # one trade a stock at a time, first come
        for x in sorted(mine, key=lambda x: x['t']):
            if x['t'] > last:
                out.append(x)
                last = x['te']
    out.sort(key=lambda x: x['t'])
    return out


def placebo(D, cfg, tr, draws=200, seed=1):
    """Mean return of the same trades moved to a random listed stock (same bar, side, stop / target distances,
    exits); distribution over `draws`."""
    listed = D.listed(cfg['top'], cfg['min_price'])
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(draws):
        rs = []
        for x in tr:
            pool = np.flatnonzero(listed[D.bar_day[x['t']]])
            if not len(pool):
                continue
            j = int(rng.choice(pool))
            e = D.c[x['t'], j]
            if not np.isfinite(e):
                continue
            s = e * (x['stop'] / x['entry'])
            g = e * (x['target'] / x['entry'])
            ex = simulate_exit(D.o[:, j], D.h[:, j], D.l[:, j], D.c[:, j], x['t'], x['side'], float(e), s, g,
                               cfg['hold'], cfg['cost'])
            if ex:
                rs.append(ex[3])
        means.append(float(np.mean(rs)) if rs else 0.0)
    return np.array(means)


def option_account(D, tr, seg, frac=.05, dte=10, k=.05, spread_x=1.0):
    """Each trade as a bought ATM call / put (`dte` calendar days), priced by option simulation v2 on the IV of the
    session before entry, revalued at the exit bar; premium = `frac` of realised equity, open premium <= equity."""
    from studies.trader_options import pricing as P
    iv = P.load_panel('iv', 'iv', D.days, D.codes, .01)
    ev = P.earnings(set(D.codes))
    rx = {j: P.reactions(D.days, ev.get(c, [])) for j, c in enumerate(D.codes)}
    import datetime as dt

    def hours(a, b):
        return (dt.datetime.fromisoformat(b) - dt.datetime.fromisoformat(a)).total_seconds() / 3600

    def price(j, di, S, K, T, put, ie):
        v = iv[max(di - 1, 0), j]
        if not (np.isfinite(v) and v > 0):
            return float('nan')
        E = P.implied_event_var(iv, j, rx[j], di, None) or 0.0
        _, near, spans = P.event_context(D.days, rx[j], max(di - 1, 0), ie)
        return P.bs(S, K, T, P.vol_v2(S, K, T, v, put, E, near, spans, k), put)

    eq, open_, rets, curve = 1.0, [], [], []
    for x in [t for t in tr if seg[0] <= t['entry_time'][:10] <= seg[1]]:
        for p in sorted([p for p in open_ if p[0] <= x['entry_time']]):
            eq += p[1] * p[2]
        open_ = [p for p in open_ if p[0] > x['entry_time']]
        put = x['side'] < 0
        di0, di1 = D.bar_day[x['t']], D.bar_day[x['te']]
        S0, S1 = x['entry'], x['exit']
        T0 = dte / 365
        ie = min(int(np.searchsorted(D.days, str(np.datetime64(x['entry_time'][:10]) + np.timedelta64(dte, 'D')),
                                     side='right')) - 1, len(D.days) - 1)
        T1 = max(T0 - hours(x['entry_time'], x['exit_time']) / (365 * 24), 1e-6)
        q0, q1 = price(x['j'], di0, S0, S0, T0, put, ie), price(x['j'], di1, S1, S0, T1, put, ie)
        if not (np.isfinite(q0) and np.isfinite(q1)) or q0 <= 0:
            continue
        p0 = q0 * (1 + P.half_spread(q0) * spread_x)
        p1 = q1 * (1 - P.half_spread(q1) * spread_x) if q1 > 0 else 0.0
        r = p1 / p0 - 1
        amt = frac * eq
        if sum(p[1] for p in open_) + amt > eq:
            continue
        open_.append((x['exit_time'], amt, r))
        rets.append(r)
        curve.append(eq)
    for p in open_:
        eq += p[1] * p[2]
    r = np.array(rets)
    peak = np.maximum.accumulate(np.array(curve + [eq])) if curve else np.ones(1)
    return dict(total=eq - 1, n=len(r), win=float((r > 0).mean()) if len(r) else None,
                avg_win=float(r[r > 0].mean()) if (r > 0).any() else None,
                avg_loss=float(r[r <= 0].mean()) if (r <= 0).any() else None,
                maxdd=float(np.max(1 - np.array(curve + [eq]) / peak)) if curve else 0.0)


def summary(tr):
    r = np.array([x['ret'] for x in tr])
    if not len(r):
        return dict(n=0)
    by_side = {s: float(np.mean([x['ret'] for x in tr if (x['side'] > 0) == (s == 'long')] or [np.nan]))
               for s in ('long', 'short')}
    why = {}
    for x in tr:
        why.setdefault(x['why'], []).append(x['ret'])
    srt = np.sort(r)[::-1]
    return dict(n=len(r), win=float((r > 0).mean()), avg=float(r.mean()), t=float(r.mean() / r.std() * math.sqrt(len(r))),
                avg_win=float(r[r > 0].mean()), avg_loss=float(r[r <= 0].mean()), by_side=by_side,
                why={k: (len(v), float(np.mean(v))) for k, v in why.items()},
                avg_without_top10=float(srt[10:].mean()) if len(r) > 20 else None,
                years={y: (len(v), float(np.mean(v))) for y in sorted({x['entry_time'][:4] for x in tr})
                       for v in [[x['ret'] for x in tr if x['entry_time'][:4] == y]]})


def round_(name, D=None):
    spec = json.loads((ROUNDS / f'{name}.json').read_text(encoding='utf-8'))
    D = D or Data()
    res = {}
    for key, ch in spec['candidates'].items():
        cfg = dict(BASE, **ch)
        tr = trades(D, cfg, SELECT)
        st = summary(tr)
        pl = placebo(D, cfg, tr, spec.get('draws', 200))
        st['placebo'] = dict(median=float(np.median(pl)), rank=float(np.mean(pl < st.get('avg', -9))))
        st['option'] = {tag: option_account(D, tr, SELECT, spread_x=sx, k=kk) for tag, sx, kk in (('v2', 1, .05), ('cons', 2, 0.0))}
        res[key] = dict(config=cfg, select=st)
        print(name, key, json.dumps({a: (round(b, 4) if isinstance(b, float) else b) for a, b in st.items()
                                     if a in ('n', 'win', 'avg', 't', 'avg_without_top10', 'placebo')}),
              'option', {k_: round(v['total'], 3) for k_, v in st['option'].items()}, flush=True)
    ok = [k_ for k_, v in res.items() if v['select']['n'] >= 100 and v['select']['placebo']['rank'] >= .9]
    chosen = max(ok, key=lambda k_: res[k_]['select']['t']) if ok else None
    out = dict(name=name, spec=spec, full=res, chosen=chosen, chosen_config=res[chosen]['config'] if chosen else None,
               rule='n >= 100 and placebo rank >= 0.9, then the highest t')
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f'{name.lower()}.json').write_text(json.dumps(out, indent=1, default=float), encoding='utf-8')
    print(name, 'chosen', chosen, flush=True)
    return out


def validate(report, D=None):
    res = json.loads((REPORTS / report).read_text(encoding='utf-8'))
    cfg = res['chosen_config']
    if cfg is None:
        print('nothing chosen')
        return None
    D = D or Data()
    out = dict(report=report, config=cfg)
    for nm, seg in (('validate_2020_2023', VALIDATE), ('select', SELECT), ('used_2026', USED)):
        tr = trades(D, cfg, seg)
        st = summary(tr)
        pl = placebo(D, cfg, tr, 200)
        st['placebo'] = dict(median=float(np.median(pl)), rank=float(np.mean(pl < st.get('avg', -9))))
        oseg = ('2023-06-01', seg[1]) if nm.startswith('validate') else seg
        st['option'] = {tag: option_account(D, tr, oseg, spread_x=sx, k=kk) for tag, sx, kk in (('v2', 1, .05), ('cons', 2, 0.0))}
        out[nm] = st
        print('VALIDATE', nm, json.dumps({a: (round(b, 4) if isinstance(b, float) else b) for a, b in st.items()
                                          if a in ('n', 'win', 'avg', 't', 'placebo', 'years')}),
              'option', {k_: round(v['total'], 3) for k_, v in st['option'].items()}, flush=True)
    (REPORTS / f'validate_{report.replace(".json", "")}.json').write_text(json.dumps(out, indent=1, default=float),
                                                                          encoding='utf-8')
    return out


if __name__ == '__main__':
    if sys.argv[1] == 'round':
        round_(sys.argv[2])
    elif sys.argv[1] == 'validate':
        validate(sys.argv[2])
