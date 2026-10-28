"""David Trullas: Nasdaq-100 futures day trading, approximated on QQQ 1-minute bars (see notes/RULES_CN.md).

Prices are QQQ; NQ points = QQQ price move x NQ_PER_QQQ. Position size counts MNQ units ($2 per NQ point;
10 MNQ = 1 NQ). Every decision at bar i uses bars <= i only. A close-confirmed entry fills at the close of bar i
and is managed from bar i+1; a stop-order entry (the fib trigger) fills inside bar i, and that bar only counts
against us (its low below the stop = stopped, its high is not a target hit). Inside a bar the stop is checked
before the target; stop / BE / add changes made in a bar apply from the next bar.

Links (Cfg field groups): window (when), bias (daily trend), zone (prior levels / retrace), trigger
('macd': two swing lows with MACD divergence, + RSI / volume confirmations, fib 23.6% break entry, stop a tick
beyond the extreme, 38 / 50 / 66% targets; 'vol': new low on lower volume then reclaim, high-volume whip),
stop, BE, add, target, day limits, sizing (leverage on equity, one unit per confirmation, $2,500 start).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

NQ_PER_QQQ = 41.2          # his quoted NQ prices / QQQ on the same minutes (2026-06-01, 08-05); basis ignored
MNQ_USD = 2.0              # USD per NQ point per MNQ
TICK = 0.25 / NQ_PER_QQQ   # one NQ tick in QQQ dollars
START = 2500.0             # quarterly contest minimum deposit


@dataclass(frozen=True)
class Cfg:
    windows: tuple = ((510, 660),)    # entry windows, minutes ET (08:30-11:00: an hour before the open to after)
    bias: str = 'none'                # none | ema20: long only if prior daily close > EMA20 of daily closes
    zone: str = 'none'                # none | levels | fib | either
    zone_tol: float = 0.0012          # distance to a level as a fraction of price
    level_days: int = 3               # prior sessions used for levels
    trig: str = 'macd'                # macd | vol
    tf: int = 1                       # bar size in minutes for the macd trigger (1, 2, 5)
    piv: int = 3                      # swing low = lowest of piv bars each side (confirmed piv bars later)
    pair_look: int = 60               # max bars between the two swing lows
    hidden: bool = False              # also hidden divergence (higher low, lower MACD)
    fib_in: float = 0.236             # entry: break of low + fib_in * (top - low)
    max_chase: float = 0.382          # skip if the bar opens above this fib level
    expire: int = 10                  # bars the pending entry stays live after confirmation
    min_range: float = 20.0           # NQ points top - low, smaller swings skipped
    macd_drop: float = 0.0            # macd: require a session drop of this many NQ points from the high since 09:25
    confirm_units: bool = True        # units = MACD + RSI div + RSI extreme + volume div (1..4), else 1
    # 'open' trigger (his opening patterns A / B / C)
    open_sets: str = 'ABC'
    open_lows: int = 3                # A: consecutive new lows on falling volume
    open_drop: float = 100.0          # C: NQ points the session has dropped from its high since 09:25
    open_units: int = 2               # confirmation units given to an opening setup (1-4)
    mfail_gap: float = 0.25           # 'mfail': MACD-signal gap at the new low <= this share of its 20-bar max
    # 'vol' trigger
    div_look: int = 15
    reclaim_bars: int = 5
    whip_mult: float = 3.0
    stop_buf: float = 0.0001
    max_stop: float = 0.004
    min_stop: float = 0.0004
    # management
    be_at: float = 0.0                # move the stop to cost + be_plus once price gained be_at R (0 = off)
    be_plus: float = 1.5              # NQ points above (weighted) cost
    add_pts: float = 0.0              # add the same units again after +add_pts NQ points (0 = off)
    tgt: str = 'fib66'                # fib38 | fib50 | fib66 | r
    tgt_r: float = 3.5                # R target for 'r'
    shave: float = 0.25               # NQ points left before the target ("a tick before")
    drop_look: int = 120              # 'vol' trigger: bars back for the high the pullback started from
    stop_pts: float = 0.0             # cap the stop at this many NQ points below entry (0 = pattern stop)
    leg_bars: int = 0                 # far target on the bigger leg: high of the last leg_bars minutes (0 = off)
    leg_frac: float = 2 / 3           # far target = low + leg_frac x (that high - low)
    part_frac: float = 0.0            # close this share at the near (pattern) target, the rest runs to the far one
    max_hold: int = 60                # minutes
    max_trades: int = 5               # per day
    max_losses: int = 3               # losing trades per day before stopping
    day_target: float = 0.0           # stop the day once day P&L >= this fraction of start-of-day equity (0 off)
    lev: float = 40.0                 # notional / equity at full size (his 2-3 NQ on ~$40k)
    lev_hi: float = 0.0               # contest start: this leverage while equity < lev_until x start (0 = off;
    lev_until: float = 0.0            # 4 NQ minis on a few $k in 2026-04, 2 NQ on ~$40k once leading)
    risk: float = 0.0                 # if > 0, size by risk fraction of equity (still capped by lev)
    cost_pts: float = 1.0             # NQ points per MNQ round trip (commission + slippage)
    shorts: bool = False              # mirror setups on the short side (he does ~1-10% shorts)


def ema(x, n):
    a, out, e = 2 / (n + 1), np.empty(len(x)), x[0]
    for i, v in enumerate(x):
        e = v if i == 0 else a * v + (1 - a) * e
        out[i] = e
    return out


def rsi(c, n=14):
    d = np.diff(c, prepend=c[0])
    up, dn = np.maximum(d, 0), np.maximum(-d, 0)
    a = 1 / n
    out, gu, gd = np.empty(len(c)), 0.0, 0.0
    for i in range(len(c)):
        gu = (1 - a) * gu + a * up[i]
        gd = (1 - a) * gd + a * dn[i]
        out[i] = 100 if gd == 0 else 100 - 100 / (1 + gu / gd)
    return out


class Market:
    """Day slices, causal daily context and per-timeframe indicators, built from load()."""

    def __init__(self, px):
        self.px = px
        day = px['day']
        self.starts = np.searchsorted(day, np.arange(len(px['dates'])))
        self.ends = np.append(self.starts[1:], len(day))
        mins = px['mins']
        rth = (mins >= 570) & (mins < 960)
        nd = len(px['dates'])
        self.d_open = np.full(nd, np.nan); self.d_high = np.full(nd, np.nan)
        self.d_low = np.full(nd, np.nan); self.d_close = np.full(nd, np.nan)
        for d in range(nd):
            s, e = self.starts[d], self.ends[d]
            r = rth[s:e]
            if r.sum() < 300:
                continue
            idx = np.arange(s, e)[r]
            self.d_open[d] = px['o'][idx[0]]; self.d_close[d] = px['c'][idx[-1]]
            self.d_high[d] = px['h'][idx].max(); self.d_low[d] = px['l'][idx].min()
        ok = ~np.isnan(self.d_close)
        filled = self.d_close.copy()
        for d in range(1, nd):
            if not ok[d]:
                filled[d] = filled[d - 1]
        self.ema20 = ema(filled, 20)
        self.ok = ok
        self._piv, self._tf = {}, {}

    def bars(self, tf):
        """tf-minute bars aligned to each session's first minute: dict(o,h,l,c,v,last=index of last 1m bar,
        day, macd, sig, rsi). A tf bar is usable once its last 1m bar has closed."""
        if tf in self._tf:
            return self._tf[tf]
        px = self.px
        if tf == 1:
            b = dict(o=px['o'], h=px['h'], l=px['l'], c=px['c'], v=px['v'], last=np.arange(len(px['c'])),
                     day=px['day'])
        else:
            o, h, l, c, v, last, day = [], [], [], [], [], [], []
            for d in range(len(self.starts)):
                s, e = self.starts[d], self.ends[d]
                for k in range(s, e, tf):
                    k2 = min(k + tf, e)
                    o.append(px['o'][k]); h.append(px['h'][k:k2].max()); l.append(px['l'][k:k2].min())
                    c.append(px['c'][k2 - 1]); v.append(px['v'][k:k2].sum()); last.append(k2 - 1); day.append(d)
            b = {k: np.array(x) for k, x in dict(o=o, h=h, l=l, c=c, v=v, last=last, day=day).items()}
        m = ema(b['c'], 12) - ema(b['c'], 26)
        b['macd'], b['sig'], b['rsi'] = m, ema(m, 9), rsi(b['c'])
        b['start'] = np.searchsorted(b['day'], np.arange(len(self.starts)))
        b['end'] = np.append(b['start'][1:], len(b['day']))
        self._tf[tf] = b
        return b

    def pivots(self, d):
        """5-minute pivot highs / lows (2 bars each side) of session d, all hours, with the minute they are known."""
        if d in self._piv:
            return self._piv[d]
        s, e = self.starts[d], self.ends[d]
        px = self.px
        n5 = (e - s) // 5
        hs = np.array([px['h'][s + 5 * k:s + 5 * k + 5].max() for k in range(n5)])
        ls = np.array([px['l'][s + 5 * k:s + 5 * k + 5].min() for k in range(n5)])
        ends5 = np.array([px['mins'][s + 5 * k + 4] for k in range(n5)])
        out = []
        for k in range(2, n5 - 2):
            if hs[k] >= hs[k - 2:k + 3].max():
                out.append((ends5[k + 2], hs[k]))
            if ls[k] <= ls[k - 2:k + 3].min():
                out.append((ends5[k + 2], ls[k]))
        self._piv[d] = out
        return out

    def levels(self, d, cfg, upto_min):
        """Prior-session RTH open/high/low/close and 5m pivots, plus today's pivots known before upto_min."""
        lv = []
        for k in range(1, cfg.level_days + 1):
            if d - k < 0:
                break
            if self.ok[d - k]:
                lv += [self.d_open[d - k], self.d_high[d - k], self.d_low[d - k], self.d_close[d - k]]
            lv += [p for _, p in self.pivots(d - k)]
        lv += [p for m, p in self.pivots(d) if m < upto_min]
        return np.array(lv)


