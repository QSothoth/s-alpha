"""Causal market-only, mutually exclusive three-state label producers.

Labels for session t use completed data through t-1. No ledger, leg labels,
account or probability enters this module. Equal-weight baskets stream by day
or stock; memory is O(days + stocks), beyond the caller's market panel.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np

NAMES = ('up', 'pullback', 'weak')
UP, PULLBACK, WEAK = range(3)
DEFAULTS = dict(version=1, frozen='2026-11-08', producer='idx_ema', source='equal_weight',
                fast=21, slow=50, band=.01, fractal=10, breadth_ratio=1.5,
                price=5., turnover=20e6, lag=1)


def spec(options=None):
    out = dict(DEFAULTS, **(options or {}))
    if set(out)-set(DEFAULTS):
        raise ValueError('unknown regime specification field')
    if out['producer'] not in ('idx_ema', 'breadth', 'smc') or out['lag'] != 1:
        raise ValueError('one known producer and lag=1 required')
    for k in ('fast', 'slow', 'fractal'):
        if not isinstance(out[k], int) or isinstance(out[k], bool) or out[k] < 1:
            raise ValueError(k+' must be a positive integer')
    if not (out['fast'] < out['slow'] and np.isfinite(out['band']) and out['band'] >= 0
            and np.isfinite(out['breadth_ratio']) and out['breadth_ratio'] > 1
            and out['price'] > 0 and out['turnover'] > 0):
        raise ValueError('invalid regime thresholds')
    if out['producer'] == 'breadth' and out['source'] != 'equal_weight':
        raise ValueError('breadth uses the market basket, not an index price')
    return out


def spec_sha(options):
    return hashlib.sha256(json.dumps(spec(options), sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def ema(x, length):
    out = np.full(len(x), np.nan)
    value = np.nan
    for t, price in enumerate(x):
        if np.isfinite(price):
            value = price if not np.isfinite(value) else value+(price-value)*2/(length+1)
        out[t] = value
    return out


def _eligible(A, day, s):
    j = day-1
    return ((A.get('raw', A['close'])[j] >= s['price']) & (A['to20'][j] >= s['turnover'])
            & np.isfinite(A['close'][j]) & (A['close'][j] > 0)) if day else np.zeros(A['close'].shape[1], bool)


def index_prices(A, s):
    if s['source'] != 'equal_weight':
        sources = [s['source']] if isinstance(s['source'], str) else list(s['source'])
        if not sources:
            raise ValueError('empty index source')
        series = []
        for name in sources:
            bars = A['indices'][name]   # explicit input; never fetch or silently substitute
            c = np.asarray(bars['close'], float)
            valid = np.flatnonzero(np.isfinite(c) & (c > 0))
            scale = c[valid[0]] if len(valid) else np.nan
            series.append([np.asarray(bars.get(k, c), float)/scale for k in ('close', 'high', 'low')])
        return tuple(np.mean([row[k] for row in series], axis=0) for k in range(3))
    c, h, l = (np.ones(len(A['days'])) for _ in range(3))
    for t in range(1, len(c)):
        valid = _eligible(A, t, s) & np.isfinite(A['close'][t]) & (A['close'][t] > 0)
        if not valid.any():
            c[t] = h[t] = l[t] = c[t-1]
            continue
        previous = A['close'][t-1, valid].astype(float)
        c[t], h[t], l[t] = (c[t-1]*float(np.mean(A[k][t, valid]/previous)) for k in ('close', 'high', 'low'))
    return c, h, l


def idx_ema(A, s):
    c, _, _ = index_prices(A, s)
    fast, slow = ema(c, s['fast']), ema(c, s['slow'])
    return np.where(c < slow, WEAK, np.where(c > fast*(1+s['band']), UP, PULLBACK)).astype(np.int8)


def breadth(A, s):
    leaders, laggards = np.zeros(len(A['days']), int), np.zeros(len(A['days']), int)
    for j in range(A['close'].shape[1]):
        c = A['close'][:, j]
        fast, slow = ema(c, s['fast']), ema(c, s['slow'])
        eligible = np.r_[False, (A.get('raw', A['close'])[:-1, j] >= s['price']) &
                         (A['to20'][:-1, j] >= s['turnover'])]
        leaders += eligible & (c > fast) & (fast > slow)
        laggards += eligible & (c < fast) & (fast < slow)
    ratio = s['breadth_ratio']
    return np.where(leaders > ratio*laggards, UP,
                    np.where(laggards > ratio*leaders, WEAK, PULLBACK)).astype(np.int8)


def smc(A, s):
    c, high, low = index_prices(A, s)
    n, trend, upper, lower = s['fractal'], 0, None, None
    broken_up, broken_down = None, None
    label = np.full(len(c), PULLBACK, np.int8)
    for t in range(len(c)):
        p = t-n                 # the right half is now complete; never backdate the pivot
        if p >= n:
            if np.isfinite(high[p]) and high[p] == np.max(high[p-n:t+1]):
                upper = (p, high[p])
            if np.isfinite(low[p]) and low[p] == np.min(low[p-n:t+1]):
                lower = (p, low[p])
        if upper is not None and c[t] > upper[1] and broken_up != upper:
            broken_up, trend = upper, 1     # bullish BOS, or bullish CHoCH after a bearish structure
        elif lower is not None and c[t] < lower[1] and broken_down != lower:
            broken_down, trend = lower, -1
        if trend > 0 and c[t] > broken_up[1]:
            label[t] = UP
        elif trend < 0 and c[t] < broken_down[1]:
            label[t] = WEAK
    return label


def episodes(label, days):
    if len(label) != len(days):
        raise ValueError('states and calendar lengths differ')
    out = []
    for t, value in enumerate(label):
        state = NAMES[int(value)]
        if not out or out[-1]['state'] != state:
            out.append(dict(id=len(out), first=t, last=t, start=str(days[t]), end=str(days[t]), state=state))
        else:
            out[-1].update(last=t, end=str(days[t]))
    return out


def states(A, options=None):
    s = spec(options)
    raw = {'idx_ema': idx_ema, 'breadth': breadth, 'smc': smc}[s['producer']](A, s)
    label = np.r_[np.int8(PULLBACK), raw[:-1]] if len(raw) else raw
    parts = episodes(label, A['days'])
    return dict(label=label, episodes=parts, counts={name: dict(days=int(np.sum(label == k)),
        episodes=sum(p['state'] == name for p in parts)) for k, name in enumerate(NAMES)},
        spec=s, spec_sha=spec_sha(s))


def perturbations(options):
    s = spec(options)
    keys = {'idx_ema': ('fast', 'slow', 'band'), 'breadth': ('fast', 'slow', 'breadth_ratio'),
            'smc': ('fractal',)}[s['producer']]
    for key in keys:
        values = (s[key]-2, s[key]+2) if key == 'fractal' else (
            (s[key]*.5, s[key]*1.5) if key == 'band' else (s[key]*.8, s[key]*1.2))
        for value in values:
            value = max(1, round(value)) if key in ('fast', 'slow') else value
            yield f'{key}={value}', dict(s, **{key: value})


def stability(A, options=None, window=None):
    base = states(A, options)['label']
    mask = np.ones(len(base), bool) if window is None else ((A['days'] >= window[0]) & (A['days'] <= window[1]))
    rows = []
    for name, variant in perturbations(options):
        other = states(A, variant)['label']
        rows.append(dict(variant=name, agreement=float(np.mean(base[mask] == other[mask])) if mask.any() else None,
            by_state={state: (float(np.sum(mask & (base == k) & (other == k)))/
                int(np.sum(mask & ((base == k) | (other == k))))
                if np.any(mask & ((base == k) | (other == k))) else None) for k, state in enumerate(NAMES)}))
    minimum = min((r['agreement'] for r in rows if r['agreement'] is not None), default=None)
    return dict(variants=rows, minimum=minimum, ok=minimum is not None and minimum >= .9)

