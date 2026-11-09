"""P4 fixed market-only entry translations and two-state producers."""
from __future__ import annotations

import numpy as np

from . import p3_signal as S
from studies.trader_replication import regime as R

CANDIDATES = ('X1_OPEN', 'X2_PRIOR_HIGH', 'X3_UNION')
REGIMES = ('B1_OR', 'B2_NOADR')
KINDS = ('p4_open', 'p4_high')


def stop_price(A, d, j, fill):
    low, adr = float(A['low'][d - 1, j]), float(A['adr'][d - 1, j])
    if not np.isfinite([low, adr, fill]).all() or min(low, adr, fill) <= 0:
        return None
    stop = max(low, fill * (1 - min(.5 * adr / 100, .05)))
    return stop if 0 < stop < fill else None


def entries(A, nominations, candidate, original, index_ok, *, use_index=True):
    """Consume price triggers before admission; preserve the frozen daily offer cap."""
    if candidate not in CANDIDATES:
        raise ValueError('unknown P4 entry candidate')
    ci = {str(c): j for j, c in enumerate(A['codes'])}
    n = len(A['days'])
    pending, raw, filtered, offered, audit = [], [], [], [], []
    for d in range(n):
        if d:
            pending.extend((d - 1, rank, ci[c]) for rank, c in enumerate(nominations.get(d - 1, [])))
        candidates, remaining = [], []
        master = original[d] if candidate == 'X3_UNION' else []
        master_names = {e[1] for e in master}
        for night, rank, j in pending:
            age = d - night
            if not 1 <= age <= (1 if candidate == 'X1_OPEN' else 3):
                continue
            opening, high = float(A['open'][d, j]), float(A['high'][d, j])
            if candidate == 'X1_OPEN':
                hit, fill, kind = True, opening, KINDS[0]
            else:
                level = float(A['high'][night, j])
                hit = bool(np.isfinite(level) and np.isfinite(high) and high > level)
                fill, kind = max(opening, level), KINDS[1]
            if not hit:
                remaining.append((night, rank, j))
                continue
            stop = stop_price(A, d, j, fill)
            detail = 'master_duplicate' if j in master_names else 'invalid_stop' if stop is None else 'trigger'
            audit.append(dict(day=str(A['days'][d]), code=str(A['codes'][j]),
                night=str(A['days'][night]), night_index=night, age=age, rank=rank,
                fill=fill, stop=stop, reason=detail))
            if detail != 'trigger' or not np.isfinite(opening) or opening <= 0:
                continue
            # An opening fill has the whole session ahead. A level fill has unknown OHLC ordering;
            # taking the stop when the day's low crosses it is the conservative daily-bar convention.
            day_exit = stop if np.isfinite(A['low'][d, j]) and A['low'][d, j] <= stop else None
            candidates.append(((1, night, rank), j, 1, fill, stop, kind, day_exit))
        pending = remaining
        old = [((0, e[0]),) + tuple(e[1:]) for e in master]
        row = sorted(old + candidates, key=lambda e: e[0])
        raw.append(row)
        allowed = row if not use_index or index_ok[d] else []
        filtered.append(allowed)
        offered.append(allowed[:4])
    return dict(raw=raw, filtered=filtered, offered=offered, triggers=audit,
                timing_assumption=candidate == 'X3_UNION')


def breadth(A, noadr=False, changes=None):
    spec = dict(S.DEFAULTS, **(changes or {}))
    n, m = A['close'].shape
    means = [np.full(m, np.nan) for _ in range(3)]
    leaders, laggards = np.zeros(n, int), np.zeros(n, int)
    for t in range(n):
        close = np.asarray(A['close'][t], float)
        valid = np.isfinite(close) & (close > 0)
        for values, length in zip(means, (spec['e9'], spec['e21'], spec['e50'])):
            fresh = valid & ~np.isfinite(values)
            values[fresh] = close[fresh]
            update = valid & ~fresh
            alpha = 2 / (length + 1)
            values[update] = alpha * close[update] + (1 - alpha) * values[update]
        eligible = valid & (A['to20'][t] >= spec['turnover'])
        if not noadr:
            eligible &= A['adr'][t] >= spec['adr']
        a, b, c = means
        leaders[t] = np.sum(eligible & (a > b) & (b > c))
        laggards[t] = np.sum(eligible & (a < b) & (b < c))
    net = leaders - laggards
    fast, slow = R.ema(net, spec['width_fast']), R.ema(net, spec['width_slow'])
    confirmed, state = S.Confirm(), np.zeros(n, np.int8)
    for t in range(1, n):
        delta = fast[t - 1] - slow[t - 1]
        state[t] = confirmed.update(1 if delta > 0 else -1 if delta < 0 else None)
    return dict(state=state, leaders=leaders, laggards=laggards, net=net, fast=fast, slow=slow)


def timeline(A, nominations, width, threshold=.5):
    columns = {str(c): j for j, c in enumerate(A['codes'])}
    n = len(A['days'])
    label, fstate = np.full(n, R.WEAK, np.int8), np.zeros(n, np.int8)
    feedback, final = S.Confirm(), S.Confirm()
    final.current = R.WEAK
    outcomes, raw = [], np.full(n, R.WEAK, np.int8)
    for t in range(n):
        judged = S.feedback(A, t, nominations, columns)
        rate = sum(r['good'] for r in judged) / len(judged) if judged else None
        fstate[t] = feedback.update((1 if rate >= threshold else -1) if len(judged) >= 5 else None)
        state = R.WEAK if width[t] == -1 or fstate[t] == -1 else (
            R.UP if width[t] == 1 and fstate[t] == 1 else None)
        raw[t] = final.current if state is None else state
        label[t] = final.update(state)
        outcomes.append(dict(day=t, n=len(judged), rate=rate,
            latest_known=max((r['known'] for r in judged), default=None),
            latest_nomination=max((r['night'] for r in judged), default=None)))
    return dict(label=label, feedback=fstate, raw=raw, outcomes=outcomes)


def perturbations(noadr):
    return [(label, change) for label, change in S.perturbations() if not (noadr and 'adr' in change)]