def _bias_ok(mk, d, cfg, side):
    if cfg.bias != 'ema20' or d == 0:
        return True
    prev = d - 1
    while prev > 0 and not mk.ok[prev]:
        prev -= 1
    return (mk.d_close[prev] > mk.ema20[prev]) == (side == 1)


def _in_zone(mk, d, cfg, side, low, ref, m, hi_arr, lo_arr, i):
    if cfg.zone == 'none':
        return True
    if cfg.zone in ('levels', 'either'):
        lv = mk.levels(d, cfg, m) * side
        if len(lv) and np.min(np.abs(lv - low)) <= cfg.zone_tol * abs(ref):
            return True
    if cfg.zone in ('fib', 'either'):
        a0 = max(0, i - 780)
        H = hi_arr[a0:i + 1].max()
        A = lo_arr[a0:a0 + int(np.argmax(hi_arr[a0:i + 1])) + 1].min()
        if H > A and 0.45 <= (H - low) / (H - A) <= 0.75:
            return True
    return False


def setups(mk, d, cfg, side=1):
    """Entries of session d for side 1 (long) / -1 (short): list of (1m bar, entry, stop, top, kind, units, intrabar).
    `top` is the far end of the swing the targets are measured on (the high for a long)."""
    if not _bias_ok(mk, d, cfg, side):
        return []
    out = []
    for t in cfg.trig.split('+'):
        out += {'macd': _macd_setups, 'vol': _vol_setups, 'open': _open_setups,
                'mfail': _mfail_setups}[t](mk, d, cfg, side)
    return sorted(out, key=lambda x: x[0])


