"""Christian Flanders through skills/trader-replication: his stages as masks on the research daily panels, the
configuration a round JSON changes, and the generic loop of studies.trader_replication.study.

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.christian_flanders.replicate round R1
    $PY -m studies.christian_flanders.replicate diagnose r1.json
    $PY -m studies.christian_flanders.replicate three r1.json

The starting point (DRAFT) is the board's draft (studies/trader_screens/screens.py ChristianFlanders + its book):
the 52-week-high breakout after a 10-day base, bought at the level, stop at the day's low, 0.25% risk, 30% per
name, 100% gross, 2 a day, 8 open, out on a close below the 10-day line.  Everything on day t uses bars up to t;
a fill at the trigger level with the day's low as stop is the draft's daily approximation of his opening-range
entries (entry 'level'); 'level_pess' counts every such day that closes below the fill as stopped at that low the
same day (the pessimistic bound), 'close' buys the close, 'open_pct' buys the open with a fixed stop below it
(both exact on daily bars).  His rules and sources: notes/RULES_CN.md; his trades: notes/trades.csv.
"""
from __future__ import annotations

from dataclasses import replace
import sys
from pathlib import Path

import numpy as np

from studies.trader_replication import panels, study, system as Y
from studies.trader_screens import screens as S

ROOT = Path(__file__).resolve().parents[2]
lag = S.lag

DRAFT = dict(
    setups=['hi52'],                 # screens.ChristianFlanders: break of the 52-week high after a 10-day base
    entry='level',                   # fill at the level (or the open above it), stop at the day's low
    stop_min=.01,                    # the stop is at least 1% below the fill (the board's researcher value)
    stop_cap=0.0,                    # > 0: a stop wider than this is moved up to it
    priority='strength',             # highest 1/3/6-month return percentile as of t-1 (the board's ranking)
    max_new=2,                       # successful new longs a day
    strength='',                     # '' | 'rs<NN>': composite RS percentile >= NN as of t-1 | 'up100': close >= 2x 52-week low
    filter='',                       # '' | 'IDX<n>': pool equal-weight index closed above its EMA n the day before
    rule_opts=dict(risk=.0025, max_position=.30, max_gross=1.0, max_open=8, trail='sma10', arm_trail_on_entry=True,
                   trims=()),
)

EP = dict(gap=.10, rvol=0.0, near=None)     # gap >= 10% (his "ideally 10% or more"); rvol, near: optional


