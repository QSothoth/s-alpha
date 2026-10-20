"""Layer 2 of the three-layer check for Martin's shorts: his dated shorts (his tickers, his days) with our daily
execution variants, each trade sized on its own (no caps).  Prints per-trade R and the mean."""
import sys
from dataclasses import replace

import numpy as np

from studies.trader_replication import systems as SY, shorts as SH, fidelity as F, panels, system as Y

x = SY.get('martin_luk')
st = x.study
A = st.arrays('us')
inside = [t for t in st.trades() if t.side == 'short' and t.dated and panels.WINDOW[0] <= t.entry_date <= panels.WINDOW[1]]
loc = F.locate(inside, A['days'], A['codes'], prefix='US.', has=A['has'])[0]
di = {str(d): i for i, d in enumerate(A['days'])}
o, h, l, c = A['open'], A['high'], A['low'], A['close']
e9p = np.vstack([np.full((1, c.shape[1]), np.nan), A['e9'][:-1]])


def entries(mode):
    out = [[] for _ in A['days']]
    for t, j, a, b in loc:
        d = di.get(t.entry_date)
        if d is None:
            continue
        if mode == 'close':                                  # our execution: the close, stop the day's high
            fill, stop = c[d, j], max(h[d, j], c[d, j] * 1.01)
        elif mode == 'e9':                                   # at the prior 9 EMA when the day traded there
            if not (h[d, j] >= e9p[d, j] >= l[d, j]):
                continue
            fill, stop = e9p[d, j], max(h[d, j], e9p[d, j] * 1.01)
        elif mode == 'open':                                 # the open, stop the day's high (LOOK-AHEAD: the high
            fill, stop = o[d, j], max(h[d, j], o[d, j] * 1.01)  # is known only after the fill; diagnostic only)
        elif mode == 'limit9':                               # sell-short limit at the prior 9 EMA (shorts.py level
            lv = e9p[d, j]                                   # entry): exact on daily bars
            if not (o[d, j] < lv <= h[d, j]):
                continue
            w = SH.level_width(A, {}, d, j)
            out[d].append((0.0, j, -1, float(lv), float(lv * (1 + w)), 'his', float(lv * (1 + w))
                           if h[d, j] >= lv * (1 + w) else None))
            continue
        out[d].append((0.0, j, -1, float(fill), float(stop), 'his'))
    return out


_, rules, _, pool = st.build(A, x.config)
base = replace(rules, max_open=0, max_new_long=0, max_gross=1e9, max_position=1e9, feedback=0, risk_scale='',
               margin_rate=0.0, management_by_kind={'his': {'trail': 'e9', 'trims': ()}}, short_trims=(),
               short_max_days=0, borrow_rate=.03)
variants = {'close / trail e9': base,
            'close / day2 half + trail e9': replace(base, short_trim_day=2, short_trim_day_frac=.5),
            'close / 3 days': replace(base, short_max_days=3),
            'e9 level / trail e9': base, 'open / trail e9': base, 'limit9 / trail e9': base,
            'limit9 / day2 half + trail e9': replace(base, short_trim_day=2, short_trim_day_frac=.5)}
for name, rules_ in variants.items():
    mode = name.split(' /')[0].replace(' level', '')
    if mode in ('e9', 'open'):
        name += ' (look-ahead)'
    e = entries(mode)
    _, _, tr = Y.simulate(st.px(A), st.ema_inputs(A, pool, rules_), rules_, e, *panels.WINDOW)
    r = np.array([t['r'] for t in tr])
    print(f'{name:32s} n {len(r)} mean R {r.mean():+.2f} median {np.median(r):+.2f} win {(r > 0).mean():.2f} '
          f'sum R {r.sum():+.1f}', sorted([(t['code'][3:], t['entry'], round(t['r'], 1)) for t in tr],
                                         key=lambda z: z[1]) if 'trail e9' == name.split('/ ')[1] and mode == 'close' else '')