def _mfail_setups(mk, d, cfg, side):
    """'MACD failure' (P1xgnJnf2PU 4:38-5:38): price makes a new low while the MACD line, above its signal line,
    dips towards it and fails to cross (gap shrinks to <= mfail_gap of its recent maximum), then turns up; enter at
    the close of the first bar that closes above the previous bar's high within reclaim_bars of the low."""
    b = mk.bars(cfg.tf)
    px = mk.px
    s, e = b['start'][d], b['end'][d]
    if side == 1:
        lo, hi, cl, gap = b['l'], b['h'], b['c'], b['macd'] - b['sig']
    else:
        lo, hi, cl, gap = -b['h'], -b['l'], -b['c'], b['sig'] - b['macd']
    last, mins = b['last'], px['mins']
    inwin = lambda k: any(a <= mins[last[k]] < z for a, z in cfg.windows)
    out, armed = [], None
    for k in range(s + 30, e):
        if not inwin(k):
            armed = None
            continue
        ref = lo[k - cfg.div_look:k].min()
        g = gap[k - 20:k].max()
        if lo[k] < ref and g > 0 and 0 < gap[k] <= cfg.mfail_gap * g and \
                (gap[k - 20:k + 1] > 0).all():
            armed = (k, lo[k])
            continue
        if armed:
            j, low = armed
            if lo[k] < low or gap[k] <= 0 or k - j > cfg.reclaim_bars:
                armed = None
                continue
            if gap[k] > gap[k - 1] and cl[k] > hi[k - 1]:
                top = hi[k - 30:k + 1].max()
                entry, stop = cl[k], low - TICK
                if (top - low) * NQ_PER_QQQ >= cfg.min_range and entry - stop <= cfg.max_stop * abs(entry):
                    out.append((int(last[k]), entry * side, stop * side, top * side, 'mfail', 4, False))
                armed = None
    return out


