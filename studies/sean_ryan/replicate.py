"""Sean Ryan through skills/trader-replication, on the Flanders machinery (entries, priorities, the generic loop);
his stages are the "second wave": a name that went sideways, shot up on big volume (the first wave), held the new
price and tightened into a small base, bought through the base's top line.

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.sean_ryan.replicate round R1

Everything on day t uses bars up to t; the pivot is the top of the last `base` sessions before t, so the fill is
max(open, pivot) and the stop the previous day's low (his "low of the previous day", PLTR).  His entry-day rule
("if I'm down on the position by the end of the day I sell it on the close") is the day-0 exit: a day that
touches the stop after the fill is stopped there (pessimistic), else a close under the fill sells at the close.
Rounds choose on the selection segment only (2024-01-02 -> 2025-12-31, PREREG_R0); the 2026 segment is
evaluated once by `validate`.  His rules and sources: notes/RULES_CN.md; his trades: notes/trades.csv.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from studies.christian_flanders import replicate as CF
from studies.trader_replication import study
from studies.trader_screens import screens as S

ROOT = Path(__file__).resolve().parents[2]
lag = S.lag

SELECT = ('2024-01-02', '2025-12-31')
VALIDATE = ('2026-01-02', '2026-10-16')
WINDOW = ('2024-01-02', '2026-10-16')

WAVE = dict(look=40,       # the first wave lies within the last `look` sessions before t
            gain=.50,      # low to later high at least +50% ("from 2 to 5"; "up 20% -> the next move only 20%")
            surge=3.0,     # one session of the wave with turnover >= 3x its 50-day average ("big volume")
            hold=.50,      # yesterday's close holds at least half of the wave ("holds that new price")
            base=10,       # the base: the last `base` sessions before t ...
            tight=.50,     # ... ranging at most half the wave's range ("tighten up, a nice little handle")
            rest=5)        # the wave's high is at least this many sessions before t (a base exists)

DRAFT = dict(
    setups=['wave2'],
    entry='pivot',                   # fill max(open, pivot); stop yesterday's low; entry-day close rule
    stop_min=.02, stop_max=.08,      # stop at least 2% (keeps a position <= 50% at 1% risk), at most 8% below
    priority='strength', max_new=3, strength='', filter='',
    pool=dict(turnover=2e6, price=1.0),
    wave=WAVE,
    rule_opts=dict(risk=.01, max_position=.50, max_gross=1.0, max_open=0, trail='plo10',
                   arm_trail_on_entry=True, trims=(), breakeven_r=1.0, exit_signal='rev', margin_rate=0.0),
)


def since_extreme(x, n, how):
    """(value, sessions since) of the max / min of the last n rows including today; NaN rows are skipped."""
    best = np.full(x.shape, np.nan)
    age = np.full(x.shape, -1)
    better = np.greater if how == 'max' else np.less
    for k in range(n):
        v = lag(x, k) if k else x.astype(float)
        with np.errstate(invalid='ignore'):
            take = np.isfinite(v) & (np.isnan(best) | better(v, best))
        best = np.where(take, v, best)
        age = np.where(take, k, age)
    return best, age


def rsi(x, n=14):
    """Wilder RSI of a 1-D series."""
    d = np.diff(x, prepend=x[0])
    up, dn = np.clip(d, 0, None), np.clip(-d, 0, None)
    out = np.full(len(x), np.nan)
    au = ad = None
    for t in range(1, len(x)):
        if t < n:
            continue
        if au is None:
            au, ad = up[1:n + 1].mean(), dn[1:n + 1].mean()
        else:
            au, ad = (au * (n - 1) + up[t]) / n, (ad * (n - 1) + dn[t]) / n
        out[t] = 100.0 if ad == 0 else 100 - 100 / (1 + au / ad)
    return out


def rsi2(c, n=14):
    """Wilder RSI of each column of a (days x codes) close array (NaN until n valid changes)."""
    out = np.full(c.shape, np.nan)
    au = np.full(c.shape[1], np.nan)
    ad = np.full(c.shape[1], np.nan)
    cnt = np.zeros(c.shape[1])
    su = np.zeros(c.shape[1])
    sd = np.zeros(c.shape[1])
    for t in range(1, len(c)):
        d = c[t] - c[t - 1]
        ok = np.isfinite(d)
        up, dn = np.where(ok, np.clip(d, 0, None), 0.0), np.where(ok, np.clip(-d, 0, None), 0.0)
        warm = np.isnan(au)
        cnt += ok & warm
        su += np.where(warm, up, 0.0)
        sd += np.where(warm, dn, 0.0)
        start = warm & (cnt >= n)
        au = np.where(start, su / n, np.where(~warm & ok, (au * (n - 1) + up) / n, au))
        ad = np.where(start, sd / n, np.where(~warm & ok, (ad * (n - 1) + dn) / n, ad))
        with np.errstate(invalid='ignore', divide='ignore'):
            out[t] = np.where(np.isfinite(au), np.where(ad == 0, 100.0, 100 - 100 / (1 + au / ad)), np.nan)
    return out


def stock_divergence(c, look=20, gap=5.0):
    """Day t: a new `look`-day closing high with RSI14 at least `gap` points under its highest of the previous
    `look` sessions (bars up to t)."""
    r = rsi2(c)
    prev_hi = lag(S.rolling(c, look, 'max'))
    prev_r = lag(S.rolling(r, look, 'max'))
    with np.errstate(invalid='ignore'):
        return (c > prev_hi) & (r < prev_r - gap)


def bear_state(idx, r, look=60, gap=5.0):
    """Per day (at its close): True from a bearish divergence (a new `look`-day closing high with RSI at least
    `gap` points under its highest of the previous `look` days) until a bullish one (a new closing low with RSI
    `gap` above its lowest) or a new high that RSI confirms (RSI at its own `look`-day high)."""
    out = np.zeros(len(idx), bool)
    on = False
    for t in range(look, len(idx)):
        win, rw = idx[t - look:t], r[t - look:t]
        if not np.isfinite(r[t]) or not np.isfinite(rw).all():
            out[t] = on
            continue
        if idx[t] > win.max():
            on = r[t] < rw.max() - gap
        elif idx[t] < win.min() and r[t] > rw.min() + gap:
            on = False
        out[t] = on
    return out


def rsi_bear(A):
    """His market read on the comparison's equal-weight index (shorts.market_index): bearish RSI divergence."""
    from studies.trader_replication.shorts import market_index
    if '_ryan_bear' not in A:
        idx = market_index(A)
        A['_ryan_bear'] = bear_state(idx, rsi(idx))
    return A['_ryan_bear']


