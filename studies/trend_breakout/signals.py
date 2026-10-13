"""Entry signals and trailing lines for the TF1 candidates (notes/TF1_PREREG.md), shared by backtest and online scan.

    from studies.trend_breakout import panel, signals
    p = panel.load('data/trend-breakout-v1/us')
    ind = signals.indicators(p)                 # every indicator, computed once
    entry, line = signals.evaluate(ind, 'T1')   # (dates x stocks): signal at the close, trailing level at the close

Everything works on the date x stock panels and never looks at the market or the source. Indicators run on
each stock's own traded bars: a suspended day (NaN) is skipped, so it neither counts in a window nor moves a
line (``compact`` / ``scatter``). A value at row t only uses bars up to and including t.
"""
from __future__ import annotations

import numpy as np

MIN_BARS = 253  # 52-week high of the previous 252 bars plus today


def compact(x, valid):
    """Move each column's valid rows to the top (time order kept); returns the array and the row order."""
    order = np.argsort(~valid, axis=0, kind='stable')
    return np.take_along_axis(x, order, axis=0), order


def scatter(xc, order, valid, fill=np.nan):
    out = np.empty_like(xc)
    np.put_along_axis(out, order, xc, axis=0)
    out[~valid] = fill
    return out


def shift(x, k=1):
    out = np.full_like(x, np.nan)
    out[k:] = x[:-k]
    return out


def _rolling(x, w, fn):
    """fn-reduce over the last w rows (NaN for the first w - 1 rows) in O(log w) passes."""
    if len(x) < w:
        return np.full_like(x, np.nan)
    span, acc = 1, x.copy()
    while span * 2 <= w:  # acc[t] = fn(x[t - 2*span + 1 .. t])
        acc[span * 2 - 1:] = fn(acc[span * 2 - 1:], acc[span - 1:-span])
        acc[:span * 2 - 1] = np.nan
        span *= 2
    out = np.full_like(x, np.nan)
    rest = w - span
    out[w - 1:] = fn(acc[w - 1:], acc[span - 1:len(x) - rest]) if rest else acc[w - 1:]
    return out


def rolling_max(x, w):
    return _rolling(x, w, np.fmax) if w > 1 else x.copy()


def rolling_min(x, w):
    return _rolling(x, w, np.fmin) if w > 1 else x.copy()


def sma(x, w):
    out = np.full_like(x, np.nan)
    if len(x) < w:
        return out
    c = np.cumsum(np.nan_to_num(x), axis=0)
    out[w - 1] = c[w - 1]
    out[w:] = c[w:] - c[:-w]
    out = out / w
    out[np.isnan(x)] = np.nan
    return out


def _smooth(x, n, alpha):
    """Recursive average seeded with the simple mean of the first n values (Wilder RMA / EMA)."""
    out = np.full_like(x, np.nan)
    if len(x) < n:
        return out
    out[n - 1] = x[:n].mean(axis=0)
    for t in range(n, len(x)):
        out[t] = alpha * x[t] + (1 - alpha) * out[t - 1]
    return out


def ema(x, n):
    return _smooth(x, n, 2.0 / (n + 1))


def atr(high, low, close, n):
    prev = shift(close)
    tr = np.fmax(high - low, np.fmax(np.abs(high - prev), np.abs(low - prev)))
    tr[0] = high[0] - low[0]
    return _smooth(tr, n, 1.0 / n)


def supertrend(high, low, close, n=10, mult=3.0):
    """TradingView's Supertrend: returns (trend +1/-1, lower band). Exit = close below the previous lower band."""
    a = atr(high, low, close, n)
    hl2 = (high + low) / 2
    basic_up, basic_dn = hl2 - mult * a, hl2 + mult * a
    up, dn = basic_up.copy(), basic_dn.copy()
    trend = np.ones_like(close)
    for t in range(1, len(close)):
        keep_up = (close[t - 1] > up[t - 1]) & ~np.isnan(up[t - 1])
        up[t] = np.where(keep_up, np.fmax(basic_up[t], up[t - 1]), basic_up[t])
        keep_dn = (close[t - 1] < dn[t - 1]) & ~np.isnan(dn[t - 1])
        dn[t] = np.where(keep_dn, np.fmin(basic_dn[t], dn[t - 1]), basic_dn[t])
        prev = trend[t - 1]
        trend[t] = np.where((prev < 0) & (close[t] > dn[t - 1]), 1.0,
                            np.where((prev > 0) & (close[t] < up[t - 1]), -1.0, prev))
    return trend, up