def _open_setups(mk, d, cfg, side):
    """His three opening patterns on 1m bars (RULES_CN 4, ledger T06-T20):
    A pre-open: 09:00-09:29, >= open_lows consecutive new lows each on lower volume, then a close above the last
      low bar's high -> enter at that close (6/1 "volume divergence before the open", 5/27 "four lows, falling volume");
    B open sweep: in 09:30-09:35 a bar undercuts the 09:00-09:29 low and closes as a bullish body -> enter at its
      close (6/22 "it was a sweep, I enter on the bullish body"; 6/3 opening longs);
    C post-open flush: 09:35-10:30, the session has dropped >= open_drop NQ points from its high since 09:25, a new
      low on lower volume than the previous low, then a close above that bar's high (6/3, 6/8, 5/27).
    Stops a tick under the lowest low of the pattern; `top` = the high the drop started from."""
    px = mk.px
    s, e = mk.starts[d], mk.ends[d]
    mins = px['mins']
    if side == 1:
        lo, hi, op, cl = px['l'], px['h'], px['o'], px['c']
    else:
        lo, hi, op, cl = -px['h'], -px['l'], -px['o'], -px['c']
    vol = px['v']
    m0 = mins[s:e]
    idx = lambda a, b: np.nonzero((m0 >= a) & (m0 < b))[0] + s
    out = []

    def emit(i, low, top, kind):
        entry = cl[i]
        stop = low - TICK
        if (top - low) * NQ_PER_QQQ < cfg.min_range or entry <= stop:
            return
        if (entry - stop) > cfg.max_stop * abs(entry):
            return
        out.append((int(i), entry * side, stop * side, top * side, kind, cfg.open_units, False))

    if 'A' in cfg.open_sets:
        bars = idx(540, 570)
        lows = []                       # (bar, low, volume) of successive new lows since 09:00
        for i in bars:
            if not lows or lo[i] < lows[-1][1]:
                if lows and vol[i] >= lows[-1][2]:
                    lows = []           # volume did not shrink: restart the count from this low
                lows.append((i, lo[i], vol[i]))
                continue
            if len(lows) >= cfg.open_lows and cl[i] > hi[lows[-1][0]]:
                top = hi[idx(510, 570)[0]:i + 1].max()
                emit(i, lows[-1][1], top, 'open_A')
                break
    if 'B' in cfg.open_sets:
        pre = idx(540, 570)
        if len(pre):
            ref = lo[pre].min()
            top = hi[pre].max()
            swept = None
            for i in idx(570, 575):
                if swept is None and lo[i] < ref:
                    swept = i
                if swept is not None and cl[i] > op[i] and cl[i] >= (hi[i] + lo[i]) / 2 and i - swept <= 3:
                    emit(i, lo[swept:i + 1].min(), top, 'open_B')
                    break
    if 'C' in cfg.open_sets:
        start = idx(565, 570)
        armed = None                    # (bar, low, high)
        for i in idx(575, 630):
            a0 = start[0] if len(start) else i
            H = hi[a0:i + 1].max()
            prev = lo[max(s, i - cfg.div_look):i - 2]
            if len(prev):
                j = max(s, i - cfg.div_look) + int(np.argmin(prev))
                if lo[i] < lo[j] and vol[i] < vol[j] and (H - lo[i]) * NQ_PER_QQQ >= cfg.open_drop:
                    armed = (i, lo[i], hi[i])
                    continue
            if armed and i - armed[0] <= cfg.reclaim_bars and cl[i] > armed[2] and lo[armed[0]:i + 1].min() >= armed[1]:
                emit(i, armed[1], H, 'open_C')
                armed = None
    return out


