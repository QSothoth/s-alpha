"""Same-pool random entries for one Flanders ticket-round candidate; reports/gap_review/placebo_flanders_<key>.json

    $PY -m studies.trader_replication.ticket_placebo L8 L8C
"""
from __future__ import annotations

import sys
from dataclasses import replace

from . import panels, review as RV, systems as SY, ticket_flanders as F, ticket_t4 as T4


def main(name, key):
    W, cfg = SY.get('christian_flanders').load()
    base = getattr(W, 'base', W)
    A = base.arrays('us')
    c, K, free, first, change = F.ROUNDS[name][key][:5]
    e, rules, mask, pool = W.build(A, {**cfg, **c})
    rk = T4.ranks(A, pool)
    e = F.keep(e, rk, K, free)

    def pr(x, d):
        if first == 2 and x[5] == 'ep':
            return -2e7
        if x[2] > 0 and rk[d, x[1]] < K:
            return float(rk[d, x[1]] - 10 ** 7)
        return float(x[0]) if not isinstance(x[0], tuple) else 0.0
    e = [[(pr(x, d),) + x[1:] for x in lst] for d, lst in enumerate(e)]
    st, tr = base.run(A, e, panels.WINDOW, pool, replace(rules, **change), placebo=100, audit=False)
    print('RESULT', key, st['total'], st.get('placebo'), flush=True)
    RV.write(f'placebo_flanders_{key}.json', dict(total=st['total'], placebo=st.get('placebo')))


if __name__ == '__main__':
    main(*sys.argv[1:3])
