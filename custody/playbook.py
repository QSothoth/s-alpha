"""When a smart buy / smart sell acts: the scenario playbook v2 (studies/us_0dte_picks/notes/EXEC8_PREREG.md).

Pure functions. Inputs are completed same-day underlying 1m bars and the contract's completed option 1m bars
(traded minutes only); nothing later than the last completed minute is read, so replaying the day at every
minute is restart-safe. ``studies/us_0dte_picks/exec_eval.run_playbook2`` is the research twin; a parity test
keeps them identical.

Direction is the contract's own (CALL: the underlying up is favourable; PUT: down). A buy waits for pullbacks
and never takes a spike; a sell sells into strength (the first bar that fails to rise after a push) and leaves
weakness at once (below the day's low, a flush, losing VWAP). Protection: an executable price 10% worse than
the arrival acts at once. Urgency: the last 50% of the window allows 3 more bars, the last 20% acts at once
(a buy still skips one spike bar); a 0DTE window counts its remaining time at half after 14:30.
"""
from .evaluate import PRIMARY_FILL
from .indicators import SessionIndicators
from .strategy import session_minute

PLAYBOOK_ID = 'playbook_v2'
OPEN_MINUTES, SPIKE_ATR, SPIKE_OPTION, LATE_0DTE = 5, 2.0, .15, 300
GUARD = {'BUY': 1.10, 'SELL': 0.90}


class Snap:
    """Signed underlying state after one completed bar (CALL: price, PUT: minus price)."""
    __slots__ = ('c', 'hi', 'lo', 'vwap', 'e9', 'e21', 'atr', 'orh', 'day_low')

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

    @property
    def trend(self):
        return 1 if self.c > self.vwap and self.e9 > self.e21 else -1 if self.c < self.vwap and self.e9 < self.e21 else 0


def underlying_series(bars, session, sign):
    ind, out, lows = SessionIndicators(9, 21, 14, 15), {}, []
    for bar in bars:
        m = session_minute(session, bar.close_time)
        ind.update(bar, m)
        hi, lo = max(sign * bar.high, sign * bar.low), min(sign * bar.high, sign * bar.low)
        orh = (ind.or_high - ind.or_low) if ind.or_ready else (ind.high - ind.low)
        out[m] = Snap(c=sign * bar.close, hi=hi, lo=lo, vwap=sign * ind.vwap, e9=sign * ind.ema_fast,
                      e21=sign * ind.ema_slow, atr=ind.atr, orh=max(orh, ind.atr), day_low=min(lows) if lows else lo)
        lows.append(lo)
    return out


def executable(bar, side, fill=PRIMARY_FILL):
    return fill.buy(bar) if side == 'BUY' else fill.sell(bar)


def _thin(minutes, m):
    return sum(1 for x in minutes if m - 10 < x <= m) < 5


def _option_change(options, minutes, side, m, bars=3):
    seen = [x for x in minutes if x <= m][-(bars + 1):]
    if len(seen) < bars + 1:
        return None
    return executable(options[seen[-1]], side) / executable(options[seen[0]], side) - 1


def scenario(series, options, minutes, side, m):
    x = series[m]
    if m < OPEN_MINUTES:
        return 'open'
    back = series.get(m - 3)
    move = (x.c - back.c) / x.atr if back else 0.0
    change = None if _thin(minutes, m) else _option_change(options, minutes, side, m)
    if move >= SPIKE_ATR or (change is not None and change >= SPIKE_OPTION):
        return 'spike_up'
    if move <= -SPIKE_ATR or (change is not None and change <= -SPIKE_OPTION):
        return 'spike_down'
    if x.c - x.vwap > x.orh:
        return 'stretched'
    if x.c - x.vwap < -x.orh:
        return 'sunk'
    if x.trend == 1:
        return 'with'
    if x.trend == -1:
        return 'against'
    recent = [series[k] for k in range(m - 5, m) if k in series]
    if x.c > x.vwap and any(r.c < r.vwap for r in recent):
        return 'reclaim'
    if x.c < x.vwap and any(r.c > r.vwap for r in recent):
        return 'lose'
    return 'chop'


def acts(side, scen, series, m):
    x, p = series[m], series.get(m - 1)
    if scen == 'open':
        return False
    if scen == 'chop':
        recent = [series[k] for k in range(m - 9, m + 1) if k in series]
        mid = (max(r.hi for r in recent) + min(r.lo for r in recent)) / 2
        return x.c <= mid if side == 'BUY' else x.c >= mid
    up = p is not None and x.c > p.c
    if side == 'BUY':
        pullback = p is not None and p.c <= p.e9 + .25 * p.atr and up
        rebuild = (up and x.lo >= p.lo) or x.c > x.vwap if p is not None else x.c > x.vwap
        return {'spike_up': pullback, 'spike_down': up, 'stretched': x.c - x.vwap <= .5 * x.orh, 'sunk': up,
                'with': pullback, 'against': rebuild, 'reclaim': True, 'lose': rebuild}[scen]
    fade = p is not None and x.c <= p.c
    prior = [series[k].c for k in range(m - 10, m - 1) if k in series]
    push = fade and bool(prior) and p.c >= max(prior)
    return {'spike_up': fade, 'stretched': fade, 'with': push, 'reclaim': push,
            'spike_down': True, 'sunk': True, 'against': True, 'lose': True}[scen]


def decide(side, series, options, start, end, arrival, zero_dte, until=None):
    """``(minute, trigger)`` of the first completed bar on which the order acts, or None.

    ``options`` maps a completed minute to its traded option bar; ``until`` is the last completed minute
    (default: everything given). At ``end`` without a decision the caller fills anyway (the deadline).
    """
    buy, total = side == 'BUY', max(end - start, 1)
    minutes = sorted(options)
    band = spike_wait = 0
    last = min(end, until if until is not None else end)
    for m in range(max(start, 1), last + 1):
        if m not in series:
            continue
        option = options.get(m)
        if option is not None and arrival:
            q = executable(option, side)
            if (q >= arrival * GUARD['BUY']) if buy else (q <= arrival * GUARD['SELL']):
                return m, 'protect'
        if _thin(minutes, m) and end - m <= 15:
            return m, 'thin_deadline'
        r = (end - m) / total
        if zero_dte and m >= LATE_0DTE:
            r /= 2
        scen = scenario(series, options, minutes, side, m)
        if not buy and scen != 'open' and series[m].c < series[m].day_low:
            return m, 'stop_low'
        ok, trigger = acts(side, scen, series, m), scen
        if not ok and r < .2:
            if buy and scen == 'spike_up' and spike_wait < 1:
                spike_wait += 1
            else:
                ok, trigger = True, 'urgency'
        elif not ok and r < .5:
            band += 1
            if band > 3:
                ok, trigger = True, 'urgency'
        if ok:
            return m, trigger
    return None
