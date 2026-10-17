"""Fidelity of a replication stage: does the stage output contain the trades the trader actually took?

A stage output is a boolean (days x codes) mask: True on day t means "on day t this stock is in our list"
(watchlist, setup or signal), computed only from information available at that decision time.
A trade is hit when the mask is True for its stock on any day of its window (exact trades: the day itself).
Recall alone rewards flagging everything, so it is always reported next to the mask's width and the recall a
random list of the same daily width would get (lift = recall / random recall).
"""
from __future__ import annotations

import numpy as np


def locate(trades, days, codes, prefix='US.', has=None):
    """Map trades to (trade, column, first day index, last day index); trades outside the panel (or, with `has`,
    without any bar in their window) are skipped and returned as missing."""
    col = {str(c): j for j, c in enumerate(codes)}
    out, missing = [], []
    for t in trades:
        j = col.get(prefix + t.ticker)
        a, b = np.searchsorted(days, t.window_lo), np.searchsorted(days, t.window_hi, side='right') - 1
        if j is None or a > b or a >= len(days) or (has is not None and not has[a:b + 1, j].any()):
            missing.append(t.id)
            continue
        out.append((t, j, int(a), int(b)))
    return out, missing


def recall(mask, located, pool=None):
    """Share of located trades whose stock is flagged on some day of its window, with a same-width random baseline.

    pool: optional (days x codes) mask of names the stage could have picked from; random baseline draws the same
    number of names per day from it (default: every name with data that day).
    """
    if not located:
        return dict(n=0, hits=0, recall=float('nan'), random=float('nan'), lift=float('nan'), per_trade={})
    pool = np.ones_like(mask, bool) if pool is None else pool
    width = (mask & pool).sum(1)
    size = np.maximum(pool.sum(1), 1)
    share = np.clip(width / size, 0, 1)
    per, base = {}, []
    for t, j, a, b in located:
        per[t.id] = bool(mask[a:b + 1, j].any())
        base.append(1 - np.prod(1 - share[a:b + 1]))
    hits = sum(per.values())
    r, rb = hits / len(located), float(np.mean(base))
    return dict(n=len(located), hits=hits, recall=r, random=rb, lift=r / rb if rb > 0 else float('nan'),
                per_trade=per)


def width(mask, days, lo, hi, pool=None):
    """Median and mean number of flagged names per day between ISO dates (and the mean share of the pool)."""
    m = (days >= lo) & (days <= hi)
    w = (mask & (pool if pool is not None else True))[m].sum(1)
    out = dict(median=float(np.median(w)), mean=float(np.mean(w)))
    if pool is not None:
        out['share'] = float(np.mean(w / np.maximum(pool[m].sum(1), 1)))
    return out


def funnel(stages, located, pool=None):
    """Recall after each cumulative stage: stages is a list of (name, mask); stage k is the AND of masks 0..k."""
    cur, rows = None, []
    for name, mask in stages:
        cur = mask if cur is None else cur & mask
        res = recall(cur, located, pool)
        rows.append(dict(stage=name, **{k: v for k, v in res.items() if k != 'per_trade'},
                         lost=[i for i, ok in res['per_trade'].items() if not ok]))
    return rows