def _macd_setups(mk, d, cfg, side):
    b = mk.bars(cfg.tf)
    px = mk.px
    s, e = b['start'][d], b['end'][d]
    if side == 1:
        lo, hi, op = b['l'], b['h'], b['o']
        mac, rs = b['macd'], b['rsi']
    else:
        lo, hi, op = -b['h'], -b['l'], -b['o']
        mac, rs = -b['macd'], 100 - b['rsi']
    vol, last, mins = b['v'], b['last'], px['mins']
    p = cfg.piv

    def inwin(k):
        m = mins[last[k]]
        return any(a <= m < z for a, z in cfg.windows)

    lows, out, pend = [], [], None    # lows: (bar, price) of confirmed swing lows today
    for k in range(s + 2 * p, e):
        j = k - p                      # candidate swing low confirmed at the close of bar k
        if lo[j] <= lo[j - p:j].min() and lo[j] < lo[j + 1:k + 1].min():
            prev = [x for x in lows if j - x[0] <= cfg.pair_look]
            lows.append((j, lo[j]))
            if prev and inwin(k):
                j1, l1 = prev[-1]
                regular = lo[j] < l1 and mac[j] > mac[j1]
                hidden = cfg.hidden and lo[j] > l1 and mac[j] < mac[j1]
                top = hi[j1:j + 1].max()
                rng_pts = (top - lo[j]) * NQ_PER_QQQ
                if cfg.macd_drop > 0:      # only after the session fell macd_drop points from its high since 09:25
                    since = [x for x in range(s, k + 1) if mins[last[x]] >= 565]
                    if not since or (hi[since[0]:k + 1].max() - lo[j]) * NQ_PER_QQQ < cfg.macd_drop:
                        regular = hidden = False
                if (regular or hidden) and rng_pts >= cfg.min_range:
                    units = 1
                    if cfg.confirm_units:
                        units += (rs[j] > rs[j1]) if regular else (rs[j] < rs[j1])
                        units += rs[j1] < 30
                        units += vol[j] < vol[j1]
                    pend = (k, lo[j], top, units, 'macd' if regular else 'hidden')
        if pend is None or k == pend[0]:
            continue
        k0, low, top, units, kind = pend
        if k - k0 > cfg.expire or lo[k] < low:
            pend = None                # expired, or a lower low invalidates the swing
            continue
        level = low + cfg.fib_in * (top - low) + TICK
        if hi[k] >= level and inwin(k):
            pend = None
            fill = max(op[k], level)
            if fill > low + cfg.max_chase * (top - low):
                continue
            stop = low - TICK
            if not _in_zone(mk, d, cfg, side, low, fill, mins[last[k]], hi, lo, k):
                continue
            # the 1m bar inside which the order filled is not known for tf > 1: use the tf bar's last minute
            out.append((int(last[k]), fill * side, stop * side, top * side, kind, units, True))
    return out


