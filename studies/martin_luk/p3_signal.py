"""P3 market and own-nomination feedback. No evaluation labels or accounts."""
from __future__ import annotations

import numpy as np

from studies.trader_replication import regime as R

CANDIDATES = ('C1_TIER', 'C2_NEAR21', 'C3_UPGRADE', 'C4_STATE', 'C5_COMBO')
DEFAULTS = dict(e9=9, e21=21, e50=50, width_fast=10, width_slow=30,
                turnover=100e6, adr=4., feedback=.5)


class Confirm:
    def __init__(self):
        self.current, self.pending, self.count = 0, None, 0

    def update(self, value):
        if value is None:
            self.pending, self.count = None, 0
            return self.current
        self.count = self.count+1 if value == self.pending else 1
        self.pending = value
        if self.count >= 3:
            self.current = value
        return self.current


def breadth(A, changes=None):
    """Stream completed sessions; publish each observation on the next session."""
    spec = dict(DEFAULTS, **(changes or {}))
    n, m = A['close'].shape
    means = [np.full(m, np.nan) for _ in range(3)]
    leaders, laggards = np.zeros(n, int), np.zeros(n, int)
    for t in range(n):
        c = np.asarray(A['close'][t], float)
        valid = np.isfinite(c) & (c > 0)
        for values, length in zip(means, (spec['e9'], spec['e21'], spec['e50'])):
            fresh = valid & ~np.isfinite(values)
            values[fresh] = c[fresh]
            update = valid & ~fresh
            alpha = 2/(length+1)
            values[update] = alpha*c[update]+(1-alpha)*values[update]
        eligible = valid & (A['to20'][t] >= spec['turnover']) & (A['adr'][t] >= spec['adr'])
        a, b, c = means
        leaders[t] = np.sum(eligible & (a > b) & (b > c))
        laggards[t] = np.sum(eligible & (a < b) & (b < c))
    net = leaders-laggards
    fast, slow = R.ema(net, spec['width_fast']), R.ema(net, spec['width_slow'])
    confirmed, state = Confirm(), np.zeros(n, np.int8)
    for t in range(1, n):
        delta = fast[t-1]-slow[t-1]
        state[t] = confirmed.update(1 if delta > 0 else -1 if delta < 0 else None)
    return dict(state=state, leaders=leaders, laggards=laggards, net=net, fast=fast, slow=slow)


def perturbations():
    for key in ('e9', 'e21', 'e50', 'width_fast', 'width_slow'):
        for step in (-2, 2):
            yield f'{key}={DEFAULTS[key]+step}', {key: DEFAULTS[key]+step}
    for key in ('turnover', 'adr'):
        for scale in (.75, 1.25):
            yield f'{key}={DEFAULTS[key]*scale:g}', {key: DEFAULTS[key]*scale}
    for value in (.4, .6):
        yield f'feedback={value}', dict(feedback=value)


def percentile(values):
    """Finite cross-section midranks, including ties; no fitted boundaries."""
    values = np.asarray(values, float)
    result = np.full(len(values), .5)
    valid = np.isfinite(values)
    ordered = np.sort(values[valid])
    if len(ordered):
        x = values[valid]
        result[valid] = (np.searchsorted(ordered, x, 'left')+
                         np.searchsorted(ordered, x, 'right'))/(2*len(ordered))
    return result


def near21_order(A, t, names, columns):
    indices = [columns[c] for c in names]
    with np.errstate(invalid='ignore', divide='ignore'):
        distance = np.abs(A['close'][t, indices]/A['e21'][t, indices]-1)/(A['adr'][t, indices]/100)
    proximity = percentile(-np.maximum(distance-4, 0))
    inside = np.asarray([A['inside'].get(str(A['days'][t]), {}).get(c, .5) for c in names], float)
    score = np.nan_to_num(inside, nan=.5)+proximity
    return [names[k] for k in np.argsort(-score, kind='stable')]


