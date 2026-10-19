"""Draft screens: each trader's published rules, coded on daily bars (skills/trader-screens).

A draft is the "end-to-end version from his own words" of skills/trader-replication step 4: every rule cites the
dossier source (studies/trader_registry/dossiers); a number the sources do not give is a researcher choice marked
`researcher` and kept at a round value.  Drafts are not replicated: nothing here has been compared with the
trader's real trades or tested against random entry.

Everything on day t uses bars up to t only.  A screen returns its watchlist and setups:
  ready      the setup stands at today's close; `price` is the level that triggers tomorrow, `stop` the planned stop
  triggered  a buy today: the bar broke yesterday's ready level (or a one-day event such as an episodic pivot);
             `price` is the fill (the level, or the open when it gapped above), `stop` the rule's stop, `skip` the
             days the rule says not to buy
Each screen also carries `book`, the account rules his words give (a record; accounts run on the research engine).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np




@dataclass(frozen=True)
class BookRules:
    """The account rules his public words give for the draft (a record of the dossier; accounts are run by the
    research engine on the registered system, studies/trader_replication/systems.py)."""
    risk: float = .005              # equity fraction lost at the initial stop
    max_position: float = .30       # per name, of equity
    gross: float = 1.0              # total long value / equity
    max_new: int = 2                # new positions per day
    max_open: int = 8
    trail: str = ''                 # close trail line ('sma10', 'ema20', ...); '' = none
    partial_day: int = 0            # > 0: on this day after entry, at the close, sell partial_frac if in profit
    partial_frac: float = 0.0
    gate: str = ''                  # 'ema20' / 'ema50': no new positions while the pool index closes below it
    gate_mode: str = 'block'        # 'block' or 'half' (half risk while below)
    stop_min: float = .01           # the stop is at least this far below the fill

def lag(x, n=1):
    out = np.full_like(x, np.nan, dtype=float) if x.dtype != bool else np.zeros_like(x)
    if n < len(x):
        out[n:] = x[:-n]
    return out


def rolling(x, n, how):
    """Max / min / mean of the last n rows including today, NaN unless all n are valid."""
    out = np.full(x.shape, np.nan)
    if len(x) < n:
        return out
    if how == 'mean':
        v = np.where(np.isnan(x), 0.0, x)
        c = np.vstack([np.zeros((1, x.shape[1])), np.cumsum(v, axis=0)])
        k = np.vstack([np.zeros((1, x.shape[1])), np.cumsum(~np.isnan(x), axis=0)])
        s, m = c[n:] - c[:-n], k[n:] - k[:-n]
        out[n - 1:] = np.where(m == n, s / np.maximum(m, 1), np.nan)
        return out
    f = np.fmax if how == 'max' else np.fmin
    acc = x[n - 1:].astype(float).copy()
    bad = np.isnan(acc)
    for k in range(1, n):
        part = x[n - 1 - k:len(x) - k]
        bad |= np.isnan(part)
        acc = f(acc, part)
    out[n - 1:] = np.where(bad, np.nan, acc)
    return out


def ema(x, n):
    out = np.full(x.shape, np.nan)
    a = 2 / (n + 1)
    prev = np.full(x.shape[1], np.nan)
    for t in range(len(x)):
        v = x[t]
        ok = ~np.isnan(v)
        prev = np.where(ok & np.isnan(prev), v, np.where(ok, a * v + (1 - a) * prev, prev))
        out[t] = prev
    return out


class Feat:
    """Lazily computed daily features of one market panel (days x codes)."""

    def __init__(self, p, market):
        self.p, self.market, self._c = p, market, {}
        self.days, self.codes = p['days'], p['codes']
        for k in ('open', 'high', 'low', 'close', 'volume', 'turnover', 'raw_close'):
            setattr(self, k[0] if k in ('open', 'high', 'low', 'close') else k, p[k].astype(float))
        self.v, self.raw = self.volume, self.raw_close

    def get(self, key, fn):
        if key not in self._c:
            with np.errstate(invalid='ignore', divide='ignore'):
                self._c[key] = fn()
        return self._c[key]

    def sma(self, n):
        return self.get(('sma', n), lambda: rolling(self.c, n, 'mean'))

    def ema(self, n):
        return self.get(('ema', n), lambda: ema(self.c, n))

    def hi(self, n):
        return self.get(('hi', n), lambda: rolling(self.h, n, 'max'))

    def lo(self, n):
        return self.get(('lo', n), lambda: rolling(self.l, n, 'min'))

    def range(self, n, end_lag=0):
        """High-low range in percent of the n days ending end_lag days before today."""
        return self.get(('range', n, end_lag), lambda: lag((self.hi(n) / self.lo(n) - 1) * 100, end_lag)
                        if end_lag else (self.hi(n) / self.lo(n) - 1) * 100)

    def ret(self, n):
        return self.get(('ret', n), lambda: self.c / lag(self.c, n) - 1)

    def vol(self, n):
        return self.get(('vol', n), lambda: rolling(self.v, n, 'mean'))

    @property
    def adr(self):
        """20-day average of high / low - 1, in percent (Qullamaggie S03's ADR; Martin Luk's research too)."""
        return self.get('adr', lambda: rolling(self.h / self.l - 1, 20, 'mean') * 100)

    @property
    def atr14(self):
        def f():
            pc = lag(self.c)
            tr = np.fmax(self.h - self.l, np.fmax(np.abs(self.h - pc), np.abs(self.l - pc)))
            return rolling(tr, 14, 'mean')
        return self.get('atr14', f)

    @property
    def to20(self):
        return self.get('to20', lambda: rolling(self.turnover, 20, 'mean'))

    @property
    def rank_pool(self):
        """Names ranked against each other: US price >= 1 and 20-day turnover >= 2M USD (the research rank pool);
        HK / A-shares: every listed name with data (the lists are already liquid)."""
        return self.get('rank_pool', lambda: ((self.raw >= 1) & (self.to20 >= 2e6)) if self.market == 'us'
                        else np.isfinite(self.to20))

    def rank(self, key, x):
        """Per-day percentile (0..1) of x among rank-pool names; NaN elsewhere."""
        def f():
            out = np.full(x.shape, np.nan)
            pool = self.rank_pool
            for t in range(len(x)):
                ok = pool[t] & np.isfinite(x[t])
                n = ok.sum()
                if n >= 20:
                    out[t, np.flatnonzero(ok)] = (np.argsort(np.argsort(x[t, ok])) + .5) / n
            return out
        return self.get(('rank', key), f)

    def liquid(self, usd):
        """US: 20-day average turnover of at least `usd` and a price of at least 5 USD (researcher: no penny
        stocks); HK / A-shares: list membership (the trend-scan lists are filtered by turnover or market cap
        already), so these floors do not apply there."""
        return self.get(('liquid', usd), lambda: ((self.to20 >= usd) & (self.raw >= 5)) if self.market == 'us'
                        else np.isfinite(self.to20))

    @property
    def has(self):
        return np.isfinite(self.c)


@dataclass
class Setup:
    name: str
    kind: str                       # 'ready' (tomorrow's trigger) | 'triggered' (a buy today)
    mask: np.ndarray
    price: np.ndarray
    stop: np.ndarray
    note: str = ''
    tags: dict = field(default_factory=dict)   # tag text -> bool array (shown, not filtering)
    skip: np.ndarray | None = None             # the rule says not to buy (stop too wide, chasing, ...)


def triggered_from(F, ready, level):
    """Today's high broke yesterday's ready level: (mask, entry = the level, or the open when it gapped above)."""
    lv = lag(level)
    with np.errstate(invalid='ignore'):
        m = lag(ready) & (F.h > lv)
    return m, np.where(m, np.fmax(F.o, lv), np.nan)


def strength(F):
    """Highest of the 1 / 3 / 6-month return percentiles: the ranking every draft uses when it has more signals
    than its daily limit (researcher choice; these are all momentum traders)."""
    return F.get('strength', lambda: np.fmax(np.fmax(F.rank('r21', F.ret(21)), F.rank('r63', F.ret(63))),
                                             F.rank('r126', F.ret(126))))


class Screen:
    id = ''              # studies/trader_registry id
    name = ''
    level = 'draft'
    markets = ('us', 'hk', 'cn')
    dossier = ''
    summary = ''
    book = BookRules()
    book_note = ''

    def run(self, F):
        """dict(watch=mask, setups=[Setup])"""
        raise NotImplementedError


class Qullamaggie(Screen):
    id, name = 'qullamaggie', 'Qullamaggie'
    dossier = 'studies/trader_registry/dossiers/qullamaggie/dossier.zh.md'
    summary = '1/3/6 月强势股的收窄整理突破；重大跳空放量（EP）'
    book = BookRules(risk=.005, max_position=.30, gross=1.0, max_new=3, max_open=10, trail='sma10',
                     partial_day=3, partial_frac=1 / 3)
    book_note = ('每笔风险 0.5%（S03：0.3–0.5%）、单只 ≤ 30%（S01）；第 3 天收盘若盈利卖 1/3（S01：3–5 天减 1/3–1/2）；'
                 '余仓收盘跌破 10 日线清仓（S01：10/20 日线）；每天最多 3 笔、同时 10 只、总仓位 100%：研究者取值')

    def run(self, F):
        adr = F.adr
        pool = F.liquid(20e6) & (adr >= 4)                       # S07 early $20M floor; ADR >= 4: researcher
        watch = pool & (strength(F) >= .98)                      # S01 1/3/6-month leaders; top 2%: researcher
        with np.errstate(invalid='ignore'):
            base = ((F.range(10) <= 3 * adr)                     # S01 2 weeks-2 months tightening; 10 days, 3 ADR
                    & (F.range(5) < F.range(5, 5))               # narrowing
                    & (F.lo(5) > lag(F.lo(5), 5))                # S01 higher lows
                    & (F.c >= F.hi(10) * (1 - adr / 100)))       # within 1 ADR of the base high: researcher
        ready = watch & base
        level = F.hi(10)
        trig, entry = triggered_from(F, ready, level)
        with np.errstate(invalid='ignore'):
            wide = (entry - F.l) / entry > lag(adr) / 100        # S01 stop within one ADR
            gap = F.o / lag(F.c) - 1 >= .10                      # S01 / S04 about 10%+ gap
            heavy = F.v >= 3 * lag(F.vol(20))                    # S04 unusual volume; 3x: researcher
            quiet = lag(F.ret(63)) < .10                         # S01 prefers names not up in prior months
            ep = F.liquid(20e6) & gap & heavy
            ep_wide = (F.o - F.l) / F.o > 1.5 * lag(adr) / 100   # S04 stop usually 1, at most 1.5 ADR
        return dict(watch=watch, setups=[
            Setup('突破', 'ready', ready, level, level * (1 - adr / 100),
                  '越过触发价买；止损为当日低点，离买价不超过 1 个 ADR（显示的是最远止损）'),
            Setup('突破', 'triggered', trig, entry, F.l, '越过 10 日高点买，止损当日低点', skip=wide),
            Setup('EP', 'triggered', ep, F.o, F.l, '高开 ≥ 10% 且放量，止损当日低点；催化剂要人工确认',
                  {'此前三个月涨幅不足 10%（他偏好的）': quiet}, skip=ep_wide),
        ])


class ClementAng(Screen):
    id, name = 'clement_ang', 'Clement Ang'
    dossier = 'studies/trader_registry/dossiers/active/clement_ang.md'
    summary = '2026 宽筛（50/200 日线上方、成交额、ADR）→ 精选（接近年高、离 50 日线不远、收缩）'
    book = BookRules(risk=.003, max_position=.30, gross=1.0, max_new=2, max_open=8, trail='sma20')
    book_note = ('每笔风险 0.3%（CA2：从 0.3% 试探）；初始仓一次建立（CA1）；离场档案没给，用收盘跌破 20 日线：研究者取值；'
                 '每天最多 2 笔、同时 8 只、单只 ≤ 30%、总仓位 100%：研究者取值')

    def run(self, F):
        adr, atr = F.adr, F.atr14
        with np.errstate(invalid='ignore'):
            wide = (F.c > F.sma(50)) & (F.c > F.sma(200)) & F.liquid(50e6) & (adr >= 3)        # CA1 wide screen
            fine = (wide & (adr >= 4)                                                          # CA1
                    & (F.c >= .90 * F.hi(252))                    # CA1 near the yearly high; within 10%: researcher
                    & ((F.c - F.sma(50)) < 4 * atr)               # CA1 < 4 ATR from the 50 SMA; ATR14: researcher
                    & (F.range(5) <= 2 * adr))                    # CA1 contraction; 5 days within 2 ADR: researcher
        trig, entry = triggered_from(F, fine, F.h)
        with np.errstate(invalid='ignore'):
            chase = entry - F.l > .6 * lag(atr)                   # CA1 skips entries > 0.6 ATR above the day low
        return dict(watch=wide, setups=[
            Setup('精选', 'ready', fine, F.h, F.h - .6 * atr,
                  '越过今日高点买（代替他看的开盘 30 分钟区间）；离当日低点超过 0.6 ATR 不追（显示的是最远止损）'),
            Setup('精选', 'triggered', trig, entry, F.l, '越过昨日高点买，止损当日低点', skip=chase),
        ])


class ChristianFlanders(Screen):
    id, name = 'christian_flanders', 'Christian Flanders'
    dossier = 'studies/trader_registry/dossiers/active/christian_flanders.md'
    summary = '整理后突破 52 周 / 多年新高，10 日线跟踪'
    book = BookRules(risk=.0025, max_position=.30, gross=1.0, max_new=2, max_open=8, trail='sma10')
    book_note = ('每笔风险 0.25%（CF2：计划 0.25% 的例子）；收盘跌破 10 日线离场（CF1）；初始止损档案没给，用突破当日低点：'
                 '研究者取值；每天最多 2 笔、同时 8 只、单只 ≤ 30%、总仓位 100%：研究者取值')

    def run(self, F):
        adr = F.adr
        with np.errstate(invalid='ignore'):
            pool = F.liquid(20e6) & (adr >= 3) & (F.c > F.sma(50))           # researcher
            prior = lag(F.hi(242), 10)                         # the 52-week high as of 10 days ago
            based = F.hi(10) <= prior                          # no new high for 10 days: researcher's "base"
            watch = pool & (F.c >= .85 * F.hi(252))            # researcher
            ready = pool & based & (F.c >= .95 * prior) & (F.range(5) <= 2 * adr)
            trig = lag(pool & based) & (F.h > lag(prior))      # CF1 / CF2 breaks of 52-week / multi-year highs
            entry = np.where(trig, np.fmax(F.o, lag(prior)), np.nan)
            held = F.c > lag(prior)
            top = np.fmax.accumulate(np.nan_to_num(F.h, nan=-np.inf), axis=0)
            before = getattr(F, 'high_before', None)            # the highest high before the panel's first row
            if before is not None:
                top = np.fmax(top, np.nan_to_num(before, nan=-np.inf)[None, :])
            ath = F.h > lag(top)
        return dict(watch=watch, setups=[
            Setup('新高突破', 'ready', ready, prior, np.full_like(prior, np.nan),
                  '越过 52 周高点买；档案没给初始止损，离场用 10 日线（CF1）'),
            Setup('新高突破', 'triggered', trig, entry, F.l, '越过 52 周高点买；止损用当日低点（研究者取值）',
                  {'收盘守住突破位': held, '数据内历史新高': ath}),
        ])


class OliverKell(Screen):
    id, name = 'oliver_kell', 'Oliver Kell'
    dossier = 'studies/trader_registry/dossiers/swing/oliver_kell.md'
    summary = '收缩后重新站上 10/20 EMA（Wedge Pop）、之后第一次回踩守住（EMA Crossback）'
    book = BookRules(risk=.005, max_position=.30, gross=1.0, max_new=2, max_open=8, trail='ema20',
                     gate='ema20', gate_mode='half')
    book_note = ('止损日低（OK1–3）；收盘跌破 20 EMA 离场（OK1–3：10/20 EMA 依价格行为，取 20：研究者取值）；'
                 '指数在 20 EMA 下方时风险减半（OK1–3“更谨慎”，减半：研究者取值）；每笔 0.5%、每天 2 笔、同时 8 只：研究者取值')

    def run(self, F):
        adr = F.adr
        e10, e20 = F.ema(10), F.ema(20)
        with np.errstate(invalid='ignore'):
            pool = F.liquid(20e6) & (adr >= 3)                                     # researcher
            top = np.fmax(e10, e20)
            pop = (pool & (lag(F.c) <= lag(top)) & (F.c > top)                     # OK4 reclaims the 10/20 EMA
                   & (F.range(10, 1) <= 2.5 * lag(adr)))                           # OK4 after contraction; researcher
            watch = pool & (F.c > e10) & (e10 > e20) & (F.c > F.sma(50))           # researcher: in an up cycle
            touch = (F.l <= e10) & (F.c >= e20)
            below = F.c < e20
        cross = np.zeros_like(pop)
        since, touched = np.full(pop.shape[1], -1), np.zeros(pop.shape[1], bool)
        for t in range(len(pop)):                              # OK5 the first pullback after a wedge pop that holds
            live = (since >= 0) & (t - since <= 20) & (t - since >= 2)
            cross[t] = live & ~touched & touch[t] & pool[t]
            touched |= (since >= 0) & touch[t] & (t > since)
            dead = below[t] & (since >= 0) & (t > since)
            since = np.where(pop[t], t, np.where(dead, -1, since))
            touched = np.where(pop[t] | dead, False, touched)
        ctrig, centry = triggered_from(F, cross, F.h)
        return dict(watch=watch, setups=[
            Setup('Wedge Pop', 'triggered', pop, F.c, F.l, '收盘站上 10/20 EMA 时买；止损当日低点'),
            Setup('EMA Crossback', 'ready', cross, F.h, F.l,
                  '回踩 10 EMA 后收在 20 EMA 上方；越过今日高点买，止损今日低点'),
            Setup('EMA Crossback', 'triggered', ctrig, centry, lag(F.l), '越过回踩日高点买，止损回踩日低点'),
        ])


class MarkMinervini(Screen):
    id, name = 'mark_minervini', 'Mark Minervini'
    dossier = 'studies/trader_registry/dossiers/swing/mark_minervini.md'
    summary = '趋势模板 + 波动逐步收缩（VCP）的枢轴突破'
    book = BookRules(risk=.005, max_position=.30, gross=1.0, max_new=2, max_open=8, trail='sma50')
    book_note = ('止损取底部低点、最多 8%（MM2：止损通常个位数，8%：研究者取值）；离场档案没给，用收盘跌破 50 日线：研究者取值；'
                 '每笔 0.5%、每天 2 笔、同时 8 只、单只 ≤ 30%：研究者取值')

    def run(self, F):
        s50, s150, s200 = F.sma(50), F.sma(150), F.sma(200)
        with np.errstate(invalid='ignore'):
            rs = F.rank('rs', .4 * F.ret(63) + .2 * F.ret(126) + .2 * F.ret(189) + .2 * F.ret(252))
            # trend template as published in his book (MM5 / MM6 restate it; the book itself is unread)
            tt = ((F.c > s150) & (F.c > s200) & (s150 > s200) & (s200 > lag(s200, 21)) & (s50 > s150)
                  & (s50 > s200) & (F.c > s50) & (F.c >= 1.3 * F.lo(252)) & (F.c >= .75 * F.hi(252)) & (rs >= .70))
            watch = F.liquid(20e6) & tt                                             # liquidity: researcher
            vcp = ((F.range(5) < F.range(5, 5)) & (F.range(5, 5) < F.range(10, 10))  # MM1 / MM2 contractions
                   & (F.range(5) <= 10)                                             # researcher
                   & (F.vol(10) < F.vol(50))                                        # MM1 supply dries up
                   & (F.c >= .95 * F.hi(10)))                                       # near the pivot: researcher
        ready = watch & vcp
        pivot, base_low = F.hi(10), F.lo(10)
        trig, entry = triggered_from(F, ready, pivot)
        with np.errstate(invalid='ignore'):
            loud = F.v >= 1.5 * lag(F.vol(50))
            stop = np.fmax(lag(base_low), entry * .92)
        return dict(watch=watch, setups=[
            Setup('VCP 枢轴', 'ready', ready, pivot, np.fmax(base_low, pivot * .92),
                  '越过枢轴（10 日高点）买；止损底部低点，最多 8%'),
            Setup('VCP 枢轴', 'triggered', trig, entry, stop, '越过枢轴买；止损底部低点，最多 8%',
                  {'放量突破（≥ 1.5 倍 50 日均量）': loud}),
        ])


DRAFTS = (Qullamaggie(), ClementAng(), ChristianFlanders(), OliverKell(), MarkMinervini())
