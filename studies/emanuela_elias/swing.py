"""Emanuela Elias as she describes her own trading in The Trader Reset (notes/RULES_CN.md, second part): a daily-chart
swing trader in a small list of active names.  Interested long once a stock is back above its weekly 50 SMA and well
above the daily 150 / 200 SMA; two setups -- the pullback (after a breakout has set the trend, candles tighten against
the 10 / 20 EMA, in on the reclaim of the daily 10 EMA) and the base breakout (after a sharp drop, a base whose floor
buyers defend, in on the break of its top, stop under the base); out when price is extended from the 10 EMA (the end
of a leg), at two targets at most, or when the 20 EMA / the setup's floor breaks.

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.emanuela_elias.swing round E1
    $PY -m studies.emanuela_elias.swing ledger e1.json          # her dated trades: did we have the signal?

Same engine, data (trader-data-v1 through the data interface) and option account as replicate.py.
"""
from __future__ import annotations

import json
import sys

import numpy as np

from studies.emanuela_elias.replicate import Emanuela, lag, SELECT, VALIDATE
from studies.trader_replication import system as Y

SWING = dict(
    sides=['long'],
    pool=dict(price=10.0, turnover=200e6),     # active names (her list: HIMS, RDDT, CVNA, PYPL, PLTR, AVGO, AAPL ...)
    trend=dict(sma_long=250, sma_daily=200),   # above the weekly 50 SMA (~250 sessions) and the daily 200 SMA
    setups=['pullback', 'base'],
    pullback=dict(breakout=50, within=20, touch=.01, tight=.85),   # a 50-day high in the last 20 sessions; the low
    base=dict(drop=.20, high=60, days=10, width=.15),             # near the 20 EMA (1%); ATR5 <= 0.85 ATR20
    stop_floor=5,                              # pullback stop: the lowest low of the last 5 sessions
    min_stop=.02,
    ext=2.5,                                   # out once the close is more than 2.5 ATR14 above the 10 EMA
    rule_opts=dict(risk=.02, max_position=.25, max_gross=1.5, max_open=6, trail='e20', trims=(2,), trim_frac=.5,
                   max_days=0, short_max_days=0, borrow_rate=.03),
    max_new=3,
    opt=dict(dte=30, mny=0.0, frac=.05, spread=.01, v2=True, k=.05),   # "bought enough time": ~30-day calls
)


