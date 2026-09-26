"""DS2's fixed active-day boundary events; observations, never execution rules."""
from collections import Counter
from datetime import date, datetime, time, timedelta
from math import fsum, isfinite

from custody.models import ET
from .daily_signals import SNAPSHOT_MINUTES, _prefix_at, _valid_bar, daily_levels


CANDIDATES = ('B20_BREAK', 'G20_HOLD', 'F20_FAIL')


def prefix_at_checkpoint(bars, levels, minutes):
    """Return only a reached, complete RTH prefix, ignoring later prices."""
    if minutes not in SNAPSHOT_MINUTES:
        raise ValueError('DS2 permits only 15, 20 and 30 minute checkpoints')
    opening = datetime.combine(date.fromisoformat(levels['trade_date']), time(9, 30), ET)
    prefix, reached = _prefix_at(bars, opening + timedelta(minutes=minutes))
    if (not reached or len(prefix) != minutes // 5
            or any(not _valid_bar(bar, '5m', levels['symbol'])
                   or bar.close_time != opening + timedelta(minutes=5 * index)
                   for index, bar in enumerate(prefix, 1))):
        return None
    return prefix


def context(daily_history20, opening_history20, today):
    """Freeze daily context and available same-clock volume from 20 earlier days.

    Missing opening days/minutes make that clock's denominator unknown. Present
    rows must still be valid, ordered, same-symbol and aligned to the daily dates;
    the caller certifies full-session completeness before putting a day in history.
    """
    levels = daily_levels(daily_history20, today)
    if len(opening_history20) > 20:
        raise ValueError('at most twenty historical opening prefixes are permitted')
    dates = {bar.close_time.astimezone(ET).date() for bar in daily_history20}
    past, previous = {}, None
    for rows in opening_history20:
        if not rows:
            continue
        day = rows[0].close_time.astimezone(ET).date()
        if day not in dates or previous is not None and day <= previous or len(rows) > 6:
            raise ValueError('opening history must be earlier ordered daily-aligned first-six bars')
        previous = day
        stamp = None
        for bar in rows:
            if (not _valid_bar(bar, '5m', levels['symbol'])
                    or bar.close_time.astimezone(ET).date() != day
                    or stamp is not None and bar.close_time <= stamp):
                raise ValueError('invalid, mixed-symbol or unordered historical opening bars')
            stamp = bar.close_time
        past[day] = rows
    means = {}
    for minutes in SNAPSHOT_MINUTES:
        volumes = []
        for day in sorted(dates):
            prefix = prefix_at_checkpoint(past.get(day, []), levels | {'trade_date': day.isoformat()}, minutes)
            if prefix is None:
                break
            volumes.append(fsum(bar.volume for bar in prefix))
        means[minutes] = fsum(volumes) / 20 if len(volumes) == 20 else None
    return levels | {'previous_close': daily_history20[-1].close, 'mean_opening_volume': means}


def activity_at(bars_prefix, levels, minutes):
    """Three-valued activity gate; gap_atr is signed and tested in absolute value."""
    result = {'status': 'unknown', 'gap_atr': None, 'rvol': None, 'activity_reason': 'invalid_prefix'}
    prefix = prefix_at_checkpoint(bars_prefix, levels, minutes)
    if prefix is None:
        return result
    atr = levels['atr']
    if not isfinite(atr) or atr <= 0:
        return result | {'activity_reason': 'invalid_atr'}
    gap = (prefix[0].open - levels['previous_close']) / atr
    mean = levels['mean_opening_volume'].get(minutes)
    rvol = fsum(bar.volume for bar in prefix) / mean if mean is not None and isfinite(mean) and mean > 0 else None
    gap_ok, volume_ok = abs(gap) >= .5, rvol is not None and rvol >= 2
    if gap_ok or volume_ok:
        status = 'pass'
        reason = 'gap_and_rvol' if gap_ok and volume_ok else 'gap' if gap_ok else 'rvol'
    else:
        status, reason = ('unknown', 'rvol_unknown') if rvol is None else ('fail', 'below_threshold')
    return {'status': status, 'gap_atr': gap, 'rvol': rvol, 'activity_reason': reason}


def detect_events(bars5m, levels):
    """Keep each candidate's independent first event, including early G/later F."""
    signals, rejected = dict.fromkeys(CANDIDATES), Counter()
    opening_time = datetime.combine(date.fromisoformat(levels['trade_date']), time(9, 30), ET)
    high, low, atr = levels['range_high20'], levels['range_low20'], levels['atr']
    for minutes in SNAPSHOT_MINUTES:
        cutoff = opening_time + timedelta(minutes=minutes)
        _, reached = _prefix_at(bars5m, cutoff)
        if not reached:
            continue
        prefix = prefix_at_checkpoint(bars5m, levels, minutes)
        if prefix is None:
            rejected['invalid_prefix'] += 1
            continue
        activity = activity_at(prefix, levels, minutes)
        if activity['status'] != 'pass':
            rejected[activity['activity_reason']] += 1
            continue
        opening, reference = prefix[0].open, prefix[-1].close
        last_two = [bar.close for bar in prefix[-2:]]
        events = {}
        if low <= opening <= high:
            if all(price > high for price in last_two):
                events['B20_BREAK'] = ('LONG', high)
            elif all(price < low for price in last_two):
                events['B20_BREAK'] = ('SHORT', low)
        elif opening > high:
            if all(bar.low > high for bar in prefix) and reference > opening:
                events['G20_HOLD'] = ('LONG', high)
            if all(low < price < high for price in last_two):
                events['F20_FAIL'] = ('SHORT', high)
        else:
            if all(bar.high < low for bar in prefix) and reference < opening:
                events['G20_HOLD'] = ('SHORT', low)
            if all(low < price < high for price in last_two):
                events['F20_FAIL'] = ('LONG', low)
        if not events:
            rejected['no_event'] += 1
        for candidate, (direction, key_level) in events.items():
            if signals[candidate] is not None:
                continue
            sign = 1 if direction == 'LONG' else -1
            signals[candidate] = {'time': cutoff.isoformat(), 'symbol': levels['symbol'],
                                  'candidate': candidate, 'direction': direction,
                                  'reference': reference, 'atr': atr,
                                  'risk': .25 * atr, 'invalidation': reference - sign * .25 * atr,
                                  'target': reference + sign * .5 * atr,
                                  'key_level': key_level, 'range_high20': high, 'range_low20': low,
                                  'snapshot_minutes': minutes,
                                  'gap_atr': activity['gap_atr'], 'rvol': activity['rvol'],
                                  'activity_status': activity['status'],
                                  'activity_reason': activity['activity_reason']}
    return signals, rejected