class Flanders(study.Study):
    id, name = 'christian_flanders', 'Christian Flanders'
    root = ROOT / 'studies' / 'christian_flanders'
    ledger = root / 'notes' / 'trades.csv'
    cutoff = '2025-06-01'           # PREREG_R1: selection = trades whose window starts before this day
    full = ('2024-01-02', '2026-10-16')
    home = ('us',)
    his = {'2024': dict(ret=4.335, win=.308, avg_win=.118, avg_loss=-.0335, days_win=11, days_loss=1.9,
                        per_year=400),
           '2025': dict(ret=1.675, win=.305, avg_win=.1744, avg_loss=-.0455, days_win=17, days_loss=2.1,
                        per_year=489)}
    base = DRAFT

    def arrays(self, market):
        return panels.arrays(market)

    # ----- named day arrays the engine reads -----
    def named(self, A, pool, name):
        F = A['F']
        if name.startswith('sma'):
            return F.sma(int(name[3:]))
        if name.startswith('ema'):
            return F.ema(int(name[3:]))
        if name.startswith('atr50x'):                    # his yellow dot: close k ATRs above the 50-day
            k = float(name[6:])
            with np.errstate(invalid='ignore'):
                return (F.c - F.sma(50)) >= k * F.atr14
        if name.startswith('ext200_'):                   # O'Neal: 120% above the 200-day
            k = float(name[7:]) / 100
            with np.errstate(invalid='ignore'):
                return F.c >= (1 + k) * F.sma(200)
        raise KeyError(name)

    # ----- stages -----
    def pool(self, A, cfg):
        """The draft pool: 20-day turnover >= 20M USD and price >= 5 (US), ADR >= 3%, close above the 50-day."""
        F = A['F']
        p = cfg.get('pool', {})
        with np.errstate(invalid='ignore'):
            m = F.liquid(p.get('turnover', 20e6)) & (F.adr >= p.get('adr', 3.0))
            if p.get('above50', True):
                m &= F.c > F.sma(50)
        return m

    def strength_ok(self, A, cfg):
        F, s = A['F'], cfg.get('strength', '')
        if not s:
            return np.ones(F.c.shape, bool)
        if s.startswith('rs'):
            return lag(self.rs(A)) >= int(s[2:]) / 100
        if s == 'up100':
            with np.errstate(invalid='ignore'):
                return lag(F.c >= 2 * F.lo(252))
        raise ValueError(s)

    def rs(self, A):
        F = A['F']
        return F.rank('rs', .4 * F.ret(63) + .2 * F.ret(126) + .2 * F.ret(189) + .2 * F.ret(252))

    def setups(self, A, cfg):
        """name -> (mask, level or fill, stop) of day-t triggers."""
        F = A['F']
        out = {}
        names = cfg.get('setups', ['hi52'])
        if 'hi52' in names:
            st = [x for x in S.ChristianFlanders().run(F)['setups'] if x.kind == 'triggered'][0]
            out['hi52'] = (st.mask, st.price, F.l)
        if 'ep' in names:
            o = dict(EP, **cfg.get('ep', {}))
            with np.errstate(invalid='ignore', divide='ignore'):
                m = F.o / lag(F.c) - 1 >= o['gap']
                if o['rvol']:
                    m &= F.turnover >= o['rvol'] * lag(F.to20)      # the whole day's turnover: known at the close
                if o['near'] is not None:
                    m &= F.o >= (1 - o['near']) * lag(F.hi(252))
                m &= F.liquid(cfg.get('pool', {}).get('turnover', 20e6))
            out['ep'] = (m, F.o, F.l)
        return out

    def entries(self, A, cfg, masks):
        F = A['F']
        c, l, o = F.c, F.l, F.o
        mode, smin, cap = cfg.get('entry', 'level'), cfg.get('stop_min', .01), cfg.get('stop_cap', 0.0)
        prio = self.priority(A, cfg)
        out = [[] for _ in range(len(c))]
        for kind, (m, level, stop) in masks.items():
            for d, j in zip(*np.nonzero(m)):
                if d == 0 or not np.isfinite(c[d, j]):
                    continue
                pct = cfg.get('open_pct', .06)
                if mode in ('level', 'level_pess'):
                    fill, s = level[d, j], stop[d, j]
                elif mode == 'close':
                    fill, s = c[d, j], l[d, j]
                    if kind != 'ep' and not c[d, j] > level[d, j]:
                        continue                                   # close-confirmed breakout
                elif mode == 'open_pct':
                    fill = max(o[d, j], level[d, j]) if kind != 'ep' else o[d, j]
                    s = fill * (1 - pct)
                else:
                    raise ValueError(mode)
                if not (np.isfinite(fill) and np.isfinite(s) and fill > 0):
                    continue
                s = min(s, fill * (1 - smin))
                if cap:
                    s = max(s, fill * (1 - cap))
                exit0 = None
                if mode == 'level_pess' and c[d, j] < fill:
                    exit0 = s                                      # assume the low came after the fill
                elif mode == 'open_pct' and l[d, j] <= s:
                    exit0 = s                                      # a fixed stop below the open: exact
                pr = prio[d, j]
                out[d].append((pr if np.isfinite(pr) else 0.0, int(j), 1, float(fill), float(s), kind, exit0))
        return out

    def priority(self, A, cfg):
        """Lower goes first."""
        p = cfg.get('priority', 'strength')
        if p == 'strength':
            return -lag(S.strength(A['F']))
        if p == 'rs':
            return -lag(self.rs(A))
        if p == 'rvol':
            return -(A['F'].turnover / lag(A['F'].to20))
        raise ValueError(p)

    def market_ok(self, A, cfg):
        f = cfg.get('filter', '')
        if not f:
            return None
        from studies.trader_screens.scan import index_above
        return lag(index_above(A['F'], int(f[3:])))

    def build(self, A, cfg, trace=None):
        pool = self.pool(A, cfg)
        ok = self.strength_ok(A, cfg)
        masks = {k: (m & ok & (pool if k != 'ep' else True), lv, st) for k, (m, lv, st) in self.setups(A, cfg).items()}
        mask = np.zeros(pool.shape, bool)
        for m, _, _ in masks.values():
            mask |= m
        entries = self.entries(A, cfg, masks)
        if trace is not None:
            trace.update(pool=pool, strength=ok, **{f'setup_{k}': m for k, (m, _, _) in masks.items()})
            trace['raw'] = entries
        gate = self.market_ok(A, cfg)
        if gate is not None:
            entries = [e if gate[d] else [] for d, e in enumerate(entries)]
        if trace is not None:
            trace['filtered'] = entries
            trace['capped'] = entries              # the daily cap is the engine's (successful opens, as the board)
        costs = study.COSTS[A['market']]
        ro = {k: tuple(v) if isinstance(v, list) else v for k, v in cfg.get('rule_opts', {}).items()}
        rules = replace(Y.Rules(), buy_cost=costs[0], sell_cost=costs[1], max_new_long=cfg.get('max_new', 0), **ro)
        placebo_pool = pool | (masks['ep'][0] if 'ep' in masks else False)
        return entries, rules, mask, placebo_pool

    def his_entry(self, A, d, j, cfg):
        """His ticker on his day with our execution: the close, stop at the day's low (at least stop_min)."""
        c, l = A['close'][d, j], A['low'][d, j]
        if not (np.isfinite(c) and np.isfinite(l) and c > 0):
            return None
        return (0.0, j, 1, c, min(l, c * (1 - cfg.get('stop_min', .01))), 'his')


STUDY = Flanders()

if __name__ == '__main__':
    study.main(STUDY, sys.argv)
