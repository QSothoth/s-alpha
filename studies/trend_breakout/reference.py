"""Per-trade reference for backtest.run: one stock at a time, plain Python scalars, written independently.

Used only by tests to check the matrix engine trade by trade on a few stocks; see backtest.py for the rules.
"""
from __future__ import annotations

import math


def _limit(prev, pct, up):
    return math.floor(prev * (1 + pct if up else 1 - pct) * 100 + 0.5) / 100


def run_stock(bars, entry, line, ratchet, eligible, atr22, lo, hi, cost=(0.0, 0.0), limit=None, max_hold=None,
              use_stop=True, fail_level=None, fail_days=0):
    """bars: list of dicts (open, close, raw_open, raw_high, raw_close) or None when suspended.
    Returns trades as tuples (signal, entry, exit, buy, sell, stop0, risk, r, ret, at_end)."""
    buy_cost, sell_cost = cost
    trades = []
    pos = None          # dict while holding
    pending = None      # (signal row, initial stop, atr) waiting for the next open
    prev_raw = None
    last_close = None
    for t in range(0, hi + 1):
        bar = bars[t]
        if t < lo - 1:
            if bar is not None:
                prev_raw = bar['raw_close']
            continue
        if t >= lo:
            fill = None
            if pending is not None:
                sig, stop0, a, level = pending
                pending = None
                capped = bar is not None and limit is not None and prev_raw is not None and \
                    bar['raw_open'] >= _limit(prev_raw, limit, True) - 1e-9
                if bar is not None and bar['open'] > stop0 and not capped:
                    fill = (sig, stop0, a, level)
            # exit at the open comes before any entry of the same day
            if pos is not None and pos['out'] and bar is not None:
                stuck = limit is not None and prev_raw is not None and \
                    bar['raw_high'] <= _limit(prev_raw, limit, False) + 1e-9
                if not stuck:
                    trades.append(_trade(pos, t, bar['open'], False, buy_cost, sell_cost))
                    pos = None
            if fill is not None:
                sig, stop0, a, level = fill
                px = bar['open']
                pos = {'sig': sig, 'row': t, 'buy': px, 'stop0': stop0, 'stop': stop0,
                       'risk': max(px - stop0, a), 'out': False, 'fail': level}
            if pos is not None and bar is not None:
                if use_stop and bar['close'] < pos['stop']:
                    pos['out'] = True
                if max_hold is not None and t - pos['row'] + 1 >= max_hold:
                    pos['out'] = True
                if fail_days and t - pos['row'] + 1 <= fail_days and bar['close'] < pos['fail']:
                    pos['out'] = True
                if not math.isnan(line[t]):
                    pos['stop'] = max(pos['stop'], line[t]) if ratchet else line[t]
        if bar is not None:
            last_close = bar['close']
            prev_raw = bar['raw_close']
            if t < hi and pos is None and entry[t] and eligible[t] and not math.isnan(line[t]):
                level = -math.inf
                if fail_level is not None and not math.isnan(fail_level[t]):
                    level = fail_level[t]
                pending = (t, line[t], atr22[t], level)
    if pos is not None:
        trades.append(_trade(pos, hi, last_close, True, buy_cost, sell_cost))
    return trades


def _trade(pos, t, px, at_end, buy_cost, sell_cost):
    net = px * (1 - sell_cost) - pos['buy'] * (1 + buy_cost)
    return (pos['sig'], pos['row'], t, pos['buy'], px, pos['stop0'], pos['risk'], net / pos['risk'],
            net / (pos['buy'] * (1 + buy_cost)), at_end)