def _vol_setups(mk, d, cfg, side):
    px = mk.px
    s, e = mk.starts[d], mk.ends[d]
    mins = px['mins']
    if side == 1:
        lo, hi, vol, cl = px['l'], px['h'], px['v'], px['c']
    else:
        lo, hi, vol, cl = -px['h'], -px['l'], px['v'], -px['c']
    inwin = np.zeros(e - s, bool)
    for a, b in cfg.windows:
        inwin |= (mins[s:e] >= a) & (mins[s:e] < b)
    out, armed = [], []
    for i in np.nonzero(inwin)[0] + s:
        if i < s + 21:
            continue
        a0 = max(s, i - cfg.div_look)
        seg = lo[a0:i - 2]
        if len(seg):
            j = a0 + int(np.argmin(seg))
            if lo[i] < lo[j] and lo[i] <= lo[i - 2:i].min() and vol[i] < vol[j]:
                armed.append((i, lo[i], hi[i], 'div'))
        mv = vol[i - 20:i].mean()
        if mv > 0 and vol[i] >= cfg.whip_mult * mv and lo[i] <= lo[max(s, i - 10):i].min() \
                and cl[i] < (lo[i] + hi[i]) / 2:
            armed.append((i, lo[i], hi[i], 'whip'))
        keep, fired = [], None
        for (j, sl, sh, kind) in armed:
            if i - j > cfg.reclaim_bars:
                continue
            low_since = lo[j:i + 1].min()
            if kind == 'whip' and low_since < sl:
                continue
            if i > j and cl[i] > sh and fired is None:
                fired = (j, low_since, kind)
            else:
                keep.append((j, sl, sh, kind))
        armed = keep
        if fired is None:
            continue
        j, low_since, kind = fired
        armed = []
        entry = cl[i]
        stop = low_since - cfg.stop_buf * abs(entry)
        if entry - stop < cfg.min_stop * abs(entry):
            stop = entry - cfg.min_stop * abs(entry)
        if entry - stop > cfg.max_stop * abs(entry):
            continue
        if not _in_zone(mk, d, cfg, side, low_since, entry, mins[i], hi, lo, i):
            continue
        dh = hi[max(s, i - cfg.drop_look):i + 1].max()
        out.append((int(i), entry * side, stop * side, dh * side, kind, 1, False))
    return out


@dataclass
class Trade:
    date: str
    side: int
    t_in: int
    t_out: int
    entry: float
    exit: float
    stop0: float
    units: int
    added: int
    pts: float          # NQ points per initial unit
    pnl: float          # USD net of cost
    kind: str
    reason: str
    target: float = 0.0
    conf: int = 1


