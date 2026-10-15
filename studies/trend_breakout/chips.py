"""PB24 (notes/PB24_PREREG.md): turnover, a turnover-decayed cost line and a chip (cost) distribution from daily
bars only. Every value at row t uses rows up to and including t.

Turnover is volume over *total* shares (no float-share history is stored), so it understates true float turnover.
"""
from __future__ import annotations

import numpy as np


def turnover_rate(p):
    """Daily volume / total shares (shares = point-in-time market cap / raw close), clipped to [0, 1]."""
    shares = p['mktcap'] / p['raw_close']
    h = p['volume'] / shares
    h[~np.isfinite(h)] = np.nan
    return np.clip(h, 0., 1.)


def average_price(p):
    """Amount / volume on the adjusted price scale; (high + low + close) / 3 where that is missing."""
    raw = p['turnover'] / p['volume']
    adj = raw * p['close'] / p['raw_close']
    typical = (p['high'] + p['low'] + p['close']) / 3
    ok = np.isfinite(adj) & (adj >= p['low'] * .98) & (adj <= p['high'] * 1.02)
    return np.where(ok, adj, typical)


def cost_line(close, price, h):
    """cost_t = (1 - h_t) cost_{t-1} + h_t price_t; starts at the first close, unchanged on missing days."""
    cost = np.full(close.shape, np.nan)
    current = np.full(close.shape[1], np.nan)
    for t in range(len(close)):
        start = np.isnan(current) & np.isfinite(close[t])
        current[start] = close[t][start]
        ok = np.isfinite(h[t]) & np.isfinite(price[t]) & ~start
        current[ok] = (1 - h[t][ok]) * current[ok] + h[t][ok] * price[t][ok]
        cost[t] = current
    return cost


def profit_ratio(high, low, close, h, rows, step=.01, floor=.01, top=20000.):
    """Share of chips priced at or below the close, at the requested rows. Each day the existing chips shrink by
    (1 - h) and h is spread evenly over the day's low..high on a log-price grid."""
    edges = np.exp(np.arange(np.log(floor), np.log(top) + step, step))
    n_bins = len(edges)
    stocks = close.shape[1]
    state = np.zeros((stocks, n_bins), np.float32)
    out = np.full((len(rows), stocks), np.nan)
    wanted = {int(r): i for i, r in enumerate(rows)}
    idx = np.arange(stocks)
    for t in range(len(close)):
        ok = np.isfinite(high[t]) & np.isfinite(low[t]) & np.isfinite(h[t]) & (low[t] > 0)
        if ok.any():
            j = idx[ok]
            state[j] *= (1 - h[t][j])[:, None].astype(np.float32)
            # Bin i holds prices in [edges[i], edges[i + 1]); the same rule places chips and the close.
            lo = np.clip(np.searchsorted(edges, low[t][j], side='right') - 1, 0, n_bins - 1)
            hi = np.clip(np.searchsorted(edges, high[t][j], side='right') - 1, 0, n_bins - 1)
            width = (hi - lo + 1).astype(np.float32)
            add = np.zeros((len(j), n_bins + 1), np.float32)
            add[np.arange(len(j)), lo] += h[t][j] / width
            add[np.arange(len(j)), hi + 1] -= h[t][j] / width
            state[j] += np.cumsum(add[:, :n_bins], axis=1)
        if t in wanted:
            c = close[t]
            have = np.isfinite(c) & (c > 0)
            k = np.clip(np.searchsorted(edges, c[have], side='right') - 1, -1, n_bins - 1)
            cum = np.cumsum(state[have], axis=1)
            total = cum[:, -1]
            below = np.where(k >= 0, cum[np.arange(len(k)), np.maximum(k, 0)], 0.)
            out[wanted[t], have] = np.where(total > 0, below / np.maximum(total, 1e-12), np.nan)
    return out
