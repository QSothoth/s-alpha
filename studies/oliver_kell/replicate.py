"""Oliver Kell through skills/trader-replication, on the same machinery as the Flanders study (entries, stop modes,
pools, the generic loop); only his stages and numbers differ.

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.oliver_kell.replicate round R1

The starting point (DRAFT) is the board's draft (studies/trader_screens/screens.py OliverKell + its book): the Wedge
Pop (a close back above the 10 / 20 EMA after a contraction, 20-day turnover >= 20M, ADR >= 3%) and the EMA
Crossback (the first pullback to the 10 EMA after a pop that holds the 20, bought over that day's high); stop at the
day's low, 0.5% risk (halved while the pool index closed below its 20 EMA the day before), 30% per name, 100%
gross, 2 a day, 8 open, out on a close below the 20 EMA.  His rules and sources: notes/RULES_CN.md; his trades:
notes/trades.csv.
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
    setups=['pop', 'cross'],
    entry='level', stop_min=.01, stop_cap=0.0, priority='strength', max_new=2, strength='', filter='',
    pool=dict(turnover=20e6, adr=3.0, above50=False),
    rule_opts=dict(risk=.005, max_position=.30, max_gross=1.0, max_open=8, trail='ema20', arm_trail_on_entry=True,
                   trims=(), risk_scale='idxhalf20'),
)


class Kell(CF.Flanders):
    id, name = 'oliver_kell', 'Oliver Kell'
    root = ROOT / 'studies' / 'oliver_kell'
    ledger = root / 'notes' / 'trades.csv'
    cutoff = '2025-01-01'           # PREREG_R1: selection = trades whose window starts before this day
    full = ('2023-04-03', '2026-10-16')
    home = ('us',)
    his = {}                        # his championship year (2020) is outside the data
    starts = ('2023-04-03', '2023-05-01', '2023-06-01', '2023-09-01', '2024-01-02', '2025-01-02')
    base = DRAFT

    def named(self, A, pool, name):
        if name.startswith('idxhalf'):                   # risk x0.5 while the pool index closed below its EMA n
            from studies.trader_screens.scan import index_above
            return np.where(lag(index_above(A['F'], int(name[7:]))), 1.0, .5)
        return super().named(A, pool, name)

    def setups(self, A, cfg):
        F = A['F']
        out = super().setups(A, dict(cfg, setups=[s for s in cfg.get('setups', [])
                                                  if s in ('ep', 'brk52', 'pp', 'vcp')]))
        names = cfg.get('setups', ['pop', 'cross'])
        st = S.OliverKell().run(F)['setups']
        if 'pop' in names:                               # bought at the close that reclaims the higher EMA
            x = [s for s in st if s.name == 'Wedge Pop'][0]
            line = np.fmax(F.ema(10), F.ema(20))
            out['pop'] = (x.mask, np.where(x.mask, line, np.nan), F.l)
        if 'cross' in names:
            x = [s for s in st if s.name == 'EMA Crossback' and s.kind == 'triggered'][0]
            out['cross'] = (x.mask, x.price, F.l)
        return out

    def entries(self, A, cfg, masks):
        """The pop is a close signal: its draft fill is the close (the level is only the line it reclaimed)."""
        out = super().entries(A, cfg, masks)
        if cfg.get('entry', 'level') in ('level', 'level_pess') and 'pop' in masks:
            c = A['close']
            out = [[e if e[5] != 'pop' else (e[0], e[1], e[2], float(c[d, e[1]]),
                                              float(min(A['low'][d, e[1]], c[d, e[1]] * (1 - cfg.get('stop_min', .01)))),
                                              e[5], None) for e in lst] for d, lst in enumerate(out)]
        return out


STUDY = Kell()

if __name__ == '__main__':
    study.main(STUDY, sys.argv)
