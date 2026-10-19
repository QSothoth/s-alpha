"""Qullamaggie (Kristjan Kullamägi) through skills/trader-replication, on the same machinery as the Flanders study
(entries, stop modes, pools, the generic loop); only his stages and numbers differ.

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.qullamaggie.replicate round R1

The starting point (DRAFT) is the board's draft (studies/trader_screens/screens.py Qullamaggie + its book): leaders
(top 2% of the 1 / 3 / 6-month return percentiles, 20-day turnover >= 20M, ADR >= 4%) breaking a 10-day tightening
base, and EPs (gap >= 10% on 3x the 20-day volume); stop at the day's low, skipped when wider than 1 ADR (EP 1.5);
0.5% risk, 30% per name, 100% gross, 3 a day, 10 open; a third sold on day 3 when in profit, the rest out on a
close below the 10-day line.  His rules and sources: notes/RULES_CN.md; his trades: notes/trades.csv.
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
    setups=['brk', 'ep'],
    entry='level', stop_min=.01, stop_cap=0.0, priority='strength', max_new=3, strength='', filter='',
    stop_adr={'brk': 1.0, 'ep': 1.5},          # S01: the stop no wider than the ADR (S04: EP usually 1, at most 1.5)
    pool=dict(turnover=20e6, adr=4.0, above50=False),
    rule_opts=dict(risk=.005, max_position=.30, max_gross=1.0, max_open=10, trail='sma10', arm_trail_on_entry=True,
                   trims=(), trim_day=3, trim_day_frac=1 / 3, trim_day_profit=True),
)


class Qullamaggie(CF.Flanders):
    id, name = 'qullamaggie', 'Qullamaggie'
    root = ROOT / 'studies' / 'qullamaggie'
    ledger = root / 'notes' / 'trades.csv'
    cutoff = '2023-06-01'           # PREREG_R0: selection = trades whose window starts before this day
    full = ('2023-02-01', '2026-10-16')     # 21 sessions in: the 1-month leg of his strength exists
    home = ('us',)
    his = {}                        # no audited year inside the data
    his_behaviour = dict(win=.25)   # S03: 25% win rate in 2019
    starts = ('2023-02-01', '2023-04-03', '2023-06-01', '2023-09-01', '2024-01-02', '2025-01-02')
    base = DRAFT

    def setups(self, A, cfg):
        F = A['F']
        out = super().setups(A, dict(cfg, setups=[s for s in cfg.get('setups', [])
                                                  if s in ('brk52', 'pp', 'vcp')]))
        names = cfg.get('setups', ['brk', 'ep'])
        st = S.Qullamaggie().run(F)['setups']
        if 'brk' in names:
            x = [s for s in st if s.kind == 'triggered' and s.name == '突破'][0]
            out['brk'] = (x.mask, x.price, F.l)
        if 'ep' in names:
            x = [s for s in st if s.name == 'EP'][0]
            m = x.mask
            o = cfg.get('ep', {})
            with np.errstate(invalid='ignore', divide='ignore'):
                if 'min_gap' in o or 'liquid' in o or 'heavy' in o:   # the board's EP with its values replaced
                    m = (F.liquid(o.get('liquid', 20e6)) & (F.o / lag(F.c) - 1 >= o.get('min_gap', .10))
                         & (F.v >= o.get('heavy', 3.0) * lag(F.vol(20))))
                if o.get('quiet'):                              # S01: not up in the prior months
                    m = m & lag(F.ret(63) < o['quiet'])
                if o.get('gap'):
                    m = m & (F.o / lag(F.c) - 1 >= o['gap'])
            out['ep'] = (m, x.price, F.l)
        return out

    def market_ok(self, A, cfg):
        """'light': his green light on the pool's equal-weight index (QQQ in his words): the 10-day line above the
        20-day and both rising, as of the day before (1AJIzXSkfyM@00:35:30, VdQSDGZBLQE@00:55:30)."""
        if cfg.get('filter') not in ('light', 'light_q'):
            return super().market_ok(A, cfg)
        F = A['F']
        weighted = cfg.get('filter') == 'light_q'       # 'light_q': the pool weighted by t-1 turnover, a QQQ-like

        def f():                                        # large-cap index (he reads the QQQ; no ETF in the panel)
            prev = lag(F.c)
            with np.errstate(invalid='ignore', divide='ignore'):
                ok = F.rank_pool & np.isfinite(prev)
                r = np.where(ok, F.c / prev - 1, np.nan)
                if weighted:
                    w = np.where(ok & np.isfinite(r), lag(F.to20), 0.0)
                    w = np.nan_to_num(w)
                    mean = (np.nan_to_num(r) * w).sum(axis=1) / np.maximum(w.sum(axis=1), 1e-9)
                else:
                    mean = np.nan_to_num(np.nanmean(r, axis=1))
                idx = np.cumprod(1 + mean)
            s10, s20 = S.rolling(idx[:, None], 10, 'mean')[:, 0], S.rolling(idx[:, None], 20, 'mean')[:, 0]
            with np.errstate(invalid='ignore'):
                return (s10 > s20) & (s10 > lag(s10)) & (s20 > lag(s20))
        return lag(F.get(('qull_light', weighted), f))

    def named(self, A, pool, name):
        """'lighthalf': risk x1 on a green light (as of the day before), x0.5 otherwise ("fewer trades or smaller
        size", 1AJIzXSkfyM@00:36:30)."""
        if name == 'lighthalf':
            return np.where(self.market_ok(A, dict(filter='light')), 1.0, .5)
        return super().named(A, pool, name)

    def entries(self, A, cfg, masks):
        """The draft's entries, then his stop-width rule on the actual fill: skip when (fill - stop) / fill is wider
        than stop_adr[kind] ADRs as of the day before."""
        out = super().entries(A, cfg, masks)
        caps = cfg.get('stop_adr', {})
        if not caps:
            return out
        adr = lag(A['F'].adr)
        keep = []
        for d, lst in enumerate(out):
            keep.append([e for e in lst if e[5] not in caps or not np.isfinite(adr[d, e[1]])
                         or (e[3] - e[4]) / e[3] <= caps[e[5]] * adr[d, e[1]] / 100])
        return keep


STUDY = Qullamaggie()

if __name__ == '__main__':
    study.main(STUDY, sys.argv)
