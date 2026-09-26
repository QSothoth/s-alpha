"""Four causal five-minute context rules fixed in notes/OR2_PREREG.md."""
from datetime import datetime, time, timedelta
import math

from custody.models import ET


CANDIDATES = ('B30', 'N30', 'R30', 'C30')


def validate_day(bars):
    """Require one unmodified, complete regular 78-bar US five-minute session."""
    if len(bars) != 78:
        raise ValueError('a complete normal session requires exactly 78 five-minute bars')
    first = bars[0].close_time.astimezone(ET)
    opening = datetime.combine(first.date(), time(9, 30), ET)
    code = bars[0].code
    for index, bar in enumerate(bars, 1):
        if bar.close_time != opening + timedelta(minutes=5 * index):
            raise ValueError('missing, duplicate or unordered five-minute timestamp')
        values = (bar.open, bar.high, bar.low, bar.close, bar.volume)
        if (bar.code != code or bar.interval != '5m'
                or not all(math.isfinite(value) for value in values)
                or min(values[:4]) <= 0 or bar.volume < 0
                or bar.low > min(bar.open, bar.close)
                or bar.high < max(bar.open, bar.close) or bar.low > bar.high):
            raise ValueError('invalid five-minute OHLCV or mixed underlying codes')


def _execute(bars, index, direction, high, low):
    signal = bars[index]
    if index + 1 >= len(bars):
        raise ValueError('signal has no next completed bar for entry')
    entry = bars[index + 1]
    sign = 1 if direction == 'LONG' else -1
    stop = (high + low) / 2
    target = signal.close + 2 * (signal.close - stop)
    timeout = signal.close_time + timedelta(minutes=60)
    flatten = datetime.combine(signal.close_time.astimezone(ET).date(), time(15, 45), ET)
    # The pending entry fills before checking an exit at that same close.
    for exit_index in range(index + 1, len(bars)):
        bar = bars[exit_index]
        if sign * (bar.close - stop) <= 0:
            reason = 'stop'
        elif sign * (bar.close - target) >= 0:
            reason = 'target'
        elif bar.close_time >= timeout:
            reason = 'timeout'
        elif bar.close_time >= flatten:
            reason = 'flatten'
        else:
            continue
        if exit_index + 1 >= len(bars):
            raise ValueError('exit decision has no next completed bar for execution')
        exit_bar = bars[exit_index + 1]
        return {'direction': direction, 'signal_time': signal.close_time,
                'signal_price': signal.close, 'entry_time': entry.close_time,
                'entry_price': entry.close, 'exit_decision_time': bar.close_time,
                'exit_time': exit_bar.close_time, 'exit_price': exit_bar.close,
                'exit_reason': reason, 'stop': stop, 'target': target,
                'gross_return': sign * (exit_bar.close / entry.close - 1)}
    raise ValueError('complete session did not produce an executable scheduled exit')


def context_trades(bars, history, market_bars=None):
    """Return B30/N30/R30/C30 trades or None, without fees or option-price inference.

    The caller validates each historical day once with ``validate_day`` before
    adding it to its bounded window; only the fourteen dates/openings are checked
    again here. Invalid or unaligned SPY data disables R30/C30 only.
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
    market_ok = False
    if market_bars:
        try:
            validate_day(market_bars)
            market_ok = (market_bars[0].code == 'US.SPY'
                         and market_bars[0].close_time == bars[0].close_time)
        except ValueError:
            pass
    signals = {candidate: None for candidate in CANDIDATES}
    high = max(bar.high for bar in bars[:6])
    low = min(bar.low for bar in bars[:6])
    width = high - low
    if width <= 0:
        return signals
    open_price, previous_close = bars[0].open, history[-1][-1].close
    if market_ok:
        market_open = market_bars[0].open
        market_high = max(bar.high for bar in market_bars[:6])
        market_low = min(bar.low for bar in market_bars[:6])
    deadline = datetime.combine(today, time(11), ET)
    turnover = volume = 0.0
    for index, bar in enumerate(bars):
        if bar.close_time > deadline:
            break
        turnover += (bar.high + bar.low + bar.close) / 3 * bar.volume
        volume += bar.volume
        if index < 6 or volume <= 0:
            continue
        vwap = turnover / volume
        if high < bar.close <= high + width / 4 and bar.close > vwap:
            direction = 'LONG'
        elif low - width / 4 <= bar.close < low and bar.close < vwap:
            direction = 'SHORT'
        else:
            continue
        sigma = sum(abs(past[index].close / past[0].open - 1) for past in history) / 14
        noise_ok = (bar.close > max(open_price, previous_close) * (1 + sigma) if direction == 'LONG'
                    else bar.close < min(open_price, previous_close) * (1 - sigma))
        relative_ok = confirmation_ok = False
        if market_ok:
            relative = bar.close / open_price - 1 - (market_bars[index].close / market_open - 1)
            relative_ok = bars[0].code != 'US.SPY' and (relative > 0 if direction == 'LONG' else relative < 0)
            confirmation_ok = (market_bars[index].close > market_high if direction == 'LONG'
                               else market_bars[index].close < market_low)
        eligible = {'B30': True, 'N30': noise_ok, 'R30': relative_ok, 'C30': confirmation_ok}
        for candidate in CANDIDATES:
            if signals[candidate] is None and eligible[candidate]:
                signals[candidate] = (index, direction)
    return {candidate: _execute(bars, signal[0], signal[1], high, low) if signal else None
            for candidate, signal in signals.items()}
