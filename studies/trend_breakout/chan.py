"""PB16 (notes/PB16_PREREG.md): weekly bars and a simplified, causal Chan structure (inclusion, fractals, strokes,
stroke-level pivot), with pullback buy points W3B (third buy) and W2B (second buy, no divergence test).

Every output at week w uses weekly bars up to and including w only.
"""
from __future__ import annotations

from datetime import date

import numpy as np

from .portfolio import Account

FIELDS = ('open', 'high', 'low', 'close', 'raw_open', 'raw_high', 'raw_low', 'raw_close')


def week_rows(dates):
    """(first, last) daily row of every calendar (ISO) week, in order."""
    keys = [date.fromisoformat(str(d)).isocalendar()[:2] for d in dates]
    starts = [0] + [i for i in range(1, len(keys)) if keys[i] != keys[i - 1]]
    ends = [s - 1 for s in starts[1:]] + [len(keys) - 1]
    return np.array(starts), np.array(ends)


def weekly(p):
    """Weekly panel from a daily one: first valid open, max high, min low, last valid close per stock."""
    first, last = week_rows(p['dates'])
    out = {'dates': np.array([str(p['dates'][b]) for b in last]), 'codes': p['codes'], 'first': first, 'last': last}
    n = p['close'].shape[1]
    cols = np.arange(n)
    for field in FIELDS:
        x = p[field]
        w = np.full((len(first), n), np.nan)
        for i, (a, b) in enumerate(zip(first, last)):
            block = x[a:b + 1]
            ok = np.isfinite(block)
            has = ok.any(axis=0)
            if field.endswith('open'):
                w[i, has] = block[ok.argmax(axis=0), cols][has]
            elif field.endswith('close'):
                w[i, has] = block[len(block) - 1 - ok[::-1].argmax(axis=0), cols][has]
            elif field.endswith('high'):
                w[i, has] = np.nanmax(block[:, has], axis=0)
            else:
                w[i, has] = np.nanmin(block[:, has], axis=0)
        out[field] = w
    return out


def _add_fractal(ends, f, min_gap=4):
    """Apply a confirmed fractal (kind +1 top / -1 bottom, price, merged index) to the stroke endpoints."""
    kind, price, k = f[:3]
    if not ends:
        ends.append(f)
        return 'append'
    last_kind, last_price, last_k = ends[-1][:3]
    if kind == last_kind:
        if (kind > 0 and price > last_price) or (kind < 0 and price < last_price):
            ends[-1] = f
            return 'extend'
        return None
    if k - last_k >= min_gap and ((kind > 0 and price > last_price) or (kind < 0 and price < last_price)):
        ends.append(f)
        return 'append'
    return None


def chan_stock(high, low, lookback=52, min_gap=4, weeks=False):
    """Per-week arrays for one stock: buy3/stop3, buy2/stop2, cap (previous top), support (latest confirmed
    bottom endpoint). A signal week is the week whose close confirms a new bottom endpoint. With ``weeks``, also
    the weeks of the last three endpoints (bottom, top, new bottom) and the new bottom's price at signal weeks."""
    n = len(high)
    buy3, buy2 = np.zeros(n, bool), np.zeros(n, bool)
    stop3, stop2, cap, support = (np.full(n, np.nan) for _ in range(4))
    w_low, w_top, w_bottom = (np.full(n, -1) for _ in range(3))
    bottom = np.full(n, np.nan)
    mh, ml, mw, ends = [], [], [], []
    current = np.nan
    for w in range(n):
        h, l = high[w], low[w]
        if not (np.isfinite(h) and np.isfinite(l)):
            support[w] = current
            continue
        if mh and ((h <= mh[-1] and l >= ml[-1]) or (h >= mh[-1] and l <= ml[-1])):
            if len(mh) < 2 or mh[-1] > mh[-2]:
                mh[-1], ml[-1] = max(mh[-1], h), max(ml[-1], l)
            else:
                mh[-1], ml[-1] = min(mh[-1], h), min(ml[-1], l)
            mw[-1] = w
        else:
            mh.append(h)
            ml.append(l)
            mw.append(w)
            k = len(mh) - 2
            if k >= 1:
                f = None
                if mh[k] > mh[k - 1] and mh[k] > mh[k + 1]:
                    f = (1, mh[k], k, mw[k])
                elif ml[k] < ml[k - 1] and ml[k] < ml[k + 1]:
                    f = (-1, ml[k], k, mw[k])
                if f is not None and _add_fractal(ends, f, min_gap) == 'append':
                    if len(ends) >= 2 and ends[-2][0] < 0:
                        current = ends[-2][1]
                    if f[0] < 0 and len(ends) >= 3:
                        e = ends
                        cap[w] = e[-2][1]
                        w_low[w], w_top[w], w_bottom[w], bottom[w] = e[-3][3], e[-2][3], e[-1][3], e[-1][1]
                        if len(e) >= 6:
                            zg, zd = min(e[-6][1], e[-4][1]), max(e[-5][1], e[-3][1])
                            if zg > zd and e[-2][1] > zg and e[-1][1] > zg:
                                buy3[w], stop3[w] = True, zg
                        recent = low[max(0, w - lookback + 1):w + 1]
                        floor = np.nanmin(recent)
                        if e[-1][1] > e[-3][1] and e[-3][1] <= floor + 1e-12:
                            buy2[w], stop2[w] = True, e[-3][1]
        support[w] = current
    if weeks:
        return buy3, stop3, buy2, stop2, cap, support, w_low, w_top, w_bottom, bottom
    return buy3, stop3, buy2, stop2, cap, support


def signals(high, low, weeks=False, **kwargs):
    """chan_stock for every column of weekly (weeks x stocks) highs and lows."""
    shape = high.shape
    out = [np.zeros(shape, bool), np.full(shape, np.nan), np.zeros(shape, bool), np.full(shape, np.nan),
           np.full(shape, np.nan), np.full(shape, np.nan)]
    if weeks:
        out += [np.full(shape, -1), np.full(shape, -1), np.full(shape, -1), np.full(shape, np.nan)]
        kwargs['weeks'] = True
    for j in range(shape[1]):
        for arr, col in zip(out, chan_stock(high[:, j], low[:, j], **kwargs)):
            arr[:, j] = col
    return tuple(out)


class PullbackAccount(Account):
    """Equal-weight slots; a fill is dropped (not retried) when the open is not below the signal's cap."""

    def __init__(self, p, priority, cost, cap, *, slots=10, weight=.10, risk_fraction=1.):
        super().__init__(p, priority, cost, slots=slots, risk_fraction=risk_fraction, position_cap=weight)
        self.cap, self.chased = cap, 0

    def allocate(self, t, fill, prices, stops, atr, signal):
        ok = fill.copy()
        for j in np.flatnonzero(fill):
            if not prices[j] < self.cap[signal[j], j]:
                ok[j] = False
                self.chased += 1
        return super().allocate(t, ok, prices, stops, atr, signal)
