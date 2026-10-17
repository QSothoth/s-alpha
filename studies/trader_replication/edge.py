"""Edge of a stage against random entry on the same stocks.

The comparison is always within one day and one volatility group: flagged events vs unflagged events of the same
kind, so a stage that merely picks more volatile names scores zero.  Days are the resampling unit.
"""
from __future__ import annotations

import numpy as np


def groups(values, pool, rows, k=10):
    """Per-day k-quantile group of `values` among `pool` names (-1 outside the pool or on days with < 2k names)."""
    g = np.full(values.shape, -1, np.int8)
    for t in np.flatnonzero(rows):
        v = np.where(pool[t], values[t], np.nan)
        if np.isfinite(v).sum() >= 2 * k:
            edges = np.nanquantile(v, np.linspace(0, 1, k + 1)[1:-1])
            g[t] = np.where(pool[t] & np.isfinite(values[t]), np.searchsorted(edges, np.nan_to_num(values[t])), -1)
    return g


def excess(outcome, group, events, flag, rows, seed=0, draws=2000):
    """Mean over days of the group-weighted difference outcome[flagged events] - outcome[other events].

    outcome: (days x codes) forward result per event (NaN = unknown); events: the setups both sides share;
    flag: the stage being tested; rows: boolean day filter.  Returns the point estimate, a day-bootstrap 95%
    interval and the flagged events' own mean outcome.
    """
    ev = events & np.isfinite(outcome) & (group >= 0)
    diffs, inside, n = [], [], []
    for t in np.flatnonzero(rows):
        a = ev[t] & flag[t]
        if not a.any():
            continue
        z = ev[t] & ~flag[t]
        d, w = [], []
        for k in np.unique(group[t, a]):
            ak, zk = a & (group[t] == k), z & (group[t] == k)
            if zk.any():
                d.append(outcome[t, ak].mean() - outcome[t, zk].mean())
                w.append(ak.sum())
        if w:
            diffs.append(float(np.average(d, weights=w)))
            inside.append(float(outcome[t, a].mean()))
            n.append(int(a.sum()))
    if not diffs:
        return dict(days=0)
    x = np.array(diffs)
    boots = np.random.default_rng(seed).choice(x, (draws, len(x))).mean(axis=1)
    return dict(days=len(x), events_per_day=float(np.mean(n)), inside=float(np.mean(inside)), excess=float(x.mean()),
                ci=[float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))])


def forward(close, open_, horizon=10):
    """Return from the next day's open to the close `horizon` days later (entry the morning after the signal)."""
    o1 = np.full_like(close, np.nan)
    o1[:-1] = open_[1:]
    out = np.full_like(close, np.nan)
    if len(close) > horizon:
        out[:-horizon] = close[horizon:] / o1[:-horizon] - 1
    return out
