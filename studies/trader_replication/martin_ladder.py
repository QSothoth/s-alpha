"""Walking back from his answer: the account on his own dated longs, then step by step the system's own choices, so the
step where the result falls is the step to fix.  Hindsight on purpose in the first steps: a measurement, not a candidate.

    $PY -m studies.trader_replication.martin_ladder
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np

from . import panels, review as RV, systems as SY

WINDOW = panels.WINDOW


def main():
    W, cfg = SY.get('martin_luk').load()
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    reg, rules, mask, pool = W.build(A, cfg)
    wide, *_ = W.build(A, {**cfg, 'max_new': 0})
    di = {str(d): i for i, d in enumerate(A['days'])}
    his = [(t, j, a, z) for t, j, a, z in base.located(A, base.trades()) if t.side == 'long' and t.dated and t.entry_date >= '2024-01-02' and t.entry_date in di]
    mine = [[] for _ in A['days']]
    for t, j, a, z in his:
        d = di[t.entry_date]
        x = base.his_entry(A, d, j, cfg)
        if x is not None and not any(e[1] == j for e in mine[d]):
            mine[d].append(((-1.0,),) + tuple(x[1:]))
    pri = lambda e: ((1.0,) + (e[0] if isinstance(e[0], tuple) else (e[0],)),) + tuple(e[1:])
    nocap = replace(rules, max_new_long=0, max_new_by_kind={})
    keep = lambda lst, n: lst[:n]
    def merged(sig, n):
        out = []
        for d, lst in enumerate(sig):
            lon = sorted((pri(e) for e in lst if e[2] > 0 and not any(m[1] == e[1] for m in mine[d])), key=lambda e: e[0])
            room = max(0, n - len(mine[d]))
            out.append(mine[d] + lon[:room] + [pri(e) for e in lst if e[2] <= 0])
        return out
    steps = dict(S0_his_only=(mine, nocap), S1_his_then_system4=(merged(wide, 4), nocap), S2_system_only=(reg, rules))
    out = {}
    for k, (e, ru) in steps.items():
        st, tr = base.run(A, e, WINDOW, pool, ru, placebo=0, audit=True)
        st.pop('_curve', None)
        b = st['behaviour']
        o = {(t['code'], t['entry']): t for t in tr if t['side'] > 0}
        sel = [x for x in his if x[0].entry_date <= '2025-12-31']
        got = sum(any((str(A['codes'][j]), str(A['days'][d])) in o for d in range(a, z + 1)) for t, j, a, z in sel)
        win, trades = {}, {}
        for y in ('2024', '2025', '2026'):
            t = [x for x in tr if x['entry'][:4] == y and x['side'] > 0]
            trades[y] = len(t)
        r = out[k] = dict(by_year=st['by_year'], maxdd=st['maxdd'], win=b['win'], avg_win=b['avg_win'], avg_loss=b['avg_loss'], days_win=b['days_win'], trades=trades, bought_sel=got, of=len(sel))
        print(k, {y: round(v, 2) for y, v in st['by_year'].items()}, f"dd {st['maxdd']:.2f} win {b['win']:.3f} aw {b['avg_win']:+.3f} al {b['avg_loss']:+.3f} dw {b['days_win']:.1f} trades {trades} bought {got}/{len(sel)}", flush=True)
    RV.write('martin_ladder.json', out)


if __name__ == '__main__':
    main()
