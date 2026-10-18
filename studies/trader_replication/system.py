"""Daily-bar portfolio of a replicated trader: close-confirmed entries, fixed-risk sizing, partials, EMA trail,
both sides, and a placebo that swaps every entry for a random name from the same list on the same day.

Entries are tuples (priority, column, side, fill, stop, kind[, day_exit[, size_risk[, max_position]]]) placed on
day d and filled at `fill` on day d (normally that day's close); management starts on day d + 1.  side is +1 (long)
or -1 (short).  An intraday entry that was already stopped later the same day carries its exit price as day_exit;
size_risk (a fraction of the fill) sizes the trade when it is wider than the stop distance (gap risk), and
max_position caps that trade below rules.max_position (small caps).  The placebo keeps both overrides.
Same-day ordering is conservative: when a day reaches both the stop and a partial level, the stop comes first
unless the open is already beyond the partial level.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from collections import deque

import numpy as np


@dataclass(frozen=True)
class Rules:
    risk: float = .005              # equity fraction lost at the initial stop
    max_position: float = .30       # of equity, per name
    max_gross: float = 2.0          # long + short market value / equity
    trims: tuple = (3, 5)           # R multiples where trim_frac of the original size is taken off
    trim_frac: float = .15
    trail: str = 'e9'               # EMA name for the close trail ('' = none); armed after a close on the right side
    arm_trail_on_entry: bool = False  # include the completed entry close when arming the EMA trail
    stop_ema_buffer: float = -1.0   # >= 0: after arming, the stop also trails the EMA minus/plus this fraction
    max_days: int = 0               # > 0: exit at the close after this many days
    nft_days: int = 0               # > 0: exit at that day's close if the trade is still on the wrong side of its fill
    feedback: int = 0               # > 0: risk_low per trade while the last `feedback` closed trades sum to < 0 R
    feedback_opened: bool = False   # use latest opened positions, marked at the previous session close
    management_by_kind: dict = field(default_factory=dict)  # entry kind -> position management overrides
    risk_low: float = .0025
    risk_high: float = 0.0          # > 0: risk per trade while the last `feedback` closed trades sum to > 0 R
    short_trims: tuple | None = None  # shorts' partial levels (None = same as longs)
    short_max_days: int = 0           # shorts' holding limit (0 = same as longs)
    max_open: int = 0               # > 0: no new trade while this many are open
    max_new_long: int = 0           # > 0: count successful new long positions per trading session
    exit_signal: str = ''           # name of a boolean (days x codes) array in `ema`: longs exit at that close
    trail_after_trim: str = ''      # EMA name the close trail switches to after the first partial ('' = keep)
    breakeven_r: float = 0.0        # > 0: once the day's best price reaches this R multiple, the stop moves to the fill
    trim_signal: str = ''           # boolean (days x codes) array in `ema`: longs sell trim_frac of the original size
                                    # at that close (at most once a day)
    trim_signal_frac: float = 0.0   # fraction for signal trims (0 = trim_frac)
    add_r: float = 0.0              # > 0: once a long closes at least this R above its fill, buy add_frac of the original
    add_frac: float = 1.0           # size at that close (once) and move the whole stop to the original fill
    add_levels: tuple = ()          # several R levels instead of add_r, one add at each; an add the position or gross
                                    # caps leave no room for still uses up its level (no breakeven then)
    risk_scale: str = ''            # 1-D (days) array in `ema`: risk per new trade is multiplied by its value that day
    trail_alt: str = ''             # EMA name the close trail uses instead while the conditions below hold
    trail_alt_dd: float = 0.0       # > 0: ... while equity (as of the previous close) is this far below its peak
    trail_alt_days: str = ''        # 1-D bool array in `ema`: ... on these days (both set: both must hold)
    trim_day: int = 0               # > 0: at the close this many sessions after entry a long sells trim_day_frac of
    trim_day_frac: float = 0.0      # its original size, once (only when that close is above the fill if
    trim_day_profit: bool = True    # trim_day_profit) ...
    trim_day_breakeven: bool = False  # ... and then has its stop moved to the fill
    add_signal: str = ''            # boolean (days x codes) array in `ema`: a held long buys add_signal_frac (0 =
    add_signal_frac: float = 0.0    # add_frac) of its original size at that close, at most add_signal_max times
    add_signal_max: int = 0         # (0 = no limit), not on its entry day; then the stop is kept ('keep'), moved to
    add_signal_stop: str = 'keep'   # the original fill ('fill') or raised to the add day's low ('low')
    month_loss_cap: float = 0.0     # > 0: no new trades for the rest of a calendar month once equity (as of the previous
    month_cap_ladder: tuple = ()    # close) is this far below the month's opening equity; after 1, 2, ... losing
                                    # months in a row the cap is month_cap_ladder[0], [1], ... (the last one repeats)
    month_cap_basis: str = 'equity'  # 'opened': measure the month by the trades opened in it (realized plus marked at
                                    # the previous close, as a fraction of the month's opening equity) instead
    buy_cost: float = .0005
    sell_cost: float = .0005
    margin_rate: float = .07        # yearly, on long value above equity


@dataclass
class Pos:
    j: int
    side: int
    kind: str
    d0: int
    fill: float
    stop: float
    stop0: float
    size0: float                    # shares (positive)
    size: float
    trims: int = 0
    adds: int = 0
    sig_adds: int = 0
    day_trimmed: bool = False
    armed: bool = False
    cash: float = 0.0               # signed cash flow of the trade so far
    exits: list = field(default_factory=list)
    invested: float = 0.0
    executions: list = field(default_factory=list)
    management: Rules | None = None


def simulate(px, ema, rules, entries, start, end, placebo=None, pool=None, audit=False, entry_audit=None):
    """Run between ISO dates; return (equity array, dates, trades).

    px: dict of (days x codes) 'open', 'high', 'low', 'close' and 'dates', 'codes';  ema: dict name -> array;
    entries: list over days of entry tuples;  placebo: numpy Generator -> each real entry becomes a random
    pool[d] name of the same side, filled at its close with the same stop distance in percent.
    Optional px['session'] numbers trading days and px['daily_close'] marks their final bars. Stops/trims
    run every bar; daily management and financing retain their daily clocks. px['mark'] may contain
    forward-filled, already observed closes for valuation only; never use it as tradable OHLC.
    entry_audit optionally maps requested (code, ISO day) keys to lists receiving attempt outcomes;
    it records the first rejecting constraint without changing execution or logging other dates.
    """
    o, h, l, c, dates = px['open'], px['high'], px['low'], px['close'], px['dates']
    session = px.get('session', np.arange(len(dates)))
    daily_close = px.get('daily_close')
    mark = px.get('mark')
    d0, d1 = int(np.searchsorted(dates, start)), int(np.searchsorted(dates, end, side='right'))
    trail = ema.get(rules.trail) if rules.trail else None
    sig_exit = ema[rules.exit_signal] if rules.exit_signal else None
    trail2 = ema.get(rules.trail_after_trim) if rules.trail_after_trim else None
    sig_trim = ema[rules.trim_signal] if rules.trim_signal else None
    scale = ema[rules.risk_scale] if rules.risk_scale else None
    trail3 = ema[rules.trail_alt] if rules.trail_alt else None
    alt_days = ema[rules.trail_alt_days] if rules.trail_alt_days else None
    sig_add = ema[rules.add_signal] if rules.add_signal else None
    if rules.add_signal_stop not in ('keep', 'fill', 'low'):
        raise ValueError('add_signal_stop')
    peak = 1.0
    cash, pos, trades, curve = 1.0, {}, [], []
    month_trades = []
    recent_positions = deque(maxlen=rules.feedback or 1)
    opened_feedback = None
    allowed_management = {'max_position', 'trims', 'trim_frac', 'trail', 'add_r', 'add_levels'}
    for overrides in rules.management_by_kind.values():
        if set(overrides) - allowed_management:
            raise ValueError('unsupported position management override')
    management = {kind: replace(rules, **overrides) for kind, overrides in rules.management_by_kind.items()}

    def last(j, d):
        if mark is not None:
            return mark[d, j]
        k = d
        while k > 0 and np.isnan(c[k, j]):
            k -= 1
        return c[k, j]

    def value(d):
        return sum(q.side * q.size * last(q.j, d) for q in pos.values())

    def gross(d):
        return sum(q.size * last(q.j, d) for q in pos.values())

    def close_part(q, size, price, d, why):
        nonlocal cash
        size = min(size, q.size)
        if size <= 0:
            return
        if q.side > 0:
            flow = size * price * (1 - rules.sell_cost)
        else:
            flow = -size * price * (1 + rules.buy_cost)
        cash += flow
        q.cash += flow
        q.size -= size
        q.exits.append((d, price, size, why))
        if audit:
            q.executions.append(dict(time=str(dates[d]), action=why, price=float(price), shares=float(size)))
        if q.size <= 1e-12 * q.size0:
            pos.pop(q.j, None)
            risk = q.size0 * abs(q.fill - q.stop0)
            gross0 = q.size0 * q.fill
            trades.append(dict(code=str(px['codes'][q.j]), side=q.side, kind=q.kind, entry=str(dates[q.d0]),
                               exit=str(dates[d]), days=int(session[d] - session[q.d0]), fill=q.fill, stop=q.stop0,
                               risk_pct=abs(q.fill - q.stop0) / q.fill, pnl=q.cash,
                               r=q.cash / risk if risk > 0 else 0.0, ret=q.cash / gross0,
                               ret_invested=q.cash / q.invested, why=why, add_tries=q.adds))
            if audit:
                trades[-1]['executions'] = q.executions

    def record_attempt(j, d, reason, equity, fill, stop, proposed_value=None):
        if entry_audit is None:
            return
        key=(str(px['codes'][j]),str(dates[d])[:10])
        if key in entry_audit:
            entry_audit[key].append(dict(time=str(dates[d]),reason=reason,fill=float(fill),stop=float(stop),
                                         equity=float(equity),gross=float(gross(d)),
                                         successful_longs_before=new_longs,proposed_value=proposed_value))

    def open_pos(j, side, fill, stop, kind, d, equity, size_risk=None, max_pos=None):
        nonlocal cash
        if j in pos:
            record_attempt(j,d,'already_held',equity,fill,stop)
            return
        if not np.isfinite(fill) or fill <= 0:
            record_attempt(j,d,'invalid_fill',equity,fill,stop)
            return
        if rules.max_open and len(pos) >= rules.max_open:
            record_attempt(j,d,'max_open',equity,fill,stop)
            return
        risk = abs(fill - stop) / fill
        if not (0 < risk < 1) or (stop - fill) * side >= 0:
            record_attempt(j,d,'invalid_stop',equity,fill,stop)
            return
        frac = rules.risk
        recent = opened_feedback if rules.feedback_opened else (
            sum(t['r'] for t in trades[-rules.feedback:])
            if rules.feedback and len(trades) >= rules.feedback else None)
        if recent is not None:
            if recent < 0:
                frac = rules.risk_low
            elif recent > 0 and rules.risk_high > 0:
                frac = rules.risk_high
        if scale is not None and np.isfinite(scale[d]):
            frac *= scale[d]
        policy = management.get(kind, rules)
        cap = policy.max_position if max_pos is None else min(policy.max_position, max_pos)
        width = risk if size_risk is None else max(risk, size_risk)
        val = min(frac * equity / width, cap * equity, rules.max_gross * equity - gross(d))
        if val <= .001 * equity:
            record_attempt(j,d,'no_capacity',equity,fill,stop,float(val))
            return
        record_attempt(j,d,'opened',equity,fill,stop,float(val))
        size = val / fill
        flow = -val * (1 + rules.buy_cost) if side > 0 else val * (1 - rules.sell_cost)
        cash += flow
        pos[j] = Pos(j, side, kind, d, fill, stop, stop, size, size, cash=flow, invested=val, management=policy)
        month_trades.append(pos[j])
        if rules.feedback_opened:
            recent_positions.append(pos[j])
        initial_trail = trail3 if alt else ema.get(policy.trail)
        if rules.arm_trail_on_entry and initial_trail is not None and np.isfinite(initial_trail[d,j]):
            pos[j].armed = (fill-initial_trail[d,j])*side > 0
        if audit:
            pos[j].executions.append(dict(time=str(dates[d]), action='entry', price=float(fill), shares=float(size)))
        return True

    def add_pos(q, price, d, frac=None, signal=False):
        nonlocal cash
        eq = cash + value(d)
        val = min((rules.add_frac if frac is None else frac) * q.size0 * price,
                  q.management.max_position * eq - q.size * price, rules.max_gross * eq - gross(d))
        if signal:
            q.sig_adds += 1
        else:
            q.adds += 1
        if val <= .001 * eq:
            return
        flow = -val * (1 + rules.buy_cost)
        cash += flow
        q.cash += flow
        q.size += val / price
        q.invested += val
        if audit:
            q.executions.append(dict(time=str(dates[d]), action='add', price=float(price), shares=float(val / price)))
        if not signal:
            q.stop = max(q.stop, q.fill)
        elif rules.add_signal_stop == 'fill':
            q.stop = max(q.stop, q.fill)
        elif rules.add_signal_stop == 'low' and np.isfinite(l[d, q.j]):
            q.stop = max(q.stop, l[d, q.j])
        return True

    month_open, month_losses, month_cap, month_blocked = 1.0, 0, rules.month_loss_cap, False
    if rules.month_cap_basis not in ('equity', 'opened'):
        raise ValueError('month_cap_basis')

    def month_pnl(d):
        """Profit of the trades opened this month, marked at the previous close."""
        return sum(q.cash + (q.side * q.size * last(q.j, d - 1) if q.size > 0 else 0.0) for q in month_trades)

    for d in range(d0, d1):
        equity = cash + value(d - 1) if d > d0 else 1.0
        if rules.month_loss_cap > 0:
            if d > d0 and str(dates[d])[:7] != str(dates[d - 1])[:7]:     # a new month opens at the previous close
                lost = month_pnl(d) < 0 if rules.month_cap_basis == 'opened' else equity < month_open
                month_losses = month_losses + 1 if lost else 0
                month_trades.clear()
                ladder = rules.month_cap_ladder
                month_cap = ladder[min(month_losses, len(ladder)) - 1] if month_losses and ladder \
                    else rules.month_loss_cap
                month_open, month_blocked = equity, False
            now = month_open + month_pnl(d) if rules.month_cap_basis == 'opened' else equity
            month_blocked = month_blocked or now <= month_open * (1 - month_cap)
        peak = max(peak, equity)
        alt = trail3 is not None and (rules.trail_alt_dd > 0 or alt_days is not None) \
            and (rules.trail_alt_dd <= 0 or equity < peak * (1 - rules.trail_alt_dd)) \
            and (alt_days is None or bool(alt_days[d]))
        if d == d0 or session[d] != session[d - 1]:
            new_longs = 0
            if rules.feedback_opened and rules.feedback and len(recent_positions) >= rules.feedback:
                opened_feedback = sum(
                    (q.cash + (q.side * q.size * last(q.j, d - 1) if q.size > 0 else 0))
                    / (q.size0 * abs(q.fill - q.stop0)) for q in recent_positions)
                if abs(opened_feedback) < 1e-10:
                    opened_feedback = 0.0
            longs = sum(q.size * last(q.j, d - 1) for q in pos.values() if q.side > 0)
            cash -= rules.margin_rate / 252 * max(0.0, longs - equity)
        for q in list(pos.values()):
            j, s = q.j, q.side
            policy = q.management
            if np.isnan(o[d, j]):
                continue
            R = abs(q.fill - q.stop0)
            if (o[d, j] - q.stop) * s <= 0:                       # gap through the stop
                close_part(q, q.size, o[d, j], d, 'gap_stop')
                continue
            trims = policy.trims if s > 0 or rules.short_trims is None else rules.short_trims
            levels = [q.fill + s * k * R for k in trims[q.trims:]]
            worst, best = (l[d, j], h[d, j]) if s > 0 else (h[d, j], l[d, j])
            if (worst - q.stop) * s <= 0:
                while levels and (o[d, j] - levels[0]) * s >= 0:
                    close_part(q, policy.trim_frac * q.size0, o[d, j], d, 'trim')
                    q.trims += 1
                    levels.pop(0)
                if j in pos:
                    close_part(q, q.size, q.stop, d, 'stop')
                continue
            while levels and (best - levels[0]) * s >= 0 and j in pos:
                px_ = max(o[d, j], levels[0]) if s > 0 else min(o[d, j], levels[0])
                close_part(q, policy.trim_frac * q.size0, px_, d, 'trim')
                q.trims += 1
                levels.pop(0)
            if j not in pos:
                continue
            if rules.breakeven_r and (best - (q.fill + s * rules.breakeven_r * R)) * s >= 0:
                q.stop = max(q.stop, q.fill) if s > 0 else min(q.stop, q.fill)
            if daily_close is not None and not daily_close[d]:
                continue
            tr_ = trail3 if alt else (trail2 if trail2 is not None and q.trims else ema.get(policy.trail))
            if tr_ is not None and np.isfinite(tr_[d, j]):
                if (c[d, j] - tr_[d, j]) * s > 0:
                    q.armed = True
                elif q.armed:
                    close_part(q, q.size, c[d, j], d, 'trail')
                    continue
                if q.armed and rules.stop_ema_buffer >= 0:
                    level = tr_[d, j] * (1 - s * rules.stop_ema_buffer)
                    q.stop = max(q.stop, level) if s > 0 else min(q.stop, level)
            if sig_trim is not None and s > 0 and sig_trim[d, j]:
                close_part(q, (rules.trim_signal_frac or rules.trim_frac) * q.size0, c[d, j], d, 'signal_trim')
                if j not in pos:
                    continue
            if rules.trim_day and s > 0 and not q.day_trimmed and session[d] - session[q.d0] == rules.trim_day:
                q.day_trimmed = True
                if not rules.trim_day_profit or c[d, j] > q.fill:
                    close_part(q, rules.trim_day_frac * q.size0, c[d, j], d, 'day_trim')
                    if j not in pos:
                        continue
                    if rules.trim_day_breakeven:
                        q.stop = max(q.stop, q.fill)
            levels_add = policy.add_levels or ((policy.add_r,) if policy.add_r else ())
            if s > 0 and q.adds < len(levels_add) and c[d, j] >= q.fill + levels_add[q.adds] * R:
                add_pos(q, c[d, j], d)
            if sig_add is not None and s > 0 and sig_add[d, j] and session[d] > session[q.d0] \
                    and (not rules.add_signal_max or q.sig_adds < rules.add_signal_max):
                add_pos(q, c[d, j], d, rules.add_signal_frac or rules.add_frac, signal=True)
            if sig_exit is not None and s > 0 and sig_exit[d, j]:
                close_part(q, q.size, c[d, j], d, 'signal')
                continue
            if rules.nft_days and session[d] - session[q.d0] == rules.nft_days and (c[d, j] - q.fill) * s < 0:
                close_part(q, q.size, c[d, j], d, 'no_follow')
                continue
            hold = rules.max_days if s > 0 else (rules.short_max_days or rules.max_days)
            if hold and session[d] - session[q.d0] >= hold:
                close_part(q, q.size, c[d, j], d, 'time')
        eq_now = cash + value(d)
        todays = entries[d] if d < len(entries) else []
        if placebo is not None:
            swapped = []
            cand = np.flatnonzero(pool[d] & np.isfinite(c[d]))
            for e in todays:
                pr, j, side, fill, stop, kind = e[:6]
                if not len(cand):
                    continue
                k = int(placebo.choice(cand))
                pct = abs(fill - stop) / fill
                kind_ = kind if kind in management else 'placebo'
                swapped.append((pr, k, side, c[d, k], c[d, k] * (1 - side * pct), kind_, None) + tuple(e[7:9]))
            todays = swapped
        for e in sorted(todays, key=lambda x: x[0]):
            pr, j, side, fill, stop, kind = e[:6]
            if month_blocked:
                record_attempt(j,d,'month_blocked',eq_now,fill,stop)
                continue
            if side > 0 and rules.max_new_long and new_longs >= rules.max_new_long:
                record_attempt(j,d,'daily_success_cap',eq_now,fill,stop)
                continue
            had = j in pos
            opened = open_pos(j, side, fill, stop, kind, d, eq_now, e[7] if len(e) > 7 else None,
                              e[8] if len(e) > 8 else None)
            if opened and side > 0:
                new_longs += 1
            if len(e) > 6 and e[6] is not None and j in pos and not had:     # intraday entry stopped the same day
                close_part(pos[j], pos[j].size, e[6], d, 'stop_day0')
        curve.append(cash + value(d))
    for q in list(pos.values()):                                    # mark open trades at the last close
        close_part(q, q.size, last(q.j, d1 - 1), d1 - 1, 'end')
    return np.array(curve), dates[d0:d1], trades


def stats(curve, dates, trades):
    curve = np.asarray(curve)
    if not len(curve):
        return {}
    years = max(len(curve) / 252, 1e-9)
    peak = np.maximum.accumulate(curve)
    r = np.array([t['r'] for t in trades]) if trades else np.zeros(0)
    ret = np.array([t['ret'] for t in trades]) if trades else np.zeros(0)
    win = ret > 0
    by_year = {}
    for y in sorted({str(d)[:4] for d in dates}):
        idx = np.flatnonzero(np.char.startswith(dates.astype(str), y))
        base = curve[idx[0] - 1] if idx[0] > 0 else 1.0
        by_year[y] = float(curve[idx[-1]] / base - 1)
    return dict(total=float(curve[-1] - 1), cagr=float(curve[-1] ** (1 / years) - 1),
                maxdd=float(np.max(1 - curve / peak)), trades=len(trades), per_year=len(trades) / years,
                win=float(win.mean()) if len(ret) else float('nan'),
                avg_win=float(ret[win].mean()) if win.any() else float('nan'),
                avg_loss=float(ret[~win].mean()) if (~win).any() else float('nan'),
                exp_r=float(r.mean()) if len(r) else float('nan'),
                days_win=float(np.mean([t['days'] for t in trades if t['ret'] > 0])) if win.any() else float('nan'),
                days_loss=float(np.mean([t['days'] for t in trades if t['ret'] <= 0])) if (~win).any() else float('nan'),
                by_year=by_year)


def placebo_rank(px, ema, rules, entries, start, end, pool, draws=100, seed=1):
    """Real total return vs the same entry stream with random names from `pool` on the same days."""
    real = simulate(px, ema, rules, entries, start, end)[0]
    rng = np.random.default_rng(seed)
    pl = np.array([simulate(px, ema, rules, entries, start, end, placebo=rng, pool=pool)[0][-1] - 1
                   for _ in range(draws)])
    tot = float(real[-1] - 1)
    return dict(real=tot, median=float(np.median(pl)), p90=float(np.percentile(pl, 90)),
                rank=float((pl < tot).mean()))
