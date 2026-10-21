"""Diagnosis for human.py rounds: the selection-segment account split by entry kind and year (trades, winners,
profit) for H0 or round configurations.

    $PY -m studies.trader_replication.human_kinds <system> <report> <key | H0> ...
"""
import json
import sys

from . import human as H, systems as SY

if __name__ == '__main__':
    sid, rep = sys.argv[1], sys.argv[2]
    st, reg = SY.get(sid).load()
    A = st.arrays('us')
    r = json.loads((st.reports / rep).read_text(encoding='utf-8'))
    for k in sys.argv[3:]:
        cfg = H.h0_cfg(reg) if k == 'H0' else r['configs'][k]
        v = H.run(st, A, cfg, H.SELECT)
        print(k, {q: (z['n'], z['wins'], round(z['pnl'], 3)) for q, z in v['kinds'].items()}, flush=True)
