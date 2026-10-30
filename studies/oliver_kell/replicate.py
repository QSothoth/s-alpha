"""Oliver Kell through skills/trader-replication, on the same machinery as the Flanders study (entries, stop modes,
pools, the generic loop); only his stages and numbers differ.

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/opend-us-options/.venv/bin/python"
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
    cutoff = '2024-07-01'           # PREREG_R1 (ledger v2): selection = trades whose window starts before this day
    full = ('2023-04-03', '2026-10-16')
    home = ('us',)
    his = {}                        # his championship year (2020) is outside the data
    starts = ('2023-04-03', '2023-05-01', '2023-06-01', '2023-09-01', '2024-01-02', '2025-01-02')
    base = DRAFT

    def named(self, A, pool, name):
        if name.startswith('idxhalf'):                   # risk x0.5 while the pool index closed below its EMA n
            from studies.trader_screens.scan import index_above
            return np.where(lag(index_above(A['F'], int(name[7:]))), 1.0, .5)
        F = A['F']
        if name.startswith('below_ema'):                 # close below the EMA n (his half-off-at-the-10 stop)
            with np.errstate(invalid='ignore'):
                return F.c < F.ema(int(name[9:]))
        if name.startswith('ext10_'):                    # close k% above the 10-day line ("30% above the 10-day")
            with np.errstate(invalid='ignore'):
                return F.c >= (1 + int(name[6:]) / 100) * F.sma(10)
        return super().named(A, pool, name)

    def setups(self, A, cfg):
        F = A['F']
        out = super().setups(A, dict(cfg, setups=[s for s in cfg.get('setups', [])
                                                  if s in ('ep', 'brk52', 'pp', 'vcp', 'pb')]))
        names = cfg.get('setups', ['pop', 'cross'])
        st = S.OliverKell().run(F)['setups']
        if 'pop' in names:                               # bought at the close that reclaims the higher EMA
            x = [s for s in st if s.name == 'Wedge Pop'][0]
            line = np.fmax(F.ema(10), F.ema(20))
            out['pop'] = (x.mask, np.where(x.mask, line, np.nan), F.l)
        if 'cross' in names:
            x = [s for s in st if s.name == 'EMA Crossback' and s.kind == 'triggered'][0]
            out['cross'] = (x.mask, x.price, F.l)
        pool = lag(self.pool(A, cfg))
        with np.errstate(invalid='ignore'):
            if 'ib2' in names:                           # two inside days in a row, then a break of the mother bar
                inside = (F.h <= lag(F.h)) & (F.l >= lag(F.l))
                ready = inside & lag(inside)
                mother = lag(F.h, 2)
                m = pool & lag(ready) & (F.h > lag(mother)) & (F.c > F.ema(20))
                out['ib2'] = (m, np.fmax(F.o, lag(mother)), F.l)
            if 'ur' in names:                            # undercut and rally: yesterday closed below the 20 EMA
                e20 = F.ema(20)                          # after an up cycle, today closes back above it
                m = pool & lag(F.c < e20) & (F.c > e20) & lag(F.ema(10) > e20, 3) & (F.c > F.sma(50))
                out['ur'] = (m, e20, F.l)
        return out

    def kind_pools(self, A, cfg, kinds):
        """pop / cross run the board's screens.OliverKell, whose floors are fixed there (20M, ADR >= 3%), not the
        configured pool's 100M."""
        out = super().kind_pools(A, cfg, kinds)
        F = A['F']
        with np.errstate(invalid='ignore'):
            for k in ('pop', 'cross'):
                if k in kinds:
                    out[k] = lag(F.liquid(20e6) & (F.adr >= 3))
        return out

    def intraday_kinds(self, cfg, kinds):
        return tuple(k for k in super().intraday_kinds(cfg, kinds) if k != 'pop')     # the pop fills at the close

    def entries(self, A, cfg, masks):
        """The pop is a close signal: its draft fill is the close (the level is only the line it reclaimed)."""
        out = super().entries(A, cfg, masks)
        if cfg.get('entry', 'level') in ('level', 'level_pess') and 'pop' in masks:
            c = A['close']
            out = [[e if e[5] != 'pop' else (e[0], e[1], e[2], float(c[d, e[1]]),
                                              float(min(A['low'][d, e[1]], c[d, e[1]] * (1 - cfg.get('stop_min', .01)))),
                                              e[5], None) for e in lst] for d, lst in enumerate(out)]
        return out


    def short_setups(self, A, sc):
        """His short side (RULES ⑨; OK6, OK7), the board's Wedge Pop / EMA Crossback turned over, close-confirmed:

        drop     Wedge Drop: within the last `ext_days` (10) sessions before t the close was at least `ext` (30%,
                 his own measure of "extended": the long side sells a third 30% above the 10-day line) above the
                 10-day line, yesterday closed at or above the lower of the 10 / 20 EMA and today closes below it
        dcross   Downside EMA Crossback: 2-20 sessions after a Wedge Drop, still under the 20 EMA (a close above it
                 ends the drop), the first rally whose high reaches the falling 10 EMA and closes back under the
                 20 EMA ('ready'); the short is the close of a later day (within 5) that closes below that rally
                 day's low (the board's trigger over the ready day's high, mirrored)
        Pool: 20-day turnover >= `turnover` (100M, his long pool R6 A5) and price >= 5, ADR >= 3, as of t-1."""
        F = A['F']
        with np.errstate(invalid='ignore', divide='ignore'):
            pool = lag(F.liquid(sc.get('turnover', 100e6)) & (F.adr >= sc.get('adr', 3.0)))
            e10, e20 = F.ema(10), F.ema(20)
            bottom = np.fmin(e10, e20)
            ext = F.c >= (1 + sc.get('ext', .30)) * F.sma(10)
            n = sc.get('ext_days', 10)
            was_ext = np.zeros(ext.shape, bool)
            for k in range(1, n + 1):
                was_ext |= lag(ext, k)
            drop = pool & was_ext & (lag(F.c) >= lag(bottom)) & (F.c < bottom)
            ready_day = (F.h >= e10) & (F.c < e20) & (e10 < lag(e10))
            above20 = F.c > e20
        ready = np.zeros_like(drop)
        after = np.zeros_like(drop)                      # day t: a Wedge Drop 1-20 sessions back, not undone (t-1)
        since, used = np.full(drop.shape[1], -1), np.zeros(drop.shape[1], bool)
        for t in range(len(drop)):
            after[t] = (since >= 0) & (t - since >= 1) & (t - since <= 20)
            live = (since >= 0) & (t - since >= 2) & (t - since <= 20)
            ready[t] = live & ~used & ready_day[t]
            used |= ready[t]
            dead = above20[t] & (since >= 0) & (t > since)
            since = np.where(drop[t], t, np.where(dead, -1, since))
            used = np.where(drop[t] | dead, False, used)
        trig = np.zeros_like(drop)
        level, at = np.full(drop.shape[1], np.nan), np.full(drop.shape[1], -99)
        for t in range(len(drop)):                        # a later close under the ready day's low (within 5 days)
            with np.errstate(invalid='ignore'):
                trig[t] = (t - at >= 1) & (t - at <= 5) & (F.c[t] < level) & pool[t]
            at = np.where(trig[t], -99, at)               # once
            at, level = np.where(ready[t], t, at), np.where(ready[t], F.l[t], level)
        out = {}
        names = sc.get('setups', ['drop', 'dcross'])
        if 'drop' in names:
            out['drop'] = drop
        if 'dcross' in names:
            out['dcross'] = trig
        # S2 (his CAVA short, K42: "short CAVA today on the rejection at 50SMA ... my stop is today's high"): the
        # rally into a falling line after a Wedge Drop as a sell-short limit at the previous day's line, decided at
        # that close (shorts.level_entries): under the line yesterday, the line falling
        with np.errstate(invalid='ignore'):
            for name, line in (('lim20', e20), ('lim10', e10), ('lim50', F.sma(50))):
                if name in names:
                    armed = pool & after & lag((F.c < line) & (line < lag(line)))
                    out[name] = dict(armed=armed, level=lag(line))
        return out, pool


STUDY = Kell()

if __name__ == '__main__':
    study.main(STUDY, sys.argv)
