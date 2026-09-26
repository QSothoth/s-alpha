"""Two single-entry trend rules fixed in notes/OR3_PREREG.md."""
from datetime import datetime, time
import math

from custody.models import ET
from .context_signals import validate_day


CANDIDATES = ('O30_VWAP', 'N30_TRAIL')


def _trade(bars, signal_index, exit_index, direction, reason):
    if signal_index + 1 >= len(bars) or exit_index + 1 >= len(bars):
        raise ValueError('decision has no next completed bar for execution')
    signal, entry = bars[signal_index], bars[signal_index + 1]
    decision, exit_bar = bars[exit_index], bars[exit_index + 1]
    sign = 1 if direction == 'LONG' else -1
    return {'direction': direction, 'signal_time': signal.close_time,
            'signal_price': signal.close, 'entry_time': entry.close_time,
            'entry_price': entry.close, 'exit_decision_time': decision.close_time,
            'exit_time': exit_bar.close_time, 'exit_price': exit_bar.close,
            'exit_reason': reason, 'stop': None, 'target': None,
            'gross_return': sign * (exit_bar.close / entry.close - 1)}


def trend_trades(bars, history):
    """Return the two frozen OR3 trades, with no fees or option-price inference.

    The streaming caller validates each historical day with ``validate_day``
    before retaining it. Recheck its length, identity and past-only ordering here,
    without repeating all fourteen full OHLCV validations for every new session.
    """
    validate_day(bars)
    if len(history) != 14:
        raise ValueError('exactly fourteen previously validated complete days are required')
    today = bars[0].close_time.astimezone(ET).date()
    previous_day = None
    for past in history:
        if len(past) != 78:
            raise ValueError('history must contain only complete normal sessions')
        day = past[0].close_time.astimezone(ET).date()
        if (day >= today or previous_day is not None and day <= previous_day
                or past[0].code != bars[0].code or not math.isfinite(past[0].open) or past[0].open <= 0):
            raise ValueError('history must be earlier ordered days of the same underlying')
        previous_day = day
    high, low = max(bar.high for bar in bars[:6]), min(bar.low for bar in bars[:6])
    width = high - low
    open_price, previous_close = bars[0].open, history[-1][-1].close
    flatten = datetime.combine(today, time(15, 45), ET)
    signals = {name: None for name in CANDIDATES}
    trades = {name: None for name in CANDIDATES}
    turnover = volume = 0.0
    for index, bar in enumerate(bars):
        if bar.close_time > flatten:
            break
        turnover += (bar.high + bar.low + bar.close) / 3 * bar.volume
        volume += bar.volume
        if volume <= 0:
            continue
        vwap = turnover / volume
        clock = bar.close_time.astimezone(ET).time()
        half_hour = clock.minute in (0, 30)
        if half_hour:
            sigma = sum(abs(past[index].close / past[0].open - 1) for past in history) / 14
            upper = max(open_price, previous_close) * (1 + sigma)
            lower = min(open_price, previous_close) * (1 - sigma)
        for name in CANDIDATES:
            if trades[name] is not None:
                continue
            if signals[name] is None:
                direction = None
                if name == 'O30_VWAP' and width > 0 and time(10, 5) <= clock <= time(11):
                    if high < bar.close <= high + width / 4 and bar.close > vwap:
                        direction = 'LONG'
                    elif low - width / 4 <= bar.close < low and bar.close < vwap:
                        direction = 'SHORT'
                elif name == 'N30_TRAIL' and half_hour and time(10) <= clock <= time(14, 30):
                    if bar.close > upper and bar.close > vwap:
                        direction = 'LONG'
                    elif bar.close < lower and bar.close < vwap:
                        direction = 'SHORT'
                if direction is not None:
                    if index + 1 >= len(bars):
                        raise ValueError('signal has no next completed bar for entry')
                    signals[name] = (index, direction)
                continue
            signal_index, direction = signals[name]
            # The pending next-close entry is filled before eligible exit checks.
            reason = None
            if bar.close_time >= flatten:
                reason = 'flatten'
            elif name == 'O30_VWAP':
                if (bar.close <= vwap if direction == 'LONG' else bar.close >= vwap):
                    reason = 'vwap'
            elif half_hour:
                boundary = max(upper, vwap) if direction == 'LONG' else min(lower, vwap)
                if (bar.close <= boundary if direction == 'LONG' else bar.close >= boundary):
                    reason = 'trail'
            if reason is not None:
                trades[name] = _trade(bars, signal_index, index, direction, reason)
    if any(signals[name] is not None and trades[name] is None for name in CANDIDATES):
        raise ValueError('complete session did not produce an executable scheduled exit')
    return trades
