"""Diagnostics of the R7 configuration (selection-chosen, validation already seen): all quarters with placebo,
the contest-start leverage variant, and P&L concentration. Writes reports/diag_r7.json. Report only."""
import json
import os

import numpy as np

from . import engine as E
from .replicate import REPORTS, cfg_of, evaluate, market, override


def concentration(trades):
    pnl = np.sort(np.array([t.pnl for t in trades]))[::-1]
    tot = pnl.sum()
    return dict(top5_share=round(float(pnl[:5].sum() / tot), 2) if tot > 0 else None,
                best_day=max((sum(t.pnl for t in trades if t.date == d), d) for d in {t.date for t in trades})[1])


def main():
    with open(os.path.join(REPORTS, 'r7.json'), encoding='utf-8') as f:
        chosen = cfg_of(json.load(f)['chosen_cfg'])
    mk = market()
    qs = E.SELECT + E.VALIDATE
    out = {}
    for name, cfg in (('r7', chosen), ('r7_S300', override(chosen, dict(lev_hi=300.0, lev_until=10.0))),
                      ('r7_cost2', override(chosen, dict(cost_pts=2.0)))):
        rows = evaluate(mk, cfg, qs, draws=100)
        for q in qs:
            _, tr = E.quarter(mk, cfg, q)
            rows[q].update(concentration(tr))
        out[name] = rows
        for q, r in rows.items():
            print(name, q, {k: r.get(k) for k in ('ret', 'his', 'share', 'n', 'win', 'avg_win_pts', 'avg_loss_pts',
                                                  'pts_total', 'per_active_day', 'active_share', 'hold_med',
                                                  'placebo_med', 'placebo_pct', 'top5_share')})
    with open(os.path.join(REPORTS, 'diag_r7.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=1, default=float)


if __name__ == '__main__':
    main()