def indicators(p):
    """All TF1 indicators on the panel's own trading days, returned on the panel's date rows."""
    valid = ~np.isnan(p['close'])
    c = {k: compact(p[k], valid)[0] for k in ('high', 'low', 'close', 'volume', 'turnover')}
    order = compact(p['close'], valid)[1]
    h, l, cl, v = c['high'], c['low'], c['close'], c['volume']
    n_bars = np.cumsum(~np.isnan(cl), axis=0)
    sma200 = sma(cl, 200)
    atr22 = atr(h, l, cl, 22)
    trend, st_line = supertrend(h, l, cl, 10, 3.0)
    mid20 = sma(cl, 20)
    sd20 = np.sqrt(np.maximum(sma(cl * cl, 20) - mid20 ** 2, 0))
    width = 4 * sd20 / mid20
    prev = shift(cl)
    gain, loss = np.fmax(cl - prev, 0), np.fmax(prev - cl, 0)
    gain[0] = loss[0] = 0.0
    rs_up, rs_dn = _smooth(gain, 2, 0.5), _smooth(loss, 2, 0.5)
    out = {
        'ready': n_bars >= MIN_BARS,
        'close': cl,
        'trend_ok': (cl > sma200) & (sma200 > shift(sma200, 20)),
        'ema200': ema(cl, 200),
        'hh252_prev': shift(rolling_max(h, 252)),
        'll252': rolling_min(l, 252),
        'hh55_prev': shift(rolling_max(h, 55)),
        'hh20_prev': shift(rolling_max(h, 20)),
        'vol50_prev': shift(sma(v, 50)),
        'volume': v,
        'st_flip_up': (trend > 0) & (shift(trend) < 0),
        'atr22': atr22,
        'chandelier': rolling_max(h, 22) - 3 * atr22,
        'donchian20': rolling_min(l, 20),
        'supertrend': st_line,
        'atr_trail': cl - 3 * atr22,
        'ret126': cl / shift(cl, 126) - 1,
        'ret21': cl / shift(cl, 21) - 1,
        'abn_turn': sma(c['turnover'], 20) / sma(c['turnover'], 250),
        'ret252_skip21': shift(cl, 21) / shift(cl, 252) - 1,
        'id126': sma((cl < prev).astype(float), 126) - sma((cl > prev).astype(float), 126),
        'bb_upper': mid20 + 2 * sd20,
        'squeeze': shift(rolling_min(width, 5)) <= shift(rolling_min(width, 126)),
        'sma50': sma(cl, 50),
        'rsi2': np.where(rs_dn > 0, 100 - 100 / (1 + rs_up / np.where(rs_dn > 0, rs_dn, 1)), 100.0),
        'up_move': cl - prev,
        'atr22_prev': shift(atr22),
        'mid_range': (h + l) / 2,
    }
    return {k: scatter(x.astype(float), order, valid, np.nan if x.dtype != bool else 0.0) for k, x in out.items()}


def _bool(x):
    return np.nan_to_num(x) > 0


def top_share(ind, pool, key='ret126', share=0.10):
    """Stocks whose ``key`` ranks in the pool's top ``share`` at the close (days with < 20 ranked: none)."""
    r = np.where(pool, ind[key], np.nan)
    ok = (~np.isnan(r)).sum(axis=1) >= 20
    cut = np.full(len(r), np.inf)
    cut[ok] = np.nanpercentile(r[ok], 100 * (1 - share), axis=1)
    return r >= cut[:, None]


def bottom_share(ind, pool, key, share=0.10):
    """Stocks whose ``key`` ranks in the pool's bottom ``share`` at the close (days with < 20 ranked: none)."""
    r = np.where(pool, ind[key], np.nan)
    ok = (~np.isnan(r)).sum(axis=1) >= 20
    cut = np.full(len(r), -np.inf)
    cut[ok] = np.nanpercentile(r[ok], 100 * share, axis=1)
    return r <= cut[:, None]


def at_most_pool_median(ind, pool, key):
    """``key`` at or below the median of the day's pool (days with < 20 values: none)."""
    r = np.where(pool, ind[key], np.nan)
    ok = (~np.isnan(r)).sum(axis=1) >= 20
    med = np.full(len(r), -np.inf)
    med[ok] = np.nanmedian(r[ok], axis=1)
    return ind[key] <= med[:, None]


