"""Mark Minervini through skills/trader-replication, on the same machinery as the Flanders study (entries, stop
modes, pools, the generic loop); only his stages and numbers differ.

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.mark_minervini.replicate round R1

The starting point (DRAFT) is the board's draft (studies/trader_screens/screens.py MarkMinervini + its book): the
trend template (price above the 50 / 150 / 200-day in that order, the 200-day rising for a month, >= 30% above the
52-week low, within 25% of the high, RS >= 70) with 20-day turnover >= 20M, a volatility contraction (three
shrinking ranges, the last <= 10%, volume drying up, within 5% of the 10-day high) bought over the pivot (10-day
high); stop at the base low, at most 8% ('base' stop; the corrected entry uses the day's low), 0.5% risk, 30% per
name, 100% gross, 2 a day, 8 open, out on a close below the 50-day.  His rules and sources: notes/RULES_CN.md; his
trades: notes/trades.csv.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from studies.christian_flanders import replicate as CF
from studies.trader_replication import study
from studies.trader_screens import screens as S

ROOT = Path(__file__).resolve().parents[2]
lag = S.lag

DRAFT = dict(
    setups=['vcp_mm'],
    entry='level', stop_min=.01, stop_cap=0.0, priority='strength', max_new=2, strength='', filter='',
    stop='base',                     # 'base': the draft's base low, at most 8% | 'day': the entry day's low
    pool=dict(turnover=20e6, adr=0.0, above50=False),
    rule_opts=dict(risk=.005, max_position=.30, max_gross=1.0, max_open=8, trail='sma50', arm_trail_on_entry=True,
                   trims=()),
)


class Minervini(CF.Flanders):
    id, name = 'mark_minervini', 'Mark Minervini'
    root = ROOT / 'studies' / 'mark_minervini'
    ledger = root / 'notes' / 'trades.csv'
    cutoff = '2025-01-01'           # PREREG_R0: selection = trades whose window starts before this day
    full = ('2024-01-02', '2026-10-16')   # the template needs the 200-day line rising for a month
    home = ('us',)
    his = {}                        # his championship year (2021) is outside the data
    base = DRAFT

    def setups(self, A, cfg):
        F = A['F']
        out = super().setups(A, dict(cfg, setups=[s for s in cfg.get('setups', [])
                                                  if s in ('ep', 'brk52', 'pp', 'vcp')]))
        if 'vcp_mm' in cfg.get('setups', ['vcp_mm']):
            x = [s for s in S.MarkMinervini().run(F)['setups'] if s.kind == 'triggered'][0]
            out['vcp_mm'] = (x.mask, x.price, x.stop)
        return out

    def entries(self, A, cfg, masks):
        """'close' entries take the day's low as the stop (the corrected entry); with stop 'base' the draft's base
        low (at most 8% below the fill) replaces it."""
        out = super().entries(A, cfg, masks)
        if cfg.get('stop', 'base') != 'base' or 'vcp_mm' not in masks or cfg.get('entry', 'level') == 'level':
            return out                                   # 'level' already carries the draft's base stop
        base_low = lag(A['F'].lo(10))
        res = []
        for d, lst in enumerate(out):
            row = []
            for e in lst:
                if e[5] == 'vcp_mm' and np.isfinite(base_low[d, e[1]]):
                    s = min(max(base_low[d, e[1]], e[3] * .92), e[3] * (1 - cfg.get('stop_min', .01)))
                    e = (e[0], e[1], e[2], e[3], float(s), e[5], e[6])
                row.append(e)
            res.append(row)
        return res


STUDY = Minervini()

if __name__ == '__main__':
    study.main(STUDY, sys.argv)
