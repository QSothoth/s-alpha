"""Causal, read-only opening-range rules fixed in notes/OR1_PREREG.md."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Iterable

from custody.marketdata import Bar
from custody.models import ET, Session


CANDIDATES = {
    'OR15_breakout': (15, 'breakout'),
    'OR15_retest': (15, 'retest'),
    'OR30_breakout': (30, 'breakout'),
    'OR30_retest': (30, 'retest'),
}


@dataclass(frozen=True)
class Signal:
    direction: str
    time: datetime
    price: float
    range_high: float
    range_low: float
    stop: float
    target: float


def _validated(bars: Iterable[Bar], session: Session):
    """Validate only the consumed prefix; never sort, pad or inspect the future."""
    expected = session.opens + timedelta(minutes=1)
    code = None
    for bar in bars:
        if bar.close_time != expected or bar.close_time > session.closes:
            raise ValueError('expected continuous session minute at ' + expected.isoformat())
        if bar.interval != '1m' or min(bar.open, bar.high, bar.low, bar.close) <= 0:
            raise ValueError('positive 1m OHLC prices required')
        if code is not None and bar.code != code:
            raise ValueError('mixed underlying codes')
        code = bar.code
        expected += timedelta(minutes=1)
        yield bar


def opening_range(bars: Iterable[Bar], session: Session, minutes: int):
    """Return frozen (high, low), or None while the opening range is incomplete."""
    if minutes not in (15, 30):
        raise ValueError('opening range must be 15 or 30 minutes')
    high, low = float('-inf'), float('inf')
    for count, bar in enumerate(_validated(bars, session), 1):
        high, low = max(high, bar.high), min(low, bar.low)
        if count == minutes:
            return high, low
    return None


def find_signal(bars: Iterable[Bar], session: Session, candidate: str) -> Signal | None:
    """Find the first signal in a continuous, completed prefix starting at 09:31."""
    if candidate not in CANDIDATES:
        raise ValueError('unknown opening-range candidate: ' + str(candidate))
    minutes, mode = CANDIDATES[candidate]
    deadline = datetime.combine(session.opens.astimezone(ET).date(), time(11), ET)
    high, low = float('-inf'), float('inf')
    block_high, block_low = float('-inf'), float('inf')
    turnover = volume = 0.0
    waiting = None
    for count, bar in enumerate(_validated(bars, session), 1):
        if bar.close_time >= deadline:
            return None
        turnover += (bar.high + bar.low + bar.close) / 3 * bar.volume
        volume += bar.volume
        if count <= minutes:
            high, low = max(high, bar.high), min(low, bar.low)
            continue
        block_high = max(block_high, bar.high)
        block_low = min(block_low, bar.low)
        if count % 5:
            continue
        width = high - low
        direction = None
        if width > 0 and volume > 0:
            vwap = turnover / volume
            if high < bar.close <= high + width / 4 and bar.close > vwap:
                direction = 'LONG'
            elif low - width / 4 <= bar.close < low and bar.close < vwap:
                direction = 'SHORT'
        if (waiting == 'LONG' and bar.close <= high
                or waiting == 'SHORT' and bar.close >= low):
            waiting = None
        retested = (waiting == 'LONG' and block_low <= high
                    or waiting == 'SHORT' and block_high >= low)
        if direction is not None and (mode == 'breakout' or waiting == direction and retested):
            stop = (high + low) / 2
            return Signal(direction, bar.close_time.astimezone(ET), bar.close, high, low,
                          stop, bar.close + 2 * (bar.close - stop))
        if direction is not None:
            waiting = direction
        block_high, block_low = float('-inf'), float('inf')
    return None


def exit_signal(bars: Iterable[Bar], session: Session, signal: Signal) -> tuple[datetime, str] | None:
    """Evaluate later 1m closes; accept the same full-session prefix as find_signal."""
    if signal.direction not in ('LONG', 'SHORT'):
        raise ValueError('signal direction must be LONG or SHORT')
    timeout = signal.time + timedelta(minutes=60)
    flatten = session.closes - timedelta(minutes=15)
    sign = 1 if signal.direction == 'LONG' else -1
    for bar in _validated(bars, session):
        if bar.close_time <= signal.time:
            continue
        reason = None
        if sign * (bar.close - signal.stop) <= 0:
            reason = 'stop'
        elif sign * (bar.close - signal.target) >= 0:
            reason = 'target'
        elif bar.close_time >= timeout:
            reason = 'timeout'
        elif bar.close_time >= flatten:
            reason = 'flatten'
        if reason is not None:
            return bar.close_time.astimezone(ET), reason
    return None