def manage(px, i, side, entry, stop, target, units, cfg, e, intrabar=False, part=None):
    """Run one position entered in bar i. Returns (exit bar, exit price, added units, avg cost, reason).
    part = (fraction, price): that fraction is closed at `price` first and the stop goes to cost + be_plus; the
    returned exit price is then the size-weighted average of both exits (his 80% / 20% split, 0UwzsfZxHr0 11:23)."""
    o, h, l, c, mins = px['o'], px['h'], px['l'], px['c'], px['mins']
    if intrabar and side * (l[i] if side == 1 else h[i]) <= side * stop:
        return i, stop, 0, entry, 'stop'
    R = abs(entry - stop)
    add_px = entry + side * cfg.add_pts / NQ_PER_QQQ if cfg.add_pts > 0 else None
    added, avg, cur_stop = 0, entry, stop
    be_done = False
    pf, ppx, pdone = (part[0], part[1], False) if part else (0.0, None, True)
    mix = lambda fill: pf * ppx + (1 - pf) * fill if part and pdone else fill
    last = min(e - 1, i + cfg.max_hold)
    for k in range(i + 1, e):
        if k > last:
            return k - 1, mix(c[k - 1]), added, avg, 'time'
        if mins[k] >= 959:
            return k, mix(c[k]), added, avg, 'close'
        if side * (l[k] if side == 1 else h[k]) <= side * cur_stop:
            fill = o[k] if side * o[k] <= side * cur_stop else cur_stop
            return k, mix(fill), added, avg, 'stop' if not (part and pdone) else 'runner_stop'
        if not pdone and side * (h[k] if side == 1 else l[k]) >= side * ppx:
            pdone = True       # partial taken; the runner's stop moves to cost from the next bar
            if side * (h[k] if side == 1 else l[k]) < side * target:
                cur_stop = max(cur_stop * side, (entry + side * cfg.be_plus / NQ_PER_QQQ) * side) * side
                be_done = True
                continue
        if side * (h[k] if side == 1 else l[k]) >= side * target:
            fill = o[k] if side * o[k] >= side * target else target
            return k, mix(fill), added, avg, 'target'
        best = h[k] if side == 1 else l[k]
        new_stop = cur_stop
        if add_px is not None and not added and side * best >= side * add_px:
            added = units
            avg = (entry + add_px) / 2
            new_stop = avg + side * cfg.be_plus / NQ_PER_QQQ
            be_done = True
        if cfg.be_at > 0 and not be_done and side * (best - entry) >= cfg.be_at * R:
            new_stop = entry + side * cfg.be_plus / NQ_PER_QQQ
            be_done = True
        if side * new_stop > side * cur_stop:
            cur_stop = new_stop
    return e - 1, c[e - 1], added, avg, 'eod'


def target_of(cfg, side, entry, stop, top, R):
    if cfg.tgt == 'r':
        return entry + side * cfg.tgt_r * R
    frac = {'fib38': .382, 'fib50': .5, 'fib66': 2 / 3}[cfg.tgt]
    low = stop + side * TICK
    u = side * (low + side * frac * abs(top - low)) - cfg.shave / NQ_PER_QQQ
    u = max(u, side * entry + 0.25 / NQ_PER_QQQ)     # at least a tick of profit
    return side * u


def run(mk, cfg, d_lo, d_hi, start=START, entries=None):
    """Simulate sessions d_lo..d_hi (inclusive) from `start` equity. entries: optional dict day ->
    [(bar, entry, stop, top, kind, units, intrabar, side)] replacing our own setups (ledger replay / placebo)."""
    px = mk.px
    eq = start
    trades = []
    for d in range(d_lo, d_hi + 1):
        if not mk.ok[d]:
            continue
        e = mk.ends[d]
        if entries is None:
            cand = [x + (1,) for x in setups(mk, d, cfg, 1)]
            if cfg.shorts:
                cand += [x + (-1,) for x in setups(mk, d, cfg, -1)]
            cand.sort(key=lambda x: x[0])
        else:
            cand = entries.get(d, [])
        eq_day, n, losses, free_at = eq, 0, 0, -1
        for (i, entry, stop, top, kind, conf, intrabar, side) in cand:
            if i <= free_at or n >= cfg.max_trades or losses >= cfg.max_losses:
                continue
            if cfg.day_target > 0 and eq - eq_day >= cfg.day_target * eq_day:
                break
            pat_stop = stop       # targets are measured from the pattern low even when the stop is tightened
            if cfg.stop_pts > 0 and not kind.startswith('fixed') and abs(entry - stop) * NQ_PER_QQQ > cfg.stop_pts:
                stop = entry - side * cfg.stop_pts / NQ_PER_QQQ     # his tight point stop instead of the pattern low
            R = abs(entry - stop)
            if R <= 0:
                continue
            # external entries of kind 'fixed*' carry their target in the `top` slot
            target = top if kind.startswith('fixed') else target_of(cfg, side, entry, pat_stop, top, R)
            part = None
            if cfg.leg_bars > 0 and not kind.startswith('fixed'):
                # the far target is measured on the bigger leg: from the pattern low to the highest high of the last
                # leg_bars minutes ("from the session high to my entry low", HvUfJUhArX0 9:20)
                low = pat_stop + side * TICK
                a0 = max(mk.starts[d], i - cfg.leg_bars)
                big = px['h'][a0:i + 1].max() if side == 1 else px['l'][a0:i + 1].min()
                far = low + side * cfg.leg_frac * abs(big - low) - side * cfg.shave / NQ_PER_QQQ
                if side * far > side * target:
                    if cfg.part_frac > 0:
                        part = (cfg.part_frac, target)
                    target = far
            nq = entry * NQ_PER_QQQ
            lev = cfg.lev_hi if cfg.lev_hi > 0 and eq < cfg.lev_until * start else cfg.lev
            full = int(lev * eq / (nq * MNQ_USD))
            units = max(1, int(full * conf / 4)) if cfg.confirm_units and full >= 1 else full
            if cfg.risk > 0:
                units = min(units, int(cfg.risk * eq * (conf / 4 if cfg.confirm_units else 1)
                                       / (R * NQ_PER_QQQ * MNQ_USD + cfg.cost_pts * MNQ_USD)))
            if units < 1:
                continue
            k, fill, added, avg, why = manage(px, i, side, entry, stop, target, units, cfg, e, intrabar, part)
            pts_first = side * (fill - entry) * NQ_PER_QQQ
            pts_add = side * (fill - (2 * avg - entry)) * NQ_PER_QQQ if added else 0.0
            pnl = MNQ_USD * (units * pts_first + added * pts_add) - cfg.cost_pts * MNQ_USD * (units + added)
            eq = max(eq + pnl, 0.0)     # an account cannot lose more than it holds (ruin = -100%)
            trades.append(Trade(px['dates'][d], side, int(i), int(k), entry, fill, stop, units, added,
                                pts_first, pnl, kind, why, target, conf))
            n += 1
            losses += pnl < 0
            free_at = k
            if eq < 100:
                return eq, trades
    return eq, trades


