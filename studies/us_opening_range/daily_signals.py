"""Causal daily-level observations and 30-minute labels fixed by DS1.

No fills, exits, option returns or data access. Callers certify that historical
daily bars are complete and consecutive trading sessions on one price basis.
"""
from collections import Counter
from datetime import date, datetime, time, timedelta
import math

from custody.marketdata import Bar
from custody.models import ET


CANDIDATES = ('PD_BREAK', 'NR7_BREAK', 'INSIDE_BREAK')
SNAPSHOT_MINUTES = (15, 20, 30)


def _valid_bar(bar, interval, code):
    if not isinstance(bar, Bar):
        return False
    values = (bar.open, bar.high, bar.low, bar.close, bar.volume)
    return (bar.code == code and bar.interval == interval
            and bar.close_time.tzinfo is not None and bar.close_time.utcoffset() is not None
            and all(not isinstance(value, bool) and math.isfinite(value) for value in values)
            and min(values[:4]) > 0 and bar.volume >= 0
            and bar.low <= min(bar.open, bar.close)
            and bar.high >= max(bar.open, bar.close))


def daily_levels(history: list[Bar], today: date) -> dict:
    """Freeze 20 earlier daily bars; 13:00 half-day closes are also valid.

    Daily timestamps identify ET dates, not an assumed full-session close hour.
    Calendar gaps/completeness must be checked by the source-reading caller.
    """
    if len(history) != 20:
        raise ValueError('exactly twenty complete historical daily bars are required')
    previous, code = None, history[0].code
    for bar in history:
        day = bar.close_time.astimezone(ET).date()
        if (not _valid_bar(bar, '1d', code) or day >= today
                or previous is not None and day <= previous):
            raise ValueError('daily history must be valid, same-symbol, ordered and before today')
        previous = day
    yesterday, before = history[-1], history[-2]
    atr = sum(max(bar.high - bar.low, abs(bar.high - history[index - 1].close),
                  abs(bar.low - history[index - 1].close))
              for index, bar in enumerate(history) if index >= 6) / 14
    return {'symbol': code, 'trade_date': today.isoformat(),
            'yesterday_high': yesterday.high, 'yesterday_low': yesterday.low,
            'range_high20': max(bar.high for bar in history),
            'range_low20': min(bar.low for bar in history), 'atr': atr,
            'nr7': yesterday.high - yesterday.low <= min(bar.high - bar.low for bar in history[-7:]),
            'inside': (yesterday.high <= before.high and yesterday.low >= before.low
                       and (yesterday.high < before.high or yesterday.low > before.low))}


def _prefix_at(bars, cutoff):
    """Truncate before checking prices/order; later rows cannot erase a signal."""
    prefix, reached = [], False
    for bar in bars:
        if bar.close_time > cutoff:
            reached = True
            break
        prefix.append(bar)
        reached = reached or bar.close_time == cutoff
    return prefix, reached


def detect_signals(bars, levels):
    """Return candidate observations and first-failing checkpoint gate counts.

    Only reached checkpoints are counted, and evaluation stops at the earliest
    shared trigger. Static NR7/inside flags make qualifying candidates subsets
    of PD at that same instant. Prices after that instant are never validated.
    """
    signals, rejected = dict.fromkeys(CANDIDATES), Counter()
    today = date.fromisoformat(levels['trade_date'])
    opening = datetime.combine(today, time(9, 30), ET)
    code, atr = levels['symbol'], levels['atr']
    for minutes in SNAPSHOT_MINUTES:
        cutoff = opening + timedelta(minutes=minutes)
        prefix, reached = _prefix_at(bars, cutoff)
        if not reached:
            continue
        if (len(prefix) != minutes // 5
                or any(not _valid_bar(bar, '5m', code)
                       or bar.close_time != opening + timedelta(minutes=5 * index)
                       for index, bar in enumerate(prefix, 1))):
            rejected['invalid_prefix'] += 1
            continue
        if not math.isfinite(atr) or atr <= 0:
            rejected['invalid_atr'] += 1
            continue
        high, low = max(bar.high for bar in prefix), min(bar.low for bar in prefix)
        width, reference = high - low, prefix[-1].close
        if width <= 0:
            rejected['zero_range'] += 1
            continue
        if levels['yesterday_high'] + .05 * atr <= reference <= levels['yesterday_high'] + .25 * atr:
            direction, sign, level = 'LONG', 1, levels['yesterday_high']
            boundary = levels['range_high20']
        elif levels['yesterday_low'] - .25 * atr <= reference <= levels['yesterday_low'] - .05 * atr:
            direction, sign, level = 'SHORT', -1, levels['yesterday_low']
            boundary = levels['range_low20']
        else:
            rejected['breakout_band'] += 1
            continue
        if sign * (reference - prefix[0].open) < .5 * width:
            rejected['directional_body'] += 1
            continue
        invalidation = level - sign * .1 * atr
        risk = abs(reference - invalidation)
        target = reference + sign * 2 * risk
        distance = sign * (boundary - reference)
        if distance >= 0 and distance < 2 * risk:
            rejected['insufficient_room'] += 1
            continue
        room = 'beyond_observed_20d_range' if distance < 0 else 'room_to_20d_boundary'
        eligible = (True, levels['nr7'], levels['inside'])
        for candidate, enabled in zip(CANDIDATES, eligible):
            if enabled:
                signals[candidate] = {'time': cutoff.isoformat(), 'symbol': code,
                                      'candidate': candidate, 'direction': direction,
                                      'reference': reference, 'level': level,
                                      'invalidation': invalidation, 'risk': risk,
                                      'target': target, 'room_state': room,
                                      'boundary20': boundary, 'atr': atr,
                                      'snapshot_minutes': minutes}
        break
    return signals, rejected


def evaluate_signal_quality(bars, signal):
    """Label exactly six future bars, never the signal bar; MFE/MAE are >= 0.

    Incomplete, duplicate, unordered or invalid future bars leave every label
    missing. They cannot retract a previously emitted observation.
    """
    result = dict.fromkeys(('return_30m', 'return_atr', 'mfe_r', 'mae_r', 'path_status'))
    result['label_status'] = 'missing_future'
    start = datetime.fromisoformat(signal['time'])
    end = start + timedelta(minutes=30)
    future = [bar for bar in bars if start < bar.close_time <= end]
    if (len(future) != 6
            or any(not _valid_bar(bar, '5m', signal['symbol'])
                   or bar.close_time != start + timedelta(minutes=5 * index)
                   for index, bar in enumerate(future, 1))):
        return result
    sign = 1 if signal['direction'] == 'LONG' else -1
    reference, risk = signal['reference'], signal['risk']
    target, invalidation = signal['target'], signal['invalidation']
    favorable = [sign * ((bar.high if sign == 1 else bar.low) - reference) for bar in future]
    adverse = [-sign * ((bar.low if sign == 1 else bar.high) - reference) for bar in future]
    path = 'neither'
    for bar in future:
        hit_target = bar.high >= target if sign == 1 else bar.low <= target
        hit_stop = bar.low <= invalidation if sign == 1 else bar.high >= invalidation
        if hit_target or hit_stop:
            path = 'ambiguous' if hit_target and hit_stop else 'target_first' if hit_target else 'stop_first'
            break
    result.update(label_status='complete',
                  return_30m=sign * (future[-1].close / reference - 1),
                  return_atr=sign * (future[-1].close - reference) / signal['atr'],
                  mfe_r=max(0, *favorable) / risk, mae_r=max(0, *adverse) / risk,
                  path_status=path)
    return result
