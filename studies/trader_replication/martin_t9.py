"""T9 (martin_luk/notes/PREREG_T9.md): the day's strongest names of the evening list, on Martin's own exits.

    $PY -m studies.trader_replication.martin_t9
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np

from . import panels, review as RV, systems as SY, ticket_t4 as T4
from .martin_list import ema

WINDOW = panels.WINDOW
K = 100


def score(A, rk):
    c, h, l = (A[k].astype(float) for k in ('close', 'high', 'low'))
    with np.errstate(all='ignore'):
        rng = T4.WL.roll_mean(h / l - 1, 20)
        rng = np.vstack([np.full((1, c.shape[1]), np.nan), rng[:-1]])
        prev = np.vstack([np.full((1, c.shape[1]), np.nan), c[:-1]])
        ph = np.vstack([np.full((1, c.shape[1]), np.nan), h[:-1]])
        back = np.vstack([np.full((20, c.shape[1]), np.nan), c[:-20]])
        e9 = ema(c, 9)
        parts = [(c / prev - 1) / rng, (c / ph - 1) / rng, (c / e9 - 1) / rng, c / back - 1]
    s = np.full(c.shape, np.nan)
    for d in range(len(c)):
        n = np.flatnonzero(rk[d] < K)
        if len(n) < 10:
            continue
        p = np.zeros(len(n))
        for x in parts:
            v = x[d, n]
            ok = np.isfinite(v)
            q = np.zeros(len(n))
            if ok.any():
                q[ok] = (v[ok][:, None] > v[ok]).mean(1)
            p += q
        s[d, n] = p / len(parts)
    return s, parts


def entries(A, s, parts, n, gate):
    c, l = A['close'].astype(float), A['low'].astype(float)
    out = []
    for d in range(len(c)):
        row = []
        if gate is None or gate[d]:
            v = np.where(np.isfinite(s[d]) & (parts[0][d] > 0) & (parts[1][d] > 0), s[d], -1.0)
            for j in np.argsort(-v)[:n]:
                if v[j] > 0:
                    stop = min(max(l[d, j], c[d, j] * .95), c[d, j] * .99)
                    row.append((float(-v[j]), int(j), 1, float(c[d, j]), float(stop), 'list'))
        out.append(row)
    return out


def next_day(A, s, parts, n, width, gate):
    """Tomorrow's buy stop at today's high: filled at max(open, high), the stop a fixed width below the fill; with daily
    bars a day that reaches both counts as stopped."""
    o, h, l = (A[k].astype(float) for k in ('open', 'high', 'low'))
    out = [[] for _ in range(len(o))]
    for d in range(len(o) - 1):
        if gate is not None and not gate[d]:
            continue
        v = np.where(np.isfinite(s[d]) & (parts[0][d] > 0) & (parts[1][d] > 0), s[d], -1.0)
        for j in np.argsort(-v)[:n]:
            j = int(j)
            t = d + 1
            if v[j] <= 0 or not np.isfinite(h[t, j]) or h[t, j] < h[d, j]:
                continue
            fill = float(max(o[t, j], h[d, j]))
            stop = fill * (1 - width)
            e = ((float(-v[j]),), j, 1, fill, float(stop), 'list')
            out[t].append(e + ((float(min(o[t, j], stop)),) if l[t, j] <= stop else ()))
    return out


def main10():
    W, cfg = SY.get('martin_luk').load()
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    reg, rules, mask, pool = W.build(A, cfg)
    rk = T4.ranks(A, pool)
    s, parts = score(A, rk)
    gate = base.market_gate(A, cfg)
    his = [x for x in base.located(A, base.trades()) if '2024-01-02' <= x[0].entry_date <= '2025-12-31' and x[0].side == 'long']
    shorts = [[e for e in lst if e[2] <= 0] for lst in reg]
    out = dict(tickets=len(his), results={})
    for k, c in dict(REG=None, T10A=(3, .025), T10B=(3, .03), T10C=(5, .03), T10D=(5, .04), T10E=(8, .03)).items():
        e = reg if c is None else [a + b for a, b in zip(next_day(A, s, parts, c[0], c[1], gate), shorts)]
        st, tr = base.run(A, e, WINDOW, pool, rules, placebo=0, audit=True)
        st.pop('_curve', None)
        b = st['behaviour']
        o = {(t['code'], t['entry']): t for t in tr if t['side'] > 0}
        got = {}
        for t, j, a, z in his:
            for d in range(a, z + 1):
                x = o.get((str(A['codes'][j]), str(A['days'][d])))
                if x:
                    got[t.id] = (t.ticker, round(x['ret'], 3))
        r = out['results'][k] = dict(by_year=st['by_year'], maxdd=st['maxdd'], per_year=b['per_year'], win=b['win'], avg_win=b['avg_win'], avg_loss=b['avg_loss'], days_win=b['days_win'], bought=len(got), got=got)
        print(k, {y: round(v, 2) for y, v in r['by_year'].items()}, f"dd {r['maxdd']:.2f} n/y {r['per_year']:.0f} win {r['win']:.3f} aw {r['avg_win']:+.3f} al {r['avg_loss']:+.3f} dw {r['days_win']:.1f} bought {r['bought']}/{len(his)}", flush=True)
        RV.write('ticket_martin_luk_T10.json', out)


def main():
    W, cfg = SY.get('martin_luk').load()
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    reg, rules, mask, pool = W.build(A, cfg)
    rk = T4.ranks(A, pool)
    s, parts = score(A, rk)
    gate = base.market_gate(A, cfg)
    his = [x for x in base.located(A, base.trades()) if '2024-01-02' <= x[0].entry_date <= '2025-12-31' and x[0].side == 'long']
    shorts = [[e for e in lst if e[2] <= 0] for lst in reg]
    out = dict(tickets=len(his), results={})
    for k, c in dict(REG=None, T9A=(1, {}), T9B=(2, {}), T9C=(3, {}), T9D=(4, {}), T9E=(4, dict(max_position=.3))).items():
        if c is None:
            e, ru = reg, rules
        else:
            ent = entries(A, s, parts, c[0], gate)
            e, ru = [a + b for a, b in zip(ent, shorts)], replace(rules, **c[1])
        st, tr = base.run(A, e, WINDOW, pool, ru, placebo=0, audit=True)
        st.pop('_curve', None)
        b = st['behaviour']
        o = {(t['code'], t['entry']): t for t in tr if t['side'] > 0}
        got = {}
        for t, j, a, z in his:
            for d in range(a, z + 1):
                x = o.get((str(A['codes'][j]), str(A['days'][d])))
                if x:
                    got[t.id] = (t.ticker, round(x['ret'], 3))
        rets = [v[1] for v in got.values()]
        r = out['results'][k] = dict(by_year=st['by_year'], maxdd=st['maxdd'], per_year=b['per_year'], win=b['win'], avg_win=b['avg_win'], avg_loss=b['avg_loss'], days_win=b['days_win'], bought=len(got), ticket_mean=float(np.mean(rets)) if rets else None, got=got)
        print(k, {y: round(v, 2) for y, v in r['by_year'].items()}, f"dd {r['maxdd']:.2f} n/y {r['per_year']:.0f} win {r['win']:.3f} aw {r['avg_win']:+.3f} al {r['avg_loss']:+.3f} dw {r['days_win']:.1f} bought {r['bought']}/{len(his)} tmean {r['ticket_mean']}", flush=True)
        RV.write('ticket_martin_luk_T9.json', out)


if __name__ == '__main__':
    main10()