def momentum_calm(ind, pool, vol_n=21, med_n=126):
    """Days when the momentum spread (yesterday's 126-day top 10% minus the pool, equal weight) has a
    vol_n-day volatility at or below its own med_n-day median; uses returns up to today's close only."""
    close = ind['close']
    top = top_share(ind, pool)
    r = close[1:] / close[:-1] - 1
    held, base = top[:-1] & ~np.isnan(r), pool[:-1] & ~np.isnan(r)
    spread = np.full(len(close), np.nan)
    ok = held.any(axis=1) & base.any(axis=1)
    spread[1:][ok] = (np.where(held, r, 0).sum(axis=1)[ok] / held.sum(axis=1)[ok]
                      - np.where(base, r, 0).sum(axis=1)[ok] / base.sum(axis=1)[ok])
    x = spread[:, None]
    vol = np.sqrt(np.maximum(sma(x * x, vol_n) - sma(x, vol_n) ** 2, 0))[:, 0]
    calm = np.zeros(len(close), bool)
    for t in range(len(close)):
        past = vol[max(0, t - med_n + 1):t + 1]
        if t >= med_n - 1 and not np.isnan(past).any():
            calm[t] = vol[t] <= np.median(past)
    return calm


def newly(top):
    prev = np.zeros_like(top)
    prev[1:] = top[:-1]
    return top & ~prev


def momentum_top(ind, pool, key='ret126'):
    """Newly entered the pool's top 10% by ``key`` today."""
    return newly(top_share(ind, pool, key))


def smooth_momentum(ind, pool):
    """Newly entered the 126-day top 10%, with information discreteness at or below the top group's median."""
    top = top_share(ind, pool)
    ids = np.where(top, ind['id126'], np.nan)
    has = top.any(axis=1)
    med = np.full(len(top), -np.inf)
    med[has] = np.nanmedian(ids[has], axis=1)
    return newly(top) & (ind['id126'] <= med[:, None])


def market_up(close, pool, n=200):
    """Pool equal-weight index (mean close-to-close return of yesterday's pool) above its n-day average."""
    r = close[1:] / close[:-1] - 1
    r = np.where(pool[:-1] & ~np.isnan(r), r, np.nan)
    has = (~np.isnan(r)).any(axis=1)
    day = np.zeros(len(r))
    day[has] = np.nanmean(r[has], axis=1)
    idx = np.concatenate([[1.0], np.cumprod(1 + day)])[:, None]
    return (idx > sma(idx, n))[:, 0]


ENTRIES = {
    'T1': lambda i: i['close'] > i['hh252_prev'],
    'T2': lambda i: i['close'] > i['hh55_prev'],
    'T3': lambda i: (i['close'] >= 1.2 * i['ll252']) & (i['close'] > i['hh20_prev']),
    'T4': lambda i: _bool(i['st_flip_up']) & (i['close'] > i['ema200']),
    'T5': lambda i: (i['close'] > i['hh55_prev']) & (i['volume'] >= 1.5 * i['vol50_prev']),
    # TF2 (notes/TF2_PREREG.md); U1 and U5 rank inside the pool
    'U1': lambda i, pool: momentum_top(i, pool),
    'U2': lambda i: _bool(i['squeeze']) & (i['close'] > i['bb_upper']),
    'U3': lambda i: (i['close'] > i['sma50']) & (i['rsi2'] <= 10),
    'U4': lambda i: (i['up_move'] >= 2 * i['atr22_prev']) & (i['volume'] >= 3 * i['vol50_prev'])
                    & (i['close'] >= i['mid_range']),
    'U5': lambda i, pool: momentum_top(i, pool) & market_up(i['close'], pool)[:, None],
    # TF3 (notes/TF3_PREREG.md); V1 = U1 and V2 = U5
    'V1': lambda i, pool: momentum_top(i, pool),
    'V2': lambda i, pool: momentum_top(i, pool) & market_up(i['close'], pool)[:, None],
    'V3': lambda i, pool: momentum_top(i, pool, 'ret252_skip21'),
    'V4': lambda i, pool: smooth_momentum(i, pool),
    'V5': lambda i, pool: momentum_top(i, pool, 'ret252_skip21') & market_up(i['close'], pool)[:, None],
    # TF4 (notes/TF4_PREREG.md); W1 and W2 skip the trend filter
    'W1': lambda i, pool: newly(bottom_share(i, pool, 'ret21')),
    'W2': lambda i, pool: newly(bottom_share(i, pool, 'ret21')) & at_most_pool_median(i, pool, 'abn_turn'),
    'W3': lambda i, pool: momentum_top(i, pool) & at_most_pool_median(i, pool, 'abn_turn'),
    'W4': lambda i, pool: momentum_top(i, pool) & momentum_calm(i, pool)[:, None],
}
LINES = {'T1': 'chandelier', 'T2': 'donchian20', 'T3': 'chandelier', 'T4': 'supertrend', 'T5': 'chandelier',
         **{r: 'atr_trail' for r in ('U1', 'U2', 'U3', 'U4', 'U5', 'V1', 'V2', 'V3', 'V4', 'V5',
                                     'W1', 'W2', 'W3', 'W4')}}
