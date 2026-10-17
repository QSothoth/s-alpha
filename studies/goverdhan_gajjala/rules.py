"""Causal demand/organic-pullback hypotheses; not authenticated champion code."""
from dataclasses import dataclass
from datetime import datetime, timedelta

@dataclass(frozen=True)
class Bar:
    t: datetime
    o: float
    h: float
    l: float
    c: float
    v: float


def aggregate(minutes):
    groups = {}
    for b in minutes:
        if (9, 30) <= (b.t.hour, b.t.minute) < (16, 0):
            key = b.t.replace(minute=b.t.minute // 5 * 5, second=0)
            groups.setdefault(key, []).append(b)
    result = []
    for t, bs in sorted(groups.items()):
        bs = sorted(bs, key=lambda b: b.t)
        if len(bs) == 5 and [b.t for b in bs] == [t + timedelta(minutes=i) for i in range(5)]:
            result.append(Bar(t + timedelta(minutes=5), bs[0].o, max(b.h for b in bs), min(b.l for b in bs), bs[-1].c, sum(b.v for b in bs)))
    return result


def features(bars):
    e9 = e21 = None
    result = []
    cumulative = 0
    day = None
    for i, b in enumerate(bars):
        if day != b.t.date():
            day, cumulative = b.t.date(), 0
        cumulative += b.c * b.v
        e9 = b.c if e9 is None else e9 + .2 * (b.c - e9)
        e21 = b.c if e21 is None else e21 + (2 / 22) * (b.c - e21)
        result.append((e9, e21, cumulative, i >= 104))
    return result


def setups(bars, variant='domain'):
    fs = features(bars)
    previous_close = {}
    for i, b in enumerate(bars):
        if b.t.hour == 16 and b.t.minute == 0:
            previous_close[b.t.date()] = b.c
    used, out = set(), []
    for i, b in enumerate(bars):
        e9, e21, turnover, warm = fs[i]
        if not warm or not (9, 45) <= (b.t.hour, b.t.minute) <= (15, 30) or turnover < 2e6:
            continue
        if variant == 'strict':
            continue  # Historical float is unknown; fail closed, never impute.
        if variant.startswith('nofloat'):
            priors = [d for d in previous_close if d < b.t.date()]
            if not priors or not 1 <= b.c <= 20 or b.c / previous_close[max(priors)] - 1 < .10:
                continue
        for count in (1, 2, 3):
            j = i - count - 1
            if j < 0 or j in used:
                continue
            a, z = bars[j:j+2]
            pull = bars[j+2:i+1]
            segment = bars[j:i+1]
            if any(x.t.date() != b.t.date() for x in segment) or any(y.t-x.t != timedelta(minutes=5) for x,y in zip(segment,segment[1:])):
                continue
            hi, lo = max(a.h, z.h), min(a.l, z.l)
            span = hi - lo
            if not (a.c > a.o and z.c > z.o and z.c > a.c and z.v >= a.v and span / lo >= .03):
                continue
            if min(x.l for x in pull) < hi - .5 * span:
                continue
            if not variant.endswith('noquiet') and sum(x.v for x in pull) / len(pull) >= (a.v+z.v)/2:
                continue
            if not variant.endswith('noema') and b.c <= e21:
                continue
            trigger, stop = b.h + .01, b.l - .01
            if trigger <= stop:
                continue
            used.add(j)
            out.append({'signal_at': b.t.isoformat(), 'information_cutoff': b.t.isoformat(), 'setup_id': bars[j].t.isoformat(), 'trigger': trigger, 'stop': stop, 'volume_cap': b.v*.01, 'expiry': (b.t+timedelta(minutes=5)).isoformat(), 'variant': variant})
            break
    return out


def entry_path(b, trigger, stop):
    """Adverse path when both prices touch; never favorable intrabar ordering."""
    if b.v <= 0:
        return 'waiting', None
    if b.o <= stop:
        return 'invalidated', None
    if b.h >= trigger:
        price = max(b.o, trigger)
        if price > trigger + .25*(trigger-stop):
            return 'gap_cancel', None
        return ('ambiguous_entry_stop' if b.l <= stop else 'entry'), price
    if b.l <= stop:
        return 'invalidated', None
    return 'waiting', None
