"""Clement Ang through skills/trader-replication, on the same machinery as the Flanders study (entries, stop
modes, pools, the generic loop); only his stages and numbers differ.

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.clement_ang.replicate round R1

The starting point (DRAFT) is the board's draft (studies/trader_screens/screens.py ClementAng + its book): the
2026 wide screen (above the 50 / 200-day, 20-day turnover >= 50M, ADR >= 3%), the fine screen (ADR >= 4%, within
10% of the 52-week high, < 4 ATR above the 50-day, 5-day range <= 2 ADR), bought over yesterday's high unless
already 0.6 ATR above the day's low, stop at the day's low, 0.3% risk, 30% per name, 100% gross, 2 a day, 8 open,
out on a close below the 20-day.  His rules and sources: notes/RULES_CN.md; his trades: notes/trades.csv.
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
    setups=['fine'],
    entry='level', stop_min=.01, stop_cap=0.0, priority='strength', max_new=2, strength='', filter='',
    pool=dict(turnover=50e6, adr=3.0, above50=True),
    rule_opts=dict(risk=.003, max_position=.30, max_gross=1.0, max_open=8, trail='sma20', arm_trail_on_entry=True,
                   trims=()),
)
FINE = dict(adr=4.0, near=.10, atr50=4.0, tight=2.0)   # the board's fine screen (CA1 + researcher values)


class Clement(CF.Flanders):
    id, name = 'clement_ang', 'Clement Ang'
    root = ROOT / 'studies' / 'clement_ang'
    ledger = root / 'notes' / 'trades.csv'
    cutoff = '2026-01-01'           # PREREG_R1: selection = trades whose window starts before this day
    full = ('2024-01-02', '2026-10-16')
    home = ('us',)
    his = {'2024': dict(ret=.793, win=.30, avg_win=.054, avg_loss=-.021, days_win=3, days_loss=.8, per_year=800),
           '2025': dict(ret=1.404, win=.30, avg_win=.054, avg_loss=-.021, days_win=3, days_loss=.8, per_year=1294)}
    base = DRAFT

    def setups(self, A, cfg):
        F = A['F']
        out = {k: v for k, v in super().setups(A, dict(cfg, setups=[s for s in cfg.get('setups', [])
                                                                     if s in ('ep', 'brk52', 'pp', 'vcp')])).items()}
        names = cfg.get('setups', ['fine'])
        if 'fine' in names and not cfg.get('fine'):
            st = [x for x in S.ClementAng().run(F)['setups'] if x.kind == 'triggered'][0]
            out['fine'] = (st.mask & ~st.skip, st.price, F.l)
        elif 'fine' in names:                                   # the board's fine screen with its researcher values
            o = dict(FINE, **cfg['fine'])                       # replaced (near the high, tightness, extension)
            adr, atr = F.adr, F.atr14
            p = cfg.get('pool', {})
            with np.errstate(invalid='ignore'):
                wide = ((F.c > F.sma(50)) & (F.c > F.sma(200)) & F.liquid(p.get('turnover', 50e6))
                        & (adr >= p.get('adr', 3.0)))
                fine = (wide & (adr >= o['adr']) & (F.c >= (1 - o['near']) * F.hi(252))
                        & ((F.c - F.sma(50)) < o['atr50'] * atr) & (F.range(5) <= o['tight'] * adr))
            trig, entry = S.triggered_from(F, fine, F.h)
            with np.errstate(invalid='ignore'):
                chase = entry - F.l > .6 * lag(atr)
            out['fine'] = (trig & ~chase, entry, F.l)
        if 'pb' in names:                                       # pullback into the 10 / 20 EMA in an up cycle
            e10, e20, s50 = F.ema(10), F.ema(20), F.sma(50)
            with np.errstate(invalid='ignore'):
                ready = (F.l <= e10 * 1.01) & (F.c >= e20) & (e10 > e20) & (F.c > s50)
                o = cfg.get('pb', {})
                if o.get('fine'):                               # only names on his fine list: ADR, near the
                    f = dict(FINE, **cfg.get('fine', {}))       # high, not extended from the 50-day
                    ready &= ((F.c > F.sma(200)) & (F.adr >= f['adr']) & (F.c >= (1 - f['near']) * F.hi(252))
                              & ((F.c - s50) < f['atr50'] * F.atr14))
                if o.get('rs'):                                 # composite RS percentile at least this
                    ready &= self.rs(A) >= o['rs'] / 100
                pool = lag(self.pool(A, cfg))
                level = lag(F.h)
                m = pool & lag(ready) & (F.h > level)
            out['pb'] = (m, np.fmax(F.o, level), F.l)
        if cfg.get('rs_phase'):                                 # his RS phase, as of the day before
            ok = lag(self.rs_phase(F))
            out = {k: (v[0] & ok if k in ('fine', 'pb') else v[0], v[1], v[2]) for k, v in out.items()}
        return out

    @staticmethod
    def rs_phase(F):
        """The relative-strength line (close / the pool's equal-weight index) above its own 21-day EMA, and that
        EMA rising (zw96@01:31:01)."""
        def f():
            prev = lag(F.c)
            with np.errstate(invalid='ignore', divide='ignore'):
                r = np.where(F.rank_pool & np.isfinite(prev), F.c / prev - 1, np.nan)
                idx = np.cumprod(1 + np.nan_to_num(np.nanmean(r, axis=1)))[:, None]
                line = F.c / idx
                e = S.ema(line, 21)
                return (line > e) & (e > lag(e))
        return F.get('rs_phase', f)


STUDY = Clement()

if __name__ == '__main__':
    study.main(STUDY, sys.argv)
