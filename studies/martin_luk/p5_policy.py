"""P5 market-only nominations, close-stop entry adapter and percentile breadth."""
from __future__ import annotations

import numpy as np

from . import p3_signal as S, p4_policy as P4
from studies.trader_replication import allocation, regime as R

CANDIDATES = ('S1_NOBLOCK', 'S2_CLOSESTOP', 'S3_BOTH')
REGIMES = ('B3_PCT3', 'B4_PCT2')


def nominations(A, candidate):
    if candidate not in CANDIDATES:
        raise ValueError('unknown P5 candidate')
    raw = {t: A['ordered'].get(str(day), []) for t, day in enumerate(A['days'][:-1])}
    return allocation.nominations(raw, maximum=3, cooldown=10 if candidate == 'S2_CLOSESTOP' else 0)


def entries(A, picks, index_ok, *, soft=False, use_index=True):
    out = P4.entries(A, picks, 'X1_OPEN', [[] for _ in A['days']], index_ok, use_index=use_index)
    if soft:
        # Day-zero hard/close stops execute inside the engine after all opening admissions.
        for key in ('raw', 'filtered', 'offered'):
            out[key] = [list(e[:6] + (None,) + e[7:] for e in row) for row in out[key]]
    return out


def breadth(A, changes=None):
    spec = dict(S.DEFAULTS, fraction=.30)
    spec.update(changes or {})
    n, m = A['close'].shape
    means = [np.full(m, np.nan) for _ in range(3)]
    leaders, laggards, sizes = (np.zeros(n, int) for _ in range(3))
    cutoffs = np.full(n, np.nan)
    for t in range(n):
        close = np.asarray(A['close'][t], float)
        valid = np.isfinite(close) & (close > 0)
        for values, length in zip(means, (spec['e9'], spec['e21'], spec['e50'])):
            fresh = valid & ~np.isfinite(values)
            values[fresh] = close[fresh]
            update = valid & ~fresh
            alpha = 2 / (length + 1)
            values[update] = alpha * close[update] + (1 - alpha) * values[update]
        adr = np.asarray(A['adr'][t], float)
        liquid = valid & (A['to20'][t] >= spec['turnover']) & np.isfinite(adr) & (adr > 0)
        if liquid.any():
            # The quantile uses only tonight's liquid names; include exact boundary ties.
            cutoffs[t] = np.quantile(adr[liquid], 1 - spec['fraction'])
        eligible = liquid & (adr >= cutoffs[t])
        sizes[t] = np.sum(eligible)
        a, b, c = means
        leaders[t] = np.sum(eligible & (a > b) & (b > c))
        laggards[t] = np.sum(eligible & (a < b) & (b < c))
    net = leaders - laggards
    fast, slow = R.ema(net, spec['width_fast']), R.ema(net, spec['width_slow'])
    confirm, state = S.Confirm(), np.zeros(n, np.int8)
    for t in range(1, n):
        delta = fast[t - 1] - slow[t - 1]
        state[t] = confirm.update(1 if delta > 0 else -1 if delta < 0 else None)
    return dict(state=state, leaders=leaders, laggards=laggards, net=net,
                fast=fast, slow=slow, pool_size=sizes, adr_cutoff=cutoffs)


def timeline(A, picks, width, candidate, threshold=.5):
    if candidate not in REGIMES:
        raise ValueError('unknown P5 regime')
    columns = {str(c): j for j, c in enumerate(A['codes'])}
    n = len(A['days'])
    initial = R.PULLBACK if candidate == 'B3_PCT3' else R.WEAK
    label, raw, fstate = np.full(n, initial, np.int8), np.full(n, initial, np.int8), np.zeros(n, np.int8)
    feedback, final = S.Confirm(), S.Confirm()
    final.current = initial
    outcomes = []
    for t in range(n):
        judged = S.feedback(A, t, picks, columns)
        rate = sum(r['good'] for r in judged) / len(judged) if judged else None
        fstate[t] = feedback.update((1 if rate >= threshold else -1) if len(judged) >= 5 else None)
        state = R.UP if width[t] == 1 and fstate[t] == 1 else (
            R.WEAK if candidate == 'B4_PCT2' or width[t] == -1 and fstate[t] == -1 else R.PULLBACK)
        raw[t], label[t] = state, final.update(state)
        outcomes.append(dict(day=t, n=len(judged), rate=rate,
            latest_known=max((r['known'] for r in judged), default=None),
            latest_nomination=max((r['night'] for r in judged), default=None)))
    return dict(label=label, raw=raw, feedback=fstate, outcomes=outcomes)


def perturbations():
    yield from ((label, change) for label, change in S.perturbations() if 'adr' not in change)
    for fraction in (.25, .35):
        yield f'fraction={fraction}', dict(fraction=fraction)
