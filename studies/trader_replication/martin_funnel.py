"""Where each of his dated longs falls in M1: evening rank, did the day come back to a support, what the bar looked like."""
import numpy as np
from . import review as RV, systems as SY, ticket_t4 as T4, watchlist as WL
from .martin_list import ema
from .martin_m1 import CACHE
W, cfg = SY.get('martin_luk').load(); base = getattr(W, 'base', W); A = base.arrays('us')
_, rules, mask, pool = W.build(A, cfg); rk = T4.ranks(A, pool); s = np.load(CACHE).astype(float)
o, h, l, c = (A[k].astype(float) for k in ('open', 'high', 'low', 'close'))
e9, e21 = ema(c, 9), ema(c, 21); rng = WL.roll_mean(h / l - 1, 20)
gate = base.market_gate(A, cfg)
di = {str(d): i for i, d in enumerate(A['days'])}
rows = []
for t, j, a, z in base.located(A, base.trades()):
    if t.side != 'long' or not t.dated or t.entry_date < '2024-01-02' or t.entry_date not in di: continue
    d = di[t.entry_date]; v = s[d]
    place = int((v > v[j]).sum()) if np.isfinite(v[j]) else None
    lv = [x for x in (e9[d-1, j], e21[d-1, j], h[d-2, j]) if np.isfinite(x) and x < c[d-1, j]]
    L = max(lv) if lv else np.nan
    a_ = rng[d-1, j]
    rows.append(dict(id=t.id, tk=t.ticker, day=t.entry_date, setup=t.setup, list=bool(rk[d, j] < 100), place=place, gate=bool(gate[d-1]) if gate is not None else True,
      has_lv=bool(lv), touch=bool(lv and l[d, j] <= L), open_ok=bool(lv and o[d, j] >= L), gap=float((o[d,j]/c[d-1,j]-1)/a_), low_pe9=float((l[d,j]/e9[d-1,j]-1)/a_), up=float((c[d,j]/c[d-1,j]-1)/a_), over_pdh=bool(h[d,j]>h[d-1,j]), close_pos=float((c[d,j]-l[d,j])/(h[d,j]-l[d,j]+1e-9)), low_to_close=float(c[d,j]/l[d,j]-1)))
n = len(rows); m = lambda f: sum(1 for r in rows if f(r))
top = lambda r: r['place'] is not None and r['place'] < 20
print('n', n, 'list', m(lambda r: r['list']), 'top20', m(top), 'gate', m(lambda r: r['gate']), 'touch&open', m(lambda r: r['touch'] and r['open_ok']), 'top20&touch', m(lambda r: top(r) and r['touch'] and r['open_ok']))
print('over PDH', m(lambda r: r['over_pdh']), 'gap>0.5adr', m(lambda r: r['gap'] > .5), 'low below prevE9', m(lambda r: r['low_pe9'] <= 0), 'close top third', m(lambda r: r['close_pos'] > .67))
for k in ('gap', 'low_pe9', 'up', 'close_pos', 'low_to_close'):
    x = np.array([r[k] for r in rows if np.isfinite(r[k])]); print(k, 'q25/50/75', np.round(np.percentile(x, [25, 50, 75]), 3))
for st in sorted({r['setup'] for r in rows}):
    R = [r for r in rows if r['setup'] == st]
    print(st, len(R), 'touch', sum(r['touch'] and r['open_ok'] for r in R), 'overPDH', sum(r['over_pdh'] for r in R), 'gap>.5', sum(r['gap'] > .5 for r in R), 'lowtoclose med', round(float(np.nanmedian([r['low_to_close'] for r in R])), 3))
RV.write('martin_funnel.json', rows)
