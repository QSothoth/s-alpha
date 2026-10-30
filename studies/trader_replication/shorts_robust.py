"""Sensitivity of a round's carried long-short configuration (reported only, never used to choose): each variant
changes one thing in the short side (or the costs) and reruns the three accounts without placebo.

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/opend-us-options/.venv/bin/python"
    $PY -m studies.trader_replication.shorts_robust martin_luk s4.json
"""
from __future__ import annotations

import json
import sys

from . import shorts as SH, study as ST

VARIANTS = {'base': {}, 'borrow 6%': {'borrow': .06}, 'short risk x0.5': {'risk_mult': .5},
            'only below EMA50': {'gate': 'below50'}, 'costs x2': {'_costs': 2}}


def main(trader, report):
    sysx, st, long_cfg = SH.study_of(trader)
    res = json.loads((st.reports / report).read_text(encoding='utf-8'))
    long_cfg = res.get('long_config', long_cfg)                 # the longs the round ran with
    key = res['chosen'] if res['chosen'] in res['configs'] else res.get('provisional')
    sc0 = res['configs'][key] if key in res['configs'] else res['chosen_short']
    A = st.arrays('us')
    out = {}
    for name, ch in VARIANTS.items():
        sc = ST.merged(sc0, {k: v for k, v in ch.items() if not k.startswith('_')})
        cfg = dict(long_cfg, short=sc)
        if ch.get('_costs'):
            ro = dict(cfg.get('rule_opts', {}))
            ro.update(buy_cost=ST.COSTS['us'][0] * 2, sell_cost=ST.COSTS['us'][1] * 2)
            cfg['rule_opts'] = ro
        r = SH.evaluate(st, A, cfg, draws=0)
        out[name] = dict(both=r['both']['total'], long=r['long']['total'], short=r['short']['total'],
                         both_years=r['both']['by_year'], long_years=r['long']['by_year'],
                         maxdd=[r['both']['maxdd'], r['long']['maxdd']], down=r['down']['total'],
                         short_pnl_in_both=r['both_short']['pnl'])
        print(trader, report, name, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in out[name].items()},
              flush=True)
    res['robust'] = out
    (st.reports / report).write_text(json.dumps(res, indent=1, default=float), encoding='utf-8')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
