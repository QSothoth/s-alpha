"""T6, a diagnosis on the hourly list (81 names picked with hindsight, so only the comparison inside it means anything):
the same evening list and the same exits, buying the close signal against touching the prior-day high with a stop at
the day's low so far (1%-3% below).  Which one has the shape of his 940 trades (22% win, +14% / -2.1%)?

    $PY -m studies.trader_replication.ticket_t6
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np

from studies import trader_data as TD

from . import panels, review as RV, systems as SY, ticket_t4 as T4

WINDOW = panels.WINDOW
LO, HI = .01, .03


def touches(A, rk, K, ok_day, hourly_ok=None):
    h = TD.load_hourly('us', mode='frozen')
    hc = {str(c): i for i, c in enumerate(h['codes'])}
    bd = h['days'].astype(str)
    idx = {}
    for i, d in enumerate(bd):
        idx.setdefault(d, []).append(i)
    codes = [str(c) for c in A['codes']]
    cols = {j: hc[c] for j, c in enumerate(codes) if c in hc}
    out = [[] for _ in A['days']]
    ema = np.full(A['close'].shape, np.nan)
    c = A['close'].astype(float)
    with np.errstate(all='ignore'):
        ema[20:] = np.array([np.nanmean(c[i - 19:i + 1], axis=0) for i in range(20, len(c))])
    for d in range(21, len(A['days'])):
        day = str(A['days'][d])
        if day < '2023-12-01' or day not in idx or (ok_day is not None and not ok_day[d]):
            continue
        bars = np.array(idx[day])
        for j, k in cols.items():
            if rk[d, j] >= K or not c[d - 1, j] > ema[d - 1, j]:
                continue
            hi, lo = h['high'][bars, k].astype(float), h['low'][bars, k].astype(float)
            fin = np.isfinite(hi)
            if not fin.any():
                continue
            hi, lo, cl = hi[fin], lo[fin], h['close'][bars, k][fin].astype(float)
            s = c[d, j] / cl[-1]
            hi, lo = hi * s, lo * s
            ph, o = A['high'][d - 1, j], A['open'][d, j]
            at = np.flatnonzero(hi >= ph)
            if not len(at):
                continue
            t = at[0]
            fill = max(o, ph)
            low = lo[:t + 1].min()
            stop = min(max(low, fill * (1 - HI)), fill * (1 - LO))
            stopped = lo[t] < stop or (lo[t + 1:] <= stop).any()
            e = (float(-(fill - stop)), j, 1, float(fill), float(stop), 'his')
            out[d].append(e + ((float(stop),) if stopped else ()))
    return out, set(cols)


def top(e, n):
    return [sorted(x, key=lambda v: v[0])[:n] for x in e]


def main():
    W, cfg = SY.get('martin_luk').load()
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    wide, rules, mask, pool = W.build(A, {**cfg, 'max_new': 0})
    rk = T4.ranks(A, pool)
    gate = base.market_gate(A, cfg)
    his = [x for x in base.located(A, base.trades()) if '2024-01-02' <= x[0].entry_date <= '2025-12-31' and x[0].side == 'long']
    tou, names = touches(A, rk, 100, gate)
    codes = set(names)
    close = [[e for e in lst if e[2] > 0 and e[1] in codes and rk[d, e[1]] < 100] for d, lst in enumerate(wide)]
    out = {}
    for k, e, pos, n in (('close_17', close, .17, 8), ('touch_17', tou, .17, 8), ('touch_30', tou, .30, 4), ('touch_17_3', tou, .17, 3)):
        ru = replace(rules, max_new_long=0, max_new_by_kind={}, max_position=pos)
        st, tr = base.run(A, top(e, n), WINDOW, pool, ru, placebo=0, audit=True)
        st.pop('_curve', None)
        b = st['behaviour']
        o = {(t['code'], t['entry']) for t in tr if t['side'] > 0}
        got = sum(any((str(A['codes'][j]), str(A['days'][d])) in o for d in range(a, z + 1)) for t, j, a, z in his)
        E = b['win'] * b['avg_win'] + (1 - b['win']) * b['avg_loss']
        out[k] = dict(by_year=st['by_year'], maxdd=st['maxdd'], per_year=b['per_year'], win=b['win'], avg_win=b['avg_win'], avg_loss=b['avg_loss'],
                      days_win=b['days_win'], bought=got, E=E)
        print(k, {y: round(v, 2) for y, v in st['by_year'].items()}, f"dd {st['maxdd']:.2f} n/yr {b['per_year']:.0f} win {b['win']:.3f} aw {b['avg_win']:+.3f} al {b['avg_loss']:+.3f} E {E*100:.2f}% dw {b['days_win']:.1f} bought {got}/{len(his)}", flush=True)
        RV.write('ticket_martin_luk_T6.json', out)


if __name__ == '__main__':
    main()
