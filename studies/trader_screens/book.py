"""A daily-bar account for a draft screen: what the trader would actually have bought, sold and held.

Each day the signals of the day are ranked (strongest first) and at most `max_new` are bought, while there is
room under `max_open` positions and `gross` exposure; size = equity x risk / (fill - stop), capped at
`max_position`.  A position is managed from the next day: a gap below the stop exits at the open, a touch of the
stop exits at the stop, then (at the close) an optional partial sale on day `partial_day` when in profit, and an
exit on a close below the trail line.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class BookRules:
    risk: float = .005              # equity fraction lost at the initial stop
    max_position: float = .30       # per name, of equity
    gross: float = 1.0              # total long value / equity
    max_new: int = 2                # new positions per day
    max_open: int = 8
    trail: str = ''                 # Feat key of the close trail line ('sma10', 'ema20', ...); '' = none
    partial_day: int = 0            # > 0: on this day after entry, at the close, sell partial_frac if in profit
    partial_frac: float = 0.0
    gate: str = ''                  # 'ema20' / 'ema50': no new positions while the pool index closes below it
    gate_mode: str = 'block'        # 'block' or 'half' (half risk while below)
    stop_min: float = .01           # the stop is at least this far below the fill (researcher; a 0.2% stop is noise)


@dataclass
class Pos:
    j: int
    d: int
    fill: float
    stop: float
    size: float
    setup: str
    cash: float
    partial: bool = False
    invested: float = 0.0


COSTS = {'us': (.0005, .0005), 'hk': (.0016, .0016), 'cn': (.00076, .00126)}


def replay(o, h, l, c, trail, entries, rules, d0, costs=(.0005, .0005), gate_ok=None):
    """entries[d] = list of (priority, column, fill, stop, setup) for day d (lower priority first).
    Returns dict(curve, buys, sells, open, trades, skipped) with per-day event lists."""
    T = len(c)
    buy_cost, sell_cost = costs
    cash, pos, trades = 1.0, {}, []
    curve = np.full(T, np.nan)
    buys, sells = [[] for _ in range(T)], [[] for _ in range(T)]
    skipped = np.zeros(T, int)

    def mark(d):
        return sum(p.size * (c[d, p.j] if np.isfinite(c[d, p.j]) else p.fill) for p in pos.values())

    def close(p, size, price, d, why):
        nonlocal cash
        size = min(size, p.size)
        flow = size * price * (1 - sell_cost)
        cash += flow
        p.cash += flow
        p.size -= size
        sells[d].append(dict(j=p.j, setup=p.setup, why=why, price=float(price), entry_day=p.d, fill=p.fill,
                             ret=float(price / p.fill - 1), full=p.size <= 1e-12))
        if p.size <= 1e-12:
            del pos[p.j]
            trades.append(dict(j=p.j, d0=p.d, d1=d, setup=p.setup, fill=p.fill, ret=float(p.cash / p.invested)
                               if p.invested else 0.0, why=why))

    equity = 1.0
    for d in range(d0, T):
        for p in list(pos.values()):
            j = p.j
            if not np.isfinite(o[d, j]):
                continue
            if o[d, j] <= p.stop:
                close(p, p.size, o[d, j], d, '跳空跌破止损')
                continue
            if l[d, j] <= p.stop:
                close(p, p.size, p.stop, d, '跌破止损')
                continue
            if rules.partial_day and not p.partial and d - p.d == rules.partial_day and c[d, j] > p.fill:
                close(p, rules.partial_frac * p.size, c[d, j], d, f'第 {rules.partial_day} 天分批')
                p.partial = True
            if trail is not None and np.isfinite(trail[d, j]) and c[d, j] < trail[d, j]:
                close(p, p.size, c[d, j], d, '收盘跌破跟踪线')
        risk = rules.risk
        if gate_ok is not None and not gate_ok[d]:
            risk = 0.0 if rules.gate_mode == 'block' else risk / 2
        todays = sorted(entries[d], key=lambda e: e[0]) if d < len(entries) else []
        opened = 0
        for pr, j, fill, stop, setup in todays:
            if np.isfinite(fill) and np.isfinite(stop):
                stop = min(stop, fill * (1 - rules.stop_min))
            if opened >= rules.max_new or risk <= 0:
                skipped[d] += 1
                continue
            if j in pos or len(pos) >= rules.max_open or not (np.isfinite(fill) and np.isfinite(stop)) \
                    or not (0 < stop < fill):
                skipped[d] += 1
                continue
            room = rules.gross * equity - mark(d)
            val = min(equity * risk / ((fill - stop) / fill), rules.max_position * equity, room)
            if val <= .002 * equity:
                skipped[d] += 1
                continue
            size = val / fill
            cash -= val * (1 + buy_cost)
            p = Pos(j, d, float(fill), float(stop), size, setup, -val * (1 + buy_cost), invested=val * (1 + buy_cost))
            pos[j] = p
            buys[d].append(dict(j=j, setup=setup, fill=float(fill), stop=float(stop), weight=val / equity))
            opened += 1
        equity = cash + mark(d)
        curve[d] = equity
    return dict(curve=curve, buys=buys, sells=sells, trades=trades, skipped=skipped,
                open=[dict(j=p.j, d=p.d, fill=p.fill, stop=p.stop, setup=p.setup, size=p.size) for p in pos.values()],
                equity=equity)