class Swing(Emanuela):
    base = SWING

    def pool(self, A, cfg):
        F = A['F']
        p = cfg.get('pool', {})
        with np.errstate(invalid='ignore'):
            return (F.raw >= p.get('price', 10.0)) & (F.to20 >= p.get('turnover', 200e6)) & np.isfinite(F.c)

    def build(self, A, cfg, trace=None):
        F = A['F']
        c, h, l = F.c, F.h, F.l
        e10, e20 = F.ema(10), F.ema(20)
        atr = F.atr14
        tr = cfg['trend']
        with np.errstate(invalid='ignore', divide='ignore'):
            trend = c > F.sma(tr['sma_long'])
            if tr.get('sma_daily'):                               # E2: None drops the daily 200 SMA filter
                trend = trend & (c > F.sma(tr['sma_daily']))
            pool = lag(self.pool(A, cfg))
            entries = [[] for _ in range(len(c))]
            mask = np.zeros(c.shape, bool)
            if 'pullback' in cfg['setups']:
                pb = cfg['pullback']
                hi_n = F.hi(pb['breakout'])
                made_high = np.zeros(c.shape, bool)               # a new n-day high within the last `within` sessions
                newhigh = h >= hi_n
                for k in range(pb['within']):
                    made_high |= newhigh if k == 0 else lag(newhigh, k)
                near = np.zeros(c.shape, bool)                    # the pullback reached the 20 EMA zone lately
                for k in range(3):
                    near |= (l <= e20 * (1 + pb["touch"])) if k == 0 else lag(l <= e20 * (1 + pb["touch"]), k)
                atr5 = self._atr(A, 5)
                tight = atr5 <= pb['tight'] * self._atr(A, 20)
                reclaim = (c > e10) & (lag(c) <= lag(e10))         # the daily close back above the 10 EMA
                if pb.get('trigger') == 'bounce':                 # E2: or the day's low on the 10 EMA, the close
                    reclaim = reclaim | ((l <= e10) & (c > e10))   # above it (her hourly entry off the daily EMA)
                if not pb.get('need_high', True):                 # E2: no recent breakout required
                    made_high = np.ones(c.shape, bool)
                m = pool & trend & made_high & near & tight & reclaim
                stop = np.fmin(F.lo(cfg['stop_floor']), c * (1 - cfg['min_stop']))
                self._add(entries, mask, m, F, stop, 'pb')
            if 'base' in cfg['setups']:
                bs = cfg['base']
                hi_prior = lag(F.hi(bs['high']), bs['days'])     # the high before the base
                b_hi, b_lo = lag(F.hi(bs['days'])), lag(F.lo(bs['days']))
                dropped = b_lo <= hi_prior * (1 - bs['drop'])
                flat = b_hi <= b_lo * (1 + bs['width'])
                brk = (c > b_hi) & (lag(c) <= b_hi)
                m = pool & (c > F.sma(tr['sma_daily'])) & dropped & flat & brk if bs.get('trend') \
                    else pool & dropped & flat & brk
                stop = np.fmin(b_lo * .995, c * (1 - cfg['min_stop']))
                self._add(entries, mask, m, F, stop, 'bb')
        ro = dict(cfg.get('rule_opts', {}))
        ro['trims'] = tuple(ro.get('trims', ()))
        rules = Y.Rules(**ro, exit_signal='x_ext', max_new_all=cfg.get('max_new', 3))
        A['kind_pools'] = None
        A['_ext'] = cfg.get('ext', 2.5)
        return entries, rules, mask, pool

    @staticmethod
    def _add(entries, mask, m, F, stop, kind):
        mask |= m
        for d, j in zip(*np.nonzero(m)):
            f, st = float(F.c[d, j]), float(stop[d, j])
            if np.isfinite(st) and st < f:
                entries[d].append((-float(F.to20[d - 1, j]), int(j), 1, f, st, kind))

    def _atr(self, A, n):
        F = A['F']
        return F.get(('atr', n), lambda: _rolling_tr(F, n))

    def named(self, A, pool, name):
        F = A['F']
        if name.startswith('e') and name[1:].isdigit():
            return F.ema(int(name[1:]))
        if name == 'x_ext':                          # extended: the close more than k ATR14 above the 10 EMA
            with np.errstate(invalid='ignore'):
                return F.c >= F.ema(10) + A.get('_ext', 2.5) * F.atr14
        return super().named(A, pool, name)

    def pool_dependent(self, name):
        return name == 'x_ext'

    def ledger_check_cfg(self, A, cfg, mask, pool, pad=3):
        """(id, ticker, side, outcome) for her trades against an already built mask."""
        from studies.trader_replication import ledger as L
        days = A['days'].astype(str)
        ci = {str(c)[3:]: j for j, c in enumerate(A['codes'])}
        out = []
        for t in L.load(self.root / 'notes' / 'trades.csv'):
            j = ci.get(t.ticker)
            if j is None:
                out.append((t.id, t.ticker, t.side, 'not in data'))
                continue
            lo = max(int(np.searchsorted(days, t.window_lo)) - pad, 0)
            hi = min(int(np.searchsorted(days, t.window_hi, side='right')) + pad, len(days))
            sig = [days[d] for d in range(lo, hi) if mask[d, j]] if t.side == 'long' else []
            inpool = bool(pool[lo:hi, j].any())
            out.append((t.id, t.ticker, t.side, 'signal ' + ','.join(sig) if sig else
                        ('pool, no signal' if inpool else 'not in pool')))
        return out

    def ledger_check(self, report, key='chosen', pad=3):
        """Her dated trades: was there one of our long signals on the name inside her window (+- pad sessions)?"""
        from studies.trader_replication import ledger as L
        cfg = self.config(report, key)
        A = self.arrays('us')
        entries, rules, mask, pool = self.build(A, cfg)
        days = A['days'].astype(str)
        ci = {str(c)[3:]: j for j, c in enumerate(A['codes'])}
        out = []
        for t in L.load(self.root / 'notes' / 'trades.csv'):
            j = ci.get(t.ticker)
            if j is None:
                out.append((t.id, t.ticker, t.side, 'not in data'))
                continue
            lo = max(int(np.searchsorted(days, t.window_lo)) - pad, 0)
            hi = min(int(np.searchsorted(days, t.window_hi, side='right')) + pad, len(days))
            sig = [days[d] for d in range(lo, hi) if mask[d, j]]
            inpool = bool(pool[lo:hi, j].any())
            out.append((t.id, t.ticker, t.side, 'signal ' + ','.join(sig) if sig else ('pool, no signal' if inpool else 'not in pool')))
        for r in out:
            print(*r, flush=True)
        return out


def _rolling_tr(F, n):
    from studies.trader_screens.screens import rolling
    pc = lag(F.c)
    tr = np.fmax(F.h - F.l, np.fmax(np.abs(F.h - pc), np.abs(F.l - pc)))
    return rolling(tr, n, 'mean')


STUDY = Swing()

if __name__ == '__main__':
    if sys.argv[1] == 'round':
        STUDY.round(sys.argv[2])
    elif sys.argv[1] == 'ledger':
        STUDY.ledger_check(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else 'chosen')
    elif sys.argv[1] == 'validate':
        STUDY.validate(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else 'chosen')