class Ryan(CF.Flanders):
    id, name = 'sean_ryan', 'Sean Ryan'
    root = ROOT / 'studies' / 'sean_ryan'
    ledger = root / 'notes' / 'trades.csv'
    cutoff = '2024-01-01'           # PREREG_R0: every dated trade of his is 2023 (selection); no ledger validation
    full = SELECT                   # rounds see the selection segment only
    home = ('us',)
    his = {'2024': dict(ret=.408), '2025': dict(ret=.888)}
    his_behaviour = dict(per_year=577, win=.27, avg_win=.057, avg_loss=-.0371)   # his 2023 statistics
    starts = ('2024-01-02', '2024-02-01', '2024-03-01', '2024-04-01', '2024-07-01', '2025-01-02')
    base = DRAFT

    # ----- named day arrays -----
    def named(self, A, pool, name):
        F = A['F']
        if name.startswith('plo'):                       # the lowest low of the n sessions before today
            return lag(F.lo(int(name[3:])))
        if name == 'rev':                                # reversal day: a new 20-day high, a close in the day's
            return self.reversal(F)                      # bottom quarter, the biggest volume in 50 sessions
        if name == 'rsidiv':                             # "the price moved higher and the RSI was weaker"
            return F.get('ryan_rsidiv', lambda: stock_divergence(F.c))
        return super().named(A, pool, name)

    @staticmethod
    def reversal(F):
        def f():
            rng = F.h - F.l
            return ((F.h >= F.hi(20)) & (rng > 0) & (F.c <= F.l + .25 * rng)
                    & (F.v >= S.rolling(F.v, 50, 'max')))
        return F.get('ryan_rev', f)

    # ----- stages -----
    def pool(self, A, cfg):
        """Every name above the data set's floors (he flips through every chart): price >= 1, turnover >= 2M."""
        F, p = A['F'], cfg.get('pool', {})
        with np.errstate(invalid='ignore'):
            if A['market'] == 'us':
                return (F.raw >= p.get('price', 1.0)) & (F.to20 >= p.get('turnover', 2e6))
            return F.liquid(0)

    def wave(self, A, cfg):
        """Day-t readiness, all from bars up to t-1: (ready, pivot)."""
        F = A['F']
        w = dict(WAVE, **cfg.get('wave', {}))
        n, b = w['look'], w['base']
        def f():
            hi, hi_age = since_extreme(F.h, n, 'max')            # the wave's high within the look-back
            lo, lo_age = since_extreme(F.l, n + 20, 'min')        # its low: before the high
            with np.errstate(invalid='ignore', divide='ignore'):
                rel = F.turnover / lag(S.rolling(F.turnover, 50, 'mean'))
                surge = S.rolling(np.nan_to_num(rel), n, 'max') >= w['surge']
                gain = (hi / lo - 1 >= w['gain']) & (lo_age > hi_age)
                held = F.c >= lo + w['hold'] * (hi - lo)
                wave_rng = (hi / lo - 1) * 100
                tight = F.range(b) <= w['tight'] * wave_rng
                ready = gain & surge & held & tight & (hi_age >= w['rest'] - 1)
            return ready, F.hi(b)
        key = ('ryan_wave',) + tuple(sorted(w.items()))
        ready, top = F.get(key, f)
        return lag(ready), lag(top)

    def setups(self, A, cfg):
        F = A['F']
        out = super().setups(A, dict(cfg, setups=[s for s in cfg.get('setups', [])
                                                  if s in ('ep', 'brk52', 'pp', 'vcp', 'pb')]))
        names = cfg.get('setups', ['wave2'])
        pool = lag(self.pool(A, cfg))
        if 'wave2' in names:
            ready, pivot = self.wave(A, cfg)
            with np.errstate(invalid='ignore'):
                m = pool & ready & (F.h > pivot)
            out['wave2'] = (m, pivot, lag(F.l))
        if 'shake' in names:
            # his second safe buy point, "a breakdown and reversal, that's a shakeout, you buy at the neck": a base
            # that was ready three sessions ago (bars to t-3), traded under its low in the last two sessions and
            # closes back above that low today (with a higher close); the stop is the undercut's low
            ready, _ = self.wave(A, cfg)
            b = dict(WAVE, **cfg.get('wave', {}))['base']
            neck = lag(F.lo(b), 3)
            under = lag(F.lo(2))
            with np.errstate(invalid='ignore'):
                m = pool & lag(ready, 2) & (under < neck) & (F.c > neck) & (F.c > lag(F.c))
            out['shake'] = (m, neck, under)
        return out

    def entries(self, A, cfg, masks):
        """Stops sit at the setup's stop (yesterday's low) within [stop_min, stop_max] below the fill.
        'pivot'        fill max(open, level); day-0 exit at the stop when the day's low reaches it (pessimistic: the
                       low came after the fill), else at the close when it is under the fill
        'pivot_close'  the same fill; on day 0 only a close at or under the stop counts as stopped (at the stop),
                       a close under the fill sells at the close (the order of the day's low and the fill unknown)
        'close'        buy the close of a day that closes above the level (his "where it ends the day"); no day-0
                       exit; stop_from 'prev' (yesterday's low, default) or 'day' (the day's low)
        Other modes: the Flanders entries."""
        mode = cfg.get('entry')
        if mode not in ('pivot', 'pivot_close', 'close'):
            return super().entries(A, cfg, masks)
        F = A['F']
        o, l, c = F.o, F.l, F.c
        smin, smax = cfg.get('stop_min', .02), cfg.get('stop_max', .08)
        prio = self.priority(A, cfg)
        out = [[] for _ in range(len(c))]
        for kind, (m, level, stop) in masks.items():
            for d, j in zip(*np.nonzero(m)):
                if d == 0 or not np.isfinite(c[d, j]):
                    continue
                if mode == 'close':
                    if not c[d, j] > level[d, j]:
                        continue
                    fill = c[d, j]
                    s = l[d, j] if cfg.get('stop_from', 'prev') == 'day' and kind != 'shake' else stop[d, j]
                else:
                    fill = max(o[d, j], level[d, j])
                    s = stop[d, j]
                if not (np.isfinite(fill) and np.isfinite(s) and fill > 0):
                    continue
                s = max(min(s, fill * (1 - smin)), fill * (1 - smax))
                exit0 = None
                if mode == 'pivot' and l[d, j] <= s or mode == 'pivot_close' and c[d, j] <= s:
                    exit0 = s
                elif mode != 'close' and c[d, j] < fill:
                    exit0 = float(c[d, j])
                pr = prio[d, j]
                out[d].append((pr if np.isfinite(pr) else 0.0, int(j), 1, float(fill), float(s), kind, exit0))
        return out

    def priority(self, A, cfg):
        """'wave': the biggest first wave first ("up 20% -> the next move probably only 20%"), as of t-1."""
        if cfg.get('priority') != 'wave':
            return super().priority(A, cfg)
        F = A['F']
        w = dict(WAVE, **cfg.get('wave', {}))
        hi, _ = since_extreme(F.h, w['look'], 'max')
        lo, _ = since_extreme(F.l, w['look'] + 20, 'min')
        with np.errstate(invalid='ignore', divide='ignore'):
            return -lag(hi / lo)

    def market_ok(self, A, cfg):
        """'RSIDIV': no new longs while the market is in a bearish RSI divergence (decided at t-1)."""
        if cfg.get('filter') != 'RSIDIV':
            return super().market_ok(A, cfg)
        return lag(~rsi_bear(A))

    def build(self, A, cfg, trace=None):
        entries, rules, mask, placebo_pool = super().build(A, cfg, trace)
        return entries, rules, mask, lag(self.pool(A, cfg))

    def short_setups(self, A, sc):
        """His two short points (RULES ⑨; @01:23:30-01:24:50: "the breakout reversal, that's a fake-out, this is
        where you could short ... and a breakdown is another short"), close-confirmed, bars up to t:

        fake   a second-wave breakout (the long trigger) on one of the last `fake_days` (3) sessions before t, and
               today closes back under that breakout's pivot with a red candle; the stop is the highest high since
               the breakout (at least stop_min above the fill); fake_vol > 0: only on a day whose turnover is at
               least fake_vol x its 20-day mean as of t-1 ("big volume", PLTR / IYR reversals)
        brk    the long setup turned over ("sharp moves down and weak recoveries anticipate another sharp move down",
               IYR @00:55:10): within the last `look` sessions a high-to-low drop of at least `drop` (1/3, the
               first wave's +50% mirrored), yesterday's close at most halfway back up, the last `base` sessions
               ranging at most half the drop, and today closes under the base's low; the stop is the day's high
        Pool: 20-day turnover >= `turnover` (20M) and price >= 5, as of t-1."""
        F = A['F']
        w = dict(WAVE, **sc.get('wave', {}))
        n, b = w['look'], w['base']
        names = sc.get('setups', ['fake', 'brk'])
        with np.errstate(invalid='ignore', divide='ignore'):
            pool = lag(F.liquid(sc.get('turnover', 20e6)))
            out = {}
            if 'fake' in names:
                ready, pivot = self.wave(A, dict(wave=w))
                brk_day = ready & (F.h > pivot)
                k = sc.get('fake_days', 3)
                m = np.zeros(F.c.shape, bool)
                line = np.full(F.c.shape, np.nan)
                vol = sc.get('fake_vol', 0.0)            # the reversal on volume: turnover >= k x its 20-day mean
                loud = F.turnover >= vol * lag(F.to20) if vol else np.ones(F.c.shape, bool)
                for i in range(1, k + 1):
                    hit = lag(brk_day, i) & (F.c < lag(pivot, i)) & (F.c < F.o) & loud
                    line = np.where(hit & ~m, F.hi(i + 1), line)
                    m |= hit
                out['fake'] = dict(armed=pool & m, stop=line)
            if 'brk' in names:
                lo, lo_age = since_extreme(F.l, n, 'min')
                hi, hi_age = since_extreme(F.h, n + 20, 'max')
                drop = (1 - lo / hi >= sc.get('drop', 1 / 3)) & (hi_age > lo_age)
                weak = F.c <= lo + .5 * (hi - lo)
                tight = F.range(b) <= .5 * (hi / lo - 1) * 100
                ready = lag(drop & weak & tight & (lo_age >= w['rest'] - 1))
                out['brk'] = pool & ready & (F.c < lag(F.lo(b)))
        return out, pool

    def his_entry(self, A, d, j, cfg):
        """His ticker on his day with our execution: the close, stop at yesterday's low within the stop bounds."""
        c = A['close'][d, j]
        pl = A['low'][d - 1, j] if d > 0 else np.nan
        if not (np.isfinite(c) and np.isfinite(pl) and c > 0):
            return None
        s = max(min(pl, c * (1 - cfg.get('stop_min', .02))), c * (1 - cfg.get('stop_max', .08)))
        return (0.0, j, 1, c, s, 'his')

    # ----- the 2026 segment, once -----
    def validate(self, report, key='chosen'):
        """The chosen configuration on the validation segment (and the whole window), reported only."""
        cfg = self.config(report, key)
        A = self.arrays('us')
        entries, rules, mask, pool = self.build(A, cfg)
        out = {'report': report, 'config': cfg}
        for name, seg in (('validate', VALIDATE), ('window', WINDOW)):
            st, tr = self.run(A, entries, seg, pool, rules, audit=True)
            st.pop('_curve', None)
            st['ew_hold_pool'] = study.ew_hold(A, pool, seg, lagged=True)
            out[name] = st
            print('VALIDATE', name, f"total {st['total']:+.3f} dd {st['maxdd']:.2f} placebo median "
                  f"{st['placebo']['median']:+.3f} rank {st['placebo']['rank']:.2f} ew {st['ew_hold_pool']:+.3f}",
                  {a: round(b, 3) for a, b in st['by_year'].items()}, 'n', st['trades'], 'win', st['win'], flush=True)
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / f'validate_{self.tag(report, key)}.json').write_text(json.dumps(out, indent=1, default=float),
                                                                       encoding='utf-8')
        return out


STUDY = Ryan()

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'validate':
        STUDY.validate(sys.argv[2] if len(sys.argv) > 2 else '', sys.argv[3] if len(sys.argv) > 3 else 'chosen')
    elif len(sys.argv) > 1 and sys.argv[1] in ('diagnose', 'three'):
        STUDY.full = ('2023-03-01', SELECT[1])          # his dated trades are 2023 (data from 2023-01-03)
        study.main(STUDY, sys.argv)
    else:
        study.main(STUDY, sys.argv)