RATCHET = {'chandelier': True, 'donchian20': False, 'supertrend': False, 'atr_trail': True}
ROUNDS = {'tf1': ('T1', 'T2', 'T3', 'T4', 'T5'), 'tf2': ('U1', 'U2', 'U3', 'U4', 'U5'),
          'tf3': ('V1', 'V2', 'V3', 'V4', 'V5'), 'tf4': ('W1', 'W2', 'W3', 'W4'),
          'tf5': ('W4',)}  # TF5: W4 frozen, one test-segment check (notes/TF5_PREREG.md)
POOLED = {'U1', 'U5', 'V1', 'V2', 'V3', 'V4', 'V5', 'W1', 'W2', 'W3', 'W4'}
NO_TREND = {'W1', 'W2'}  # reversal buys the losers: only the history requirement applies
RULES = ROUNDS['tf1']


def trend_filter(ind):
    """Common filter F: close above a rising 200-day average, with enough history for every indicator."""
    return _bool(ind['ready']) & _bool(ind['trend_ok'])


def evaluate(ind, rule, pool=None):
    """(entry, line, ratchet): entry at row t is known at t's close; line is the trailing level at t's close.
    ``pool`` (dates x stocks, the day's universe) is needed by the rules that rank across stocks."""
    with np.errstate(invalid='ignore'):
        if rule in POOLED:
            if pool is None:
                pool = ~np.isnan(ind['close'])
            base = _bool(ind['ready']) if rule in NO_TREND else trend_filter(ind)
            entry = base & ENTRIES[rule](ind, pool)
        else:
            entry = trend_filter(ind) & ENTRIES[rule](ind)
    name = LINES[rule]
    return entry, ind[name], RATCHET[name]


def defensive_indicators(p):
    """TF8 (notes/TF8_PREREG.md): only what the anti-speculation candidates need, to keep memory small:
    ready, close, atr22, atr_trail, vol21 (std of daily returns), max21 (largest daily return), abn_turn."""
    valid = ~np.isnan(p['close'])
    c = {k: compact(p[k], valid)[0] for k in ('high', 'low', 'close', 'turnover')}
    order = compact(p['close'], valid)[1]
    cl = c['close']
    ret = cl / shift(cl) - 1
    atr22 = atr(c['high'], c['low'], cl, 22)
    out = {
        'ready': np.cumsum(~np.isnan(cl), axis=0) >= MIN_BARS,
        'close': cl,
        'atr22': atr22,
        'atr_trail': cl - 3 * atr22,
        'vol21': np.sqrt(np.maximum(sma(ret * ret, 21) - sma(ret, 21) ** 2, 0)),
        'max21': rolling_max(ret, 21),
        'abn_turn': sma(c['turnover'], 20) / sma(c['turnover'], 250),
    }
    del c
    return {k: scatter(x.astype(float), order, valid, np.nan if x.dtype != bool else 0.0) for k, x in out.items()}


def pool_percentile(x, pool):
    """Each value's rank within the day's pool, 0 (lowest) .. 1 (highest); NaN outside the pool."""
    out = np.full(x.shape, np.nan)
    for t in range(len(x)):
        idx = np.flatnonzero(pool[t] & ~np.isnan(x[t]))
        if len(idx) >= 20:
            out[t, idx[np.argsort(x[t, idx], kind='stable')]] = np.arange(len(idx)) / (len(idx) - 1)
    return out


def defensive_entry(ind, pool, rule):
    """Y1-Y4: newly entered the day's pool bottom 10% of vol21 / max21 / abn_turn / their mean percentile."""
    keys = {'Y1': ('vol21',), 'Y2': ('max21',), 'Y3': ('abn_turn',), 'Y4': ('vol21', 'max21', 'abn_turn')}[rule]
    if len(keys) == 1:
        score = {'s': ind[keys[0]]}
    else:
        score = {'s': np.mean([pool_percentile(ind[k], pool) for k in keys], axis=0)}
    with np.errstate(invalid='ignore'):
        return _bool(ind['ready']) & newly(bottom_share(score, pool, 's'))


def liquid(p, min_turnover, min_price=None):
    """Daily universe at each close: mean turnover of the stock's last 20 traded bars (and an unadjusted price floor)."""
    valid = ~np.isnan(p['close'])
    tc, order = compact(p['turnover'], valid)
    ok = scatter(sma(tc, 20), order, valid) >= min_turnover
    if min_price is not None:
        ok &= p['raw_close'] >= min_price
    return ok & valid