def tier_order(ordered, tiers, upgrades):
    groups = [[c for c in ordered if tiers[c] == k] for k in range(3)]
    ratios = [sum(upgrades[c] for c in group)/len(group) if group else -1. for group in groups]
    first, second, _ = sorted(range(3), key=lambda k: (-ratios[k], k))
    preferred = groups[first][:2]+groups[second][:1]
    return list(dict.fromkeys(preferred+ordered))[:5]


def order(A, t, candidate, state, columns):
    names = list(A['ordered'].get(str(A['days'][t]), []))
    tiers = {c: int(A['to20'][t, columns[c]] >= 100e6)+int(A['to20'][t, columns[c]] >= 1e9) for c in names}
    upgrades = {c: bool(A['upgrade'][t, columns[c]]) for c in names}
    if candidate == 'C3_UPGRADE' or (candidate in ('C4_STATE', 'C5_COMBO') and state == R.UP):
        ranked = sorted(names, key=lambda c: not upgrades[c])
    elif candidate in ('C2_NEAR21', 'C4_STATE', 'C5_COMBO'):
        ranked = near21_order(A, t, names, columns)
    else:
        ranked = names
    if candidate in ('C4_STATE', 'C5_COMBO') and state == R.WEAK:
        ranked = [c for c in ranked if tiers[c] == 2]
    return tier_order(ranked, tiers, upgrades) if candidate in ('C1_TIER', 'C5_COMBO') else ranked[:5]


def feedback(A, night, nominations, columns):
    """Only bars completed before this session; missing bars are not outcomes."""
    judged = []
    for s in range(max(0, night-10), night):
        if s+2 > night-1:
            continue
        for code in nominations.get(s, ()):
            j = columns[code]
            opening, low = A['open'][s+1, j], A['low'][s+1, j]
            closes = A['close'][s+1:s+3, j]
            if not (np.isfinite(opening) and opening > 0 and np.isfinite(low) and low > 0
                    and np.all(np.isfinite(closes) & (closes > 0))):
                continue
            judged.append(dict(night=s, code=code, known=s+2, good=bool(np.all(closes >= low))))
    return judged


def timeline(A, candidate, width, *, threshold=.5, single=False):
    if candidate not in CANDIDATES:
        raise ValueError('unknown P3 candidate')
    columns = {str(c): j for j, c in enumerate(A['codes'])}
    n = len(A['days'])
    labels, fstate = np.full(n, R.PULLBACK, np.int8), np.zeros(n, np.int8)
    picks, nominations, last, outcomes = {}, {}, {}, []
    confirm = Confirm()
    for t in range(n):
        judged = feedback(A, t, nominations, columns)
        rate = sum(r['good'] for r in judged)/len(judged) if judged else None
        fstate[t] = confirm.update((1 if rate >= threshold else -1) if len(judged) >= 5 else None)
        state = R.UP if width[t] == 1 and fstate[t] == 1 else (
            R.WEAK if width[t] == -1 and fstate[t] == -1 else R.PULLBACK)
        labels[t] = R.PULLBACK if single else state
        picks[t] = order(A, t, candidate, int(labels[t]), columns)
        new = []
        for code in picks[t]:
            if t-last.get(code, -11) <= 10:
                continue
            new.append(code)
            last[code] = t
            if len(new) == 3:
                break
        nominations[t] = new
        outcomes.append(dict(day=t, n=len(judged), good=sum(r['good'] for r in judged), rate=rate,
            latest_known=max((r['known'] for r in judged), default=None),
            latest_nomination=max((r['night'] for r in judged), default=None)))
    return dict(picks=picks, new=nominations, label=labels, feedback=fstate, outcomes=outcomes)


def first_retests(close, high, ema50):
    """Consume the first 50-EMA rally after a downcross, even if no trade fills."""
    out = np.zeros(len(close), bool)
    armed = False
    for t in range(1, len(close)):
        if t >= 2 and np.isfinite(close[t-2:t]).all() and np.isfinite(ema50[t-2:t]).all():
            if close[t-2] >= ema50[t-2] and close[t-1] < ema50[t-1]:
                armed = True
            elif close[t-1] >= ema50[t-1]:
                armed = False
        if armed and np.isfinite(high[t]) and high[t] >= ema50[t-1]:
            out[t], armed = True, False
    return out
