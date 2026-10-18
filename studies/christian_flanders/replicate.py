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

EP = dict(gap=.10, rvol=0.0, near=None, far_low=None)   # gap >= 10% (his "ideally 10% or more"); the rest optional
PP = dict(gain=1.0, flag=10, depth=.25)     # up 100% within 40 days, then a flag of at most 25% (Minervini's power play)


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
    def pool_dependent(self, name):
        return name == 'sig_all'

    def named(self, A, pool, name):
        F = A['F']
        if name == 'sig_all':
            return A['sig_all']
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
            if A['market'] == 'us' and p.get('price', 5.0) != 5.0:
                m = (F.to20 >= p.get('turnover', 20e6)) & (F.raw >= p['price']) & (F.adr >= p.get('adr', 3.0))
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
        pool = lag(self.pool(A, cfg))                         # known before the day's trades
        if 'ep' in names:
            o = dict(EP, **cfg.get('ep', {}))
            with np.errstate(invalid='ignore', divide='ignore'):
                m = F.o / lag(F.c) - 1 >= o['gap']
                if o['rvol']:
                    m &= F.turnover >= o['rvol'] * lag(F.to20)      # the whole day's turnover: known at the close
                if o['near'] is not None:
                    m &= F.o >= (1 - o['near']) * lag(F.hi(252))   # gaps into (or near) the 52-week high
                if o['far_low'] is not None:                         # not an EP near the lows (a new listing:
                    low = np.fmin.accumulate(np.where(np.isnan(F.l), np.inf, F.l), axis=0)   # its lowest so far)
                    low = np.where(np.isfinite(F.lo(252)), F.lo(252), low)
                    m &= F.o >= (1 + o['far_low']) * lag(low)
                m &= lag(self.ep_pool(A, cfg))
            out['ep'] = (m, F.o, F.l)
        with np.errstate(invalid='ignore', divide='ignore'):
            if 'brk52' in names:                                    # any break of the prior 52-week high
                prior = lag(F.hi(252))
                m = pool & (F.h > prior)
                out['brk52'] = (m, np.fmax(F.o, prior), F.l)
            if 'pp' in names:                                       # power play / high tight flag
                o = dict(PP, **cfg.get('pp', {}))
                flag_hi = lag(F.hi(o['flag']))
                m = (pool & lag(F.hi(40) / F.lo(40) >= 1 + o['gain'])
                     & lag(F.range(o['flag']) <= o['depth'] * 100) & lag(F.c >= (1 - o['depth']) * F.hi(40))
                     & (F.h > flag_hi))
                out['pp'] = (m, np.fmax(F.o, flag_hi), F.l)
            if 'pb' in names:                                       # pullback into the 10 / 20 EMA, then its high
                e10, e20 = F.ema(10), F.ema(20)
                ready = (F.l <= e10 * 1.01) & (F.c >= e20) & (e10 > e20) & (F.c > F.sma(50))
                level = lag(F.h)
                m = pool & lag(ready) & (F.h > level)
                out['pb'] = (m, np.fmax(F.o, level), F.l)
            if 'vcp' in names:                                      # contractions with supply drying up
                pivot = lag(F.hi(10))
                ready = ((F.range(5) < F.range(5, 5)) & (F.range(5, 5) < F.range(10, 10)) & (F.range(5) <= 10)
                         & (F.vol(10) < F.vol(50)) & (F.c >= .95 * F.hi(10)))
                m = pool & lag(ready) & (F.h > pivot)
                out['vcp'] = (m, np.fmax(F.o, pivot), F.l)
        return out

    def ep_pool(self, A, cfg):
        """Names an EP can come from: the pool's turnover and price floors only (an EP may gap from below its
        50-day; his liquidity worry is the spread, not the trend)."""
        p = cfg.get('ep_pool', cfg.get('pool', {}))
        F = A['F']
        with np.errstate(invalid='ignore'):
            return (F.to20 >= p.get('turnover', 20e6)) & (F.raw >= p.get('price', 5.0)) if A['market'] == 'us' \
                else F.liquid(0)

    def entries(self, A, cfg, masks):
        F = A['F']
        c, l, o = F.c, F.l, F.o
        mode, smin, cap = cfg.get('entry', 'level'), cfg.get('stop_min', .01), cfg.get('stop_cap', 0.0)
        prio = self.priority(A, cfg)
        out = [[] for _ in range(len(c))]
        for kind, (m, level, stop) in masks.items():
            mode = cfg.get('entry_by_kind', {}).get(kind, cfg.get('entry', 'level'))
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
                pr = pr if np.isfinite(pr) else 0.0
                if cfg.get('ep_first'):
                    pr = pr - 10.0 * (kind == 'ep')             # the day's EPs before its breakouts
                out[d].append((pr, int(j), 1, float(fill), float(s), kind, exit0))
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
        masks = {k: (m & ok, lv, st) for k, (m, lv, st) in self.setups(A, cfg).items()}   # each carries its pool
        mask = np.zeros(pool.shape, bool)
        for m, _, _ in masks.values():
            mask |= m
        A['sig_all'] = mask                        # a new buy point on a name already held: his pyramid adds
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