QUARTERS = {  # his official quarterly futures day-trading results (worldcupchampionships.com standings, 2026-10-28)
    '2025Q1': ('2025-01-01', '2025-03-31', 291.0),
    '2025Q2': ('2025-04-01', '2025-06-30', 712.1),
    '2025Q3': ('2025-07-01', '2025-09-30', 800.6),
    '2025Q4': ('2025-10-01', '2025-12-31', 930.7),
    '2026Q1': ('2026-01-01', '2026-03-31', 585.4),
    '2026Q2': ('2026-04-01', '2026-06-30', 2222.6),
    '2026Q3': ('2026-07-01', '2026-09-30', 1350.8),   # "final pending audit"
}
SELECT = ('2025Q1', '2025Q2', '2025Q3', '2025Q4')
VALIDATE = ('2026Q1', '2026Q2', '2026Q3')


def day_range(mk, lo, hi):
    dates = mk.px['dates']
    a = int(np.searchsorted(dates, lo))
    b = int(np.searchsorted(dates, hi, side='right')) - 1
    return a, b


def quarter(mk, cfg, q, entries=None):
    lo, hi, _ = QUARTERS[q]
    a, b = day_range(mk, lo, hi)
    eq, tr = run(mk, cfg, a, b, entries=entries)
    return 100 * (eq / START - 1), tr


def stats(trades, ndays):
    if not trades:
        return dict(n=0)
    pnl = np.array([t.pnl for t in trades])
    pts = np.array([t.pts for t in trades])
    hold = np.array([t.t_out - t.t_in for t in trades])
    days = len({t.date for t in trades})
    win, loss = pts[pnl > 0], pts[pnl <= 0]
    return dict(n=len(trades), per_active_day=round(len(trades) / days, 2), active_days=days,
                active_share=round(days / max(ndays, 1), 2), win=round(float((pnl > 0).mean()), 3),
                avg_win_pts=round(float(win.mean()), 1) if len(win) else 0.0,
                avg_loss_pts=round(float(loss.mean()), 1) if len(loss) else 0.0,
                pts_total=round(float(pts.sum()), 1), hold_med=float(np.median(hold)),
                long_share=round(float(np.mean([t.side == 1 for t in trades])), 3),
                added_share=round(float(np.mean([t.added > 0 for t in trades])), 3))
