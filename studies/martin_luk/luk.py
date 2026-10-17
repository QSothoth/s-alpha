"""Daily-bar replication of Martin Luk's long momentum swing system (see notes/PREREG_R1.md).

    /opt/futu-opend/venv/bin/python -m studies.martin_luk.luk us C3 2024-05-01 2025-04-30

Everything here is long-only, one position per stock, sized by a fixed fraction of equity at risk.
Bars are ratio-adjusted (trend_breakout.panel); price and liquidity floors use the raw close.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'data' / 'trend-scan' / '2026-10-15'
CACHE = ROOT / 'data' / 'martin-luk-cache'

MARKETS = {  # per-market floors and one-way costs (PREREG_R1)
    'us': dict(min_price=5.0, min_turnover=20e6, buy_cost=.0005, sell_cost=.0005, t1=False),
    'hk': dict(min_price=1.0, min_turnover=50e6, buy_cost=.0016, sell_cost=.0016, t1=False),
    'cn': dict(min_price=3.0, min_turnover=200e6, buy_cost=.00076, sell_cost=.00126, t1=True),
}


@dataclass(frozen=True)
class Config:
    market: str = 'us'
    breakout: bool = True          # C1
    pullback: bool = True          # C2
    market_filter: bool = False    # C4
    dd_halving: bool = False       # C5
    risk: float = .005             # equity fraction lost at the initial stop
    max_position: float = .35
    max_gross: float = 2.0
    margin_rate: float = .07
    adr_min: float = 5.0           # percent
    mom: float = .30
    stop_cap: float = .05
    trims: tuple = (3, 6, 9, 12)   # R levels, 15% of the original shares each
    trim_frac: float = .15
    conservative: bool = True      # entry-day low <= stop counts as stopped
    d4: bool = False               # R4-B: close-confirmed breakout / continuation / EP / first pullback


def load(market):
    """Panels for one market, cached as .npz (first load parses ~60 MB of gzip CSV)."""
    path = CACHE / f'{market}.npz'
    if not path.exists():
        sys.path.insert(0, str(ROOT))
        from studies.trend_breakout import panel
        p = panel.load(DATA / market)
        CACHE.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, **{k: p[k] for k in ('dates', 'codes', 'open', 'high', 'low', 'close',
                                                        'volume', 'turnover', 'raw_close', 'raw_open')})
    z = np.load(path, allow_pickle=False)
    return {k: z[k] for k in z.files}


def ema(x, n):
    """EMA down the time axis per column; NaN days keep the previous value, leading NaNs stay NaN."""
    out = np.full_like(x, np.nan)
    a = 2 / (n + 1)
    prev = np.full(x.shape[1], np.nan)
    for t in range(len(x)):
        v = x[t]
        ok = ~np.isnan(v)
        fresh = ok & np.isnan(prev)
        prev = np.where(fresh, v, prev)
        upd = ok & ~fresh
        prev = np.where(upd, a * v + (1 - a) * prev, prev)
        out[t] = prev
    return out


def rolling_mean(x, n):
    """Mean of the last n rows (NaN-aware: needs n valid values)."""
    v = np.where(np.isnan(x), 0, x)
    c = np.cumsum(np.vstack([np.zeros((1, x.shape[1])), v]), axis=0)
    k = np.cumsum(np.vstack([np.zeros((1, x.shape[1])), ~np.isnan(x)]), axis=0)
    s, m = c[n:] - c[:-n], k[n:] - k[:-n]
    out = np.full_like(x, np.nan)
    out[n - 1:] = np.where(m == n, s / np.maximum(m, 1), np.nan)
    return out


def lag(x, n=1):
    out = np.full_like(x, np.nan)
    out[n:] = x[:-n]
    return out


def indicators(p, cfg):
    m = MARKETS[cfg.market]
    c, h, l = p['close'], p['high'], p['low']
    e9, e21, e50 = ema(c, 9), ema(c, 21), ema(c, 50)
    adr = rolling_mean(h / l - 1, 20) * 100
    to20 = rolling_mean(p['turnover'], 20)
    with np.errstate(invalid='ignore', divide='ignore'):
        mom = np.fmax(np.fmax(c / lag(c, 21), c / lag(c, 63)), c / lag(c, 126)) - 1
        r63 = c / lag(c, 63) - 1
        tradeable = (p['raw_close'] >= m['min_price']) & (to20 >= m['min_turnover'])
        leader = tradeable & (adr >= cfg.adr_min) & (mom >= cfg.mom) & (e9 > e21) & (e21 > e50)
        ret = np.where(tradeable & ~np.isnan(lag(c)), c / lag(c) - 1, np.nan)
    eq = np.nanmean(np.where(np.isnan(ret), np.nan, ret), axis=1)
    idx = np.cumprod(1 + np.nan_to_num(eq))[:, None]
    up = (idx > ema(idx, 21))[:, 0]
    return dict(e9=e9, e21=e21, e50=e50, adr=adr, leader=leader, r63=r63, tradeable=tradeable,
                index=idx[:, 0], market_up=up, ew_ret=np.nan_to_num(eq))


def signals(p, ind, cfg):
    """Return (orders, closes): orders[d] = breakout buy-stops for day d; closes[d] = close entries on d.

    Each item is (priority, j, trigger_or_price, stop, kind).
    """
    if cfg.d4:
        return d4_signals(p, ind, cfg)
    o, h, l, c = p['open'], p['high'], p['low'], p['close']
    T = len(c)
    prio = np.nan_to_num(-ind['r63'], nan=0.0)
    orders = [[] for _ in range(T)]
    closes = [[] for _ in range(T)]
    with np.errstate(invalid='ignore'):
        rng = h / l - 1
        inside = (h <= lag(h)) & (l >= lag(l))
        tight = inside | (rng * 100 <= .5 * ind['adr'])
        setup = ind['leader'] & tight & (c >= ind['e21'])
        support = [lag(ind[k]) for k in ('e9', 'e21', 'e50')]
        reclaim = np.zeros_like(setup)
        for e in support:
            reclaim |= (l <= e) & (c >= e)
        pull = ind['leader'] & reclaim & (c >= (h + l) / 2)
    for d in range(T):
        if cfg.breakout and d + 1 < T:
            for j in np.flatnonzero(setup[d]):
                orders[d + 1].append((prio[d, j], j, h[d, j], l[d, j], 'bo'))
        if cfg.pullback:
            for j in np.flatnonzero(pull[d]):
                closes[d].append((prio[d, j], j, c[d, j], l[d, j], 'pb'))
    for lst in orders + closes:
        lst.sort(key=lambda x: x[0])
    return orders, closes


def d4_signals(p, ind, cfg):
    """Close entries only (PREREG_R4 B): every trigger is confirmed by today's close, stop = today's low."""
    o, h, l, c = p['open'], p['high'], p['low'], p['close']
    T = len(c)
    with np.errstate(invalid='ignore', divide='ignore'):
        inside = (h <= lag(h)) & (l >= lag(l))
        tight = inside | ((h / l - 1) * 100 <= .5 * ind['adr'])
        setup = ind['leader'] & tight & (c >= ind['e21'])
        to20 = rolling_mean(p['turnover'], 20)
        r1 = c / lag(c) - 1
        burst = (ind['tradeable'] & (ind['adr'] >= cfg.adr_min) & (r1 >= np.fmax(.08, 1.5 * ind['adr'] / 100))
                 & ((c - l) / (h - l) >= .75) & (p['turnover'] >= 2 * lag(to20)))
        hh10 = np.full_like(h, np.nan)
        for k in range(9, T):
            hh10[k] = np.nanmax(h[k - 9:k + 1], axis=0)
        fp = ind['leader'] & (hh10 >= ind['e21'] * (1 + 3 * ind['adr'] / 100)) & (c > ind['e21'])
        above_pdh = c >= lag(h)
        e21p = lag(ind['e21'])
        today = {
            'bo': lag(setup.astype(float)) == 1,
            'burst': lag(burst.astype(float)) == 1,
            'fp': (lag(fp.astype(float)) == 1) & (l < e21p) & (c > e21p),
            'ep': (lag(ind['tradeable'].astype(float)) == 1) & (o / lag(c) - 1 >= .10) & (c >= o)
                  & (p['turnover'] >= 2 * lag(to20)),
        }
        today['bo'] &= above_pdh
        today['burst'] &= above_pdh
    prio = np.nan_to_num(-ind['r63'], nan=0.0)
    orders = [[] for _ in range(T)]
    closes = [[] for _ in range(T)]
    for d in range(1, T):
        for kind, m in today.items():
            for j in np.flatnonzero(m[d]):
                closes[d].append((prio[d, j], j, c[d, j], l[d, j], 'c' + kind))
        closes[d].sort(key=lambda x: x[0])
    return orders, closes


@dataclass
class Pos:
    j: int
    kind: str
    d0: int
    fill: float
    stop: float
    shares0: float
    shares: float
    trims: int = 0
    above9: bool = False
    cash_in: float = 0.0      # cost paid
    cash_out: float = 0.0     # proceeds received
    exits: list = field(default_factory=list)


def simulate(p, ind, cfg, start, end, orders, closes, placebo=None):
    """Run the portfolio day by day between ISO dates; return (equity series, dates, trades).

    placebo: optional numpy Generator; each real entry is replaced by a random leader of the same day,
    entered at that stock's close with the same stop distance in percent.
    """
    m = MARKETS[cfg.market]
    o, h, l, c = p['open'], p['high'], p['low'], p['close']
    dates = p['dates']
    d0, d1 = int(np.searchsorted(dates, start)), int(np.searchsorted(dates, end, side='right'))
    cash, pos, trades, curve = 1.0, {}, [], []
    peak = 1.0

    def mark(d):
        return cash + sum(q.shares * last_close(q.j, d) for q in pos.values())

    def last_close(j, d):
        k = d
        while k >= 0 and np.isnan(c[k, j]):
            k -= 1
        return c[k, j] if k >= 0 else 0.0

    def sell(q, shares, price, d, why):
        nonlocal cash
        shares = min(shares, q.shares)
        if shares <= 0:
            return
        got = shares * price * (1 - m['sell_cost'])
        cash += got
        q.cash_out += got
        q.shares -= shares
        q.exits.append((d, price, shares, why))
        if q.shares <= 1e-12:
            close_trade(q, d)

    def close_trade(q, d):
        pos.pop(q.j, None)
        R = q.shares0 * (q.fill - q.stop)
        trades.append(dict(j=q.j, code=str(p['codes'][q.j]), kind=q.kind, entry=str(dates[q.d0]),
                           exit=str(dates[d]), days=d - q.d0, fill=q.fill, stop=q.stop,
                           risk_pct=(q.fill - q.stop) / q.fill, pnl=q.cash_out - q.cash_in,
                           r=(q.cash_out - q.cash_in) / R if R > 0 else 0.0,
                           ret=q.cash_out / q.cash_in - 1, why=q.exits[-1][3]))

    def buy(j, fill, stop, kind, d, equity):
        nonlocal cash, gross_ref
        risk = (fill - stop) / fill
        if not (0 < risk <= min(cfg.stop_cap, .005 * ind['adr'][d - 1 if kind == 'bo' else d, j])):
            return None
        frac = cfg.risk * (.5 if cfg.dd_halving and equity < .9 * peak else 1)
        value = min(frac * equity / risk, cfg.max_position * equity)
        value = min(value, cfg.max_gross * equity - gross_ref)
        if value <= .001 * equity:
            return None
        shares = value / fill
        paid = value * (1 + m['buy_cost'])
        cash -= paid
        gross_ref += value
        q = Pos(j, kind, d, fill, stop, shares, shares, cash_in=paid)
        pos[j] = q
        return q

    rng = placebo
    gross_ref = 0.0
    for d in range(d0, d1):
        equity = mark(d - 1) if d > d0 else 1.0
        gross_ref = sum(q.shares * last_close(q.j, d - 1) for q in pos.values())
        allow = (not cfg.market_filter) or bool(ind['market_up'][d - 1])
        allow_close = (not cfg.market_filter) or bool(ind['market_up'][d])
        # 1) positions held from earlier days: gap stop, intraday stop vs trims, CN pending NFT exits
        for q in list(pos.values()):
            j = q.j
            if np.isnan(o[d, j]):
                continue
            if getattr(q, 'exit_next_open', False):
                sell(q, q.shares, o[d, j], d, 'nft')
                continue
            R = q.fill - q.stop
            if o[d, j] <= q.stop:
                sell(q, q.shares, o[d, j], d, 'gap_stop')
                continue
            levels = [q.fill + k * R for k in cfg.trims[q.trims:]]
            if l[d, j] <= q.stop:
                while levels and o[d, j] >= levels[0]:    # trims filled at the open before the stop
                    sell(q, cfg.trim_frac * q.shares0, o[d, j], d, 'trim')
                    q.trims += 1
                    levels.pop(0)
                if j in pos:
                    sell(q, q.shares, q.stop, d, 'stop')
                continue
            while levels and h[d, j] >= levels[0] and j in pos:
                sell(q, cfg.trim_frac * q.shares0, max(o[d, j], levels[0]), d, 'trim')
                q.trims += 1
                levels.pop(0)
        # 2) breakout buy-stops placed after yesterday's close
        new_today = []
        if allow and rng is None:        # placebo replaces breakouts by close entries in step 4
            for _, j, trig, stop, kind in orders[d]:
                if j in pos or np.isnan(o[d, j]):
                    continue
                if cfg.market == 'cn' and _limit_up_open(p, d, j):
                    continue
                if o[d, j] >= trig:
                    fill = o[d, j]
                elif h[d, j] >= trig:
                    fill = trig
                else:
                    continue
                q = buy(j, fill, stop, kind, d, equity)
                if q is None:
                    continue
                new_today.append(q)
                if not m['t1']:
                    hit = l[d, j] <= stop if cfg.conservative else c[d, j] < stop
                    if hit:
                        sell(q, q.shares, stop, d, 'stop_entry_day')
                        continue
                    R = fill - stop
                    for k in cfg.trims:
                        if h[d, j] >= fill + k * R and j in pos:
                            sell(q, cfg.trim_frac * q.shares0, fill + k * R, d, 'trim')
                            q.trims += 1
        # 3) end of day: no follow-through and 9 EMA trail for positions bought before today's close
        for q in list(pos.values()):
            j = q.j
            if np.isnan(c[d, j]):
                continue
            if q.d0 == d:
                if q.kind == 'bo' and c[d, j] < q.fill:
                    if m['t1']:
                        q.exit_next_open = True
                    else:
                        sell(q, q.shares, c[d, j], d, 'nft')
                        continue
                q.above9 = c[d, j] > ind['e9'][d, j]
                continue
            if q.above9 and c[d, j] < ind['e9'][d, j]:
                sell(q, q.shares, c[d, j], d, 'ema9')
                continue
            q.above9 = q.above9 or c[d, j] > ind['e9'][d, j]
        # 4) close entries (pullback reclaim, or placebo replacements of every entry)
        if allow_close:
            items = closes[d] if rng is None else (_placebo(closes[d], d, ind, rng, 'pb')
                                                    + _placebo(orders[d + 1] if d + 1 < len(orders) else [],
                                                               d, ind, rng, 'bo'))
            for _, j, price, stop, kind in items:
                if j in pos or np.isnan(c[d, j]):
                    continue
                q = buy(j, price, stop, kind, d, equity)
                if q is not None:
                    q.above9 = c[d, j] > ind['e9'][d, j]
        # 5) financing and mark
        gross = sum(q.shares * last_close(q.j, d) for q in pos.values())
        eq = cash + gross
        if gross > eq > 0:
            cash -= (gross - eq) * cfg.margin_rate / 252
        eq = mark(d)
        peak = max(peak, eq)
        curve.append(eq)
    for q in list(pos.values()):             # mark-to-market open trades at the end
        sell(q, q.shares, last_close(q.j, d1 - 1), d1 - 1, 'end')
    return np.array(curve), dates[d0:d1], trades


def _placebo(items, d, ind, rng, kind):
    """Same count and stop distance as the real signals of day d, but on random leaders of day d."""
    if not items:
        return []
    pool = np.flatnonzero(ind['leader'][d])
    out = []
    for prio, j, px, stop, _ in items:
        if len(pool) == 0:
            break
        k = int(rng.choice(pool))
        risk = (px - stop) / px
        out.append((prio, k, ind['_close'][d, k], ind['_close'][d, k] * (1 - risk), kind))
    return out


def _limit_up_open(p, d, j):
    prev = p['close'][d - 1, j]
    if np.isnan(prev):
        return True
    cap = .195 if str(p['codes'][j]).split('.')[-1][:3] in ('300', '301', '688', '689') else .095
    return p['open'][d, j] / prev - 1 >= cap


def stats(curve, dates, trades):
    if not len(curve):
        return {}
    yrs = len(curve) / 252
    dd = 1 - curve / np.maximum.accumulate(np.maximum(curve, 1.0))
    r = np.array([t['r'] for t in trades]) if trades else np.zeros(1)
    wins = r > 0
    ret = np.array([t['ret'] for t in trades]) if trades else np.zeros(1)
    by_year = {}
    prev = 1.0
    for y in sorted({s[:4] for s in dates}):
        k = np.flatnonzero(np.char.startswith(dates.astype(str), y))[-1]
        by_year[y] = curve[k] / prev - 1
        prev = curve[k]
    return dict(total=curve[-1] - 1, cagr=curve[-1] ** (1 / yrs) - 1 if curve[-1] > 0 else -1,
                maxdd=dd.max(), trades=len(trades), per_year=len(trades) / yrs,
                win=wins.mean(), avg_win=ret[wins].mean() if wins.any() else 0,
                avg_loss=ret[~wins].mean() if (~wins).any() else 0,
                exp_r=r.mean(), avg_win_r=r[wins].mean() if wins.any() else 0,
                days_win=np.mean([t['days'] for t, w in zip(trades, wins) if w]) if wins.any() else 0,
                days_loss=np.mean([t['days'] for t, w in zip(trades, wins) if not w]) if (~wins).any() else 0,
                by_year=by_year)


def benchmark(ind, dates_all, start, end):
    d0, d1 = int(np.searchsorted(dates_all, start)), int(np.searchsorted(dates_all, end, side='right'))
    return float(np.prod(1 + ind['ew_ret'][d0:d1]) - 1)


CANDIDATES = {
    'C1': dict(breakout=True, pullback=False),
    'C2': dict(breakout=False, pullback=True),
    'C3': dict(),
    'C4': dict(market_filter=True),
    'C5': dict(market_filter=True, dd_halving=True),
    'D4': dict(d4=True),
}


def run(market, cand, start, end, **over):
    p = load(market)
    cfg = replace(Config(market=market), **CANDIDATES[cand], **over)
    ind = indicators(p, cfg)
    ind['_close'] = p['close']
    orders, closes = signals(p, ind, cfg)
    curve, dates, trades = simulate(p, ind, cfg, start, end, orders, closes)
    return stats(curve, dates, trades), trades, benchmark(ind, p['dates'], start, end)


if __name__ == '__main__':
    market, cand, start, end = sys.argv[1:5]
    s, trades, bench = run(market, cand, start, end)
    print({k: (round(v, 4) if isinstance(v, float) else v) for k, v in s.items() if k != 'by_year'})
    print('by_year', {k: round(v, 3) for k, v in s['by_year'].items()}, 'bench', round(bench, 3))
