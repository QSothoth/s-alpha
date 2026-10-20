"""Why Qullamaggie's R7 X1 wins 37.8% (he says 25%): his closed longs by exit path and size of the result, and the
same for the provisional Q5C shorts; then R7 X1 with the day-3 breakeven off, to see how much of the win rate is
the 'sell half on day 3 and move the stop to the fill' rule (diagnostic only, not a round)."""
import json
from collections import Counter
from dataclasses import replace

import numpy as np

from studies.trader_replication import systems as SY, shorts as SH, panels, system as Y

x = SY.get('qullamaggie')
st, cfg = x.load()
long_cfg = SH.split_cfg(cfg)[0]
A = st.arrays('us')


def path(t):
    acts = [e['action'] for e in t['executions'] if e['action'] not in ('entry', 'end')]
    return '+'.join(dict.fromkeys(acts))


def show(tag, tr, side):
    cl = [t for t in tr if t['side'] == side and t['why'] != 'end']
    ret = np.array([t['ret'] for t in cl])
    print(f'\n== {tag}: {len(cl)} closed, win {np.mean(ret > 0):.3f}, tiny wins (0 < ret < 1%) '
          f'{np.mean((ret > 0) & (ret < .01)):.3f}, wins >= 5% {np.mean(ret >= .05):.3f}')
    by = Counter()
    win = Counter()
    for t in cl:
        by[path(t)] += 1
        win[path(t)] += t['ret'] > 0
    for k, n in by.most_common(8):
        r = np.array([t['ret'] for t in cl if path(t) == k])
        print(f'  {k:28s} n {n:4d} win {win[k] / n:.2f} median ret {np.median(r):+.4f}')


e, rules, mask, pool = st.build(A, long_cfg)
_, _, tr = SH.run(st, A, e, rules, pool)
show('R7 X1 longs', tr, 1)
r2 = replace(rules, trim_day_breakeven=False)
_, _, tr2 = SH.run(st, A, e, r2, pool)
show('R7 X1 longs, no breakeven after the day-3 half (diagnostic)', tr2, 1)
sc = json.load(open(st.reports / 's5.json'))['configs']['Q5C']
e, rules, mask, pool = st.build(A, dict(long_cfg, short=sc))
_, _, tr3 = SH.run(st, A, e, rules, pool)
show('Q5C shorts', tr3, -1)
