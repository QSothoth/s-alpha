"""Synthetic-only DS2 event, same-clock activity and causal history checks."""
from collections import Counter
from dataclasses import replace
from datetime import date, datetime, time, timedelta
import unittest

from custody.marketdata import Bar
from custody.models import ET
from studies.us_opening_range.daily_signals import evaluate_signal_quality
from studies.us_opening_range.event_signals import (
    CANDIDATES, activity_at, context, detect_events, prefix_at_checkpoint,
)


TODAY = date(2024, 3, 18)
OPEN = datetime.combine(TODAY, time(9, 30), ET)


def bars(opening=100, prices=None, count=12, volumes=None, start=OPEN):
    rows, previous = [], opening
    for index in range(count):
        close = (prices or {}).get(index, 103)
        volume = (volumes or {}).get(index, 20)
        rows.append(Bar('US.SPY', start + timedelta(minutes=5 * (index + 1)),
                        previous, max(previous, close) + .1,
                        min(previous, close) - .1, close, volume, '5m'))
        previous = close
    return rows


def levels(**changes):
    return {'symbol': 'US.SPY', 'trade_date': TODAY.isoformat(),
            'yesterday_high': 101, 'yesterday_low': 99,
            'range_high20': 102, 'range_low20': 98, 'atr': 4,
            'previous_close': 100, 'nr7': False, 'inside': False,
            'mean_opening_volume': {15: 30, 20: 40, 30: 60}} | changes


def histories():
    daily, openings, day = [], [], TODAY
    while len(daily) < 20:
        day -= timedelta(days=1)
        if day.weekday() < 5:
            daily.append(Bar('US.SPY', datetime.combine(day, time(16), ET),
                             100, 102, 98, 100, 1000, '1d'))
            openings.append(bars(prices={i: 100 for i in range(6)}, count=6,
                                 volumes={i: i + 1 for i in range(6)},
                                 start=datetime.combine(day, time(9, 30), ET)))
    return list(reversed(daily)), list(reversed(openings))


def mirror(rows):
    return [replace(bar, open=200 - bar.open, high=200 - bar.low,
                    low=200 - bar.high, close=200 - bar.close) for bar in rows]


class ContextTests(unittest.TestCase):
    def test_same_clock_means_not_whole_day_volume_and_half_day_history(self):
        daily, openings = histories()
        daily[-1] = replace(daily[-1], close_time=daily[-1].close_time.replace(hour=13))
        known = context(daily, openings, TODAY)
        self.assertEqual(known['mean_opening_volume'], {15: 6, 20: 10, 30: 21})
        self.assertEqual(known['previous_close'], 100)
        self.assertEqual(known['atr'], 4)
        self.assertEqual(known['range_high20'], 102)
        self.assertEqual(known['range_low20'], 98)
        self.assertEqual(known['trade_date'], TODAY.isoformat())

    def test_missing_clock_does_not_damage_known_earlier_volume(self):
        daily, openings = histories()
        openings[0] = openings[0][:4]
        self.assertEqual(context(daily, openings, TODAY)['mean_opening_volume'],
                         {15: 6, 20: 10, 30: None})
        openings[0] = openings[0][:1] + openings[0][2:]
        self.assertEqual(context(daily, openings, TODAY)['mean_opening_volume'],
                         {15: None, 20: None, 30: None})

    def test_missing_day_or_empty_day_is_unknown_not_zero_or_nineteen_day_mean(self):
        daily, openings = histories()
        for past in (openings[:-1], [[]] + openings[1:], []):
            with self.subTest(length=len(past)):
                self.assertEqual(context(daily, past, TODAY)['mean_opening_volume'],
                                 {15: None, 20: None, 30: None})
        empty_volume = [[replace(bar, volume=0) for bar in rows] for rows in openings]
        self.assertEqual(context(daily, empty_volume, TODAY)['mean_opening_volume'],
                         {15: 0, 20: 0, 30: 0})

    def test_history_rejects_future_wrong_day_symbol_order_duplicate_and_extra_rows(self):
        daily, openings = histories()
        versions = [openings[:-1] + [bars(count=6)], list(reversed(openings)),
                    openings[:-1] + openings[-2:-1], openings + openings[-1:],
                    openings[:-1] + [[replace(bar, code='US.QQQ') for bar in openings[-1]]],
                    openings[:-1] + [list(reversed(openings[-1]))],
                    openings[:-1] + [openings[-1] + openings[-1][-1:]],
                    openings[:-1] + [[replace(openings[-1][0], low=0)] + openings[-1][1:]]]
        for past in versions:
            with self.subTest(length=len(past)), self.assertRaises(ValueError):
                context(daily, past, TODAY)
        with self.assertRaises(ValueError):
            context(daily[:-1], openings, TODAY)
        with self.assertRaises(ValueError):
            context(daily[:-1] + [replace(daily[-1], close_time=OPEN)], openings, TODAY)


class ActivityTests(unittest.TestCase):
    def test_rvol_uses_only_same_clock_prefix_and_equal_two_passes(self):
        daily, openings = histories()
        known = context(daily, openings, TODAY)
        current = bars(volumes={i: 2 * (i + 1) if i < 3 else 10 ** 8 for i in range(12)})
        result = activity_at(current, known, 15)
        self.assertEqual(result, {'status': 'pass', 'gap_atr': 0,
                                  'rvol': 2, 'activity_reason': 'rvol'})
        current[0] = replace(current[0], volume=current[0].volume - .01)
        self.assertEqual(activity_at(current, known, 15)['status'], 'fail')

    def test_signed_gap_equality_and_gap_or_rvol_unknown(self):
        for opening, gap in ((102, .5), (98, -.5)):
            with self.subTest(opening=opening):
                result = activity_at(bars(opening=opening), levels(mean_opening_volume={15: None}), 15)
                self.assertEqual(result, {'status': 'pass', 'gap_atr': gap,
                                          'rvol': None, 'activity_reason': 'gap'})
        for mean in (None, 0):
            result = activity_at(bars(), levels(mean_opening_volume={15: mean}), 15)
            self.assertEqual(result['status'], 'unknown')
            self.assertIsNone(result['rvol'])
            self.assertEqual(result['activity_reason'], 'rvol_unknown')

    def test_both_reasons_known_fail_bad_atr_and_bad_prefix(self):
        result = activity_at(bars(opening=103), levels(), 15)
        self.assertEqual(result['activity_reason'], 'gap_and_rvol')
        low_volume = bars(volumes={i: 10 for i in range(12)})
        self.assertEqual(activity_at(low_volume, levels(), 15)['status'], 'fail')
        self.assertEqual(activity_at(bars(), levels(atr=0), 15)['activity_reason'], 'invalid_atr')
        self.assertEqual(activity_at(bars()[1:], levels(), 15)['activity_reason'], 'invalid_prefix')

    def test_public_prefix_is_causal_complete_and_limited_to_registered_clocks(self):
        current = bars()
        self.assertEqual(prefix_at_checkpoint(current, levels(), 15), current[:3])
        changed = current[:3] + [replace(bar, low=0, code='US.BAD') for bar in current[3:]]
        self.assertEqual(prefix_at_checkpoint(changed, levels(), 15), current[:3])
        for bad in ([], current[:2], current[1:], current[:1] + current[2:],
                    [current[1], current[0]] + current[2:], current[:1] + current,
                    [replace(current[0], interval='1m')] + current[1:]):
            self.assertIsNone(prefix_at_checkpoint(bad, levels(), 15))
        with self.assertRaises(ValueError):
            prefix_at_checkpoint(current, levels(), 25)


class EventTests(unittest.TestCase):
    def test_both_break_directions_and_fixed_measurement_lines(self):
        for short in (False, True):
            with self.subTest(short=short):
                rows = bars(count=3)
                if short:
                    rows = mirror(rows)
                events, rejected = detect_events(rows, levels())
                self.assertEqual(tuple(events), CANDIDATES)
                event = events['B20_BREAK']
                self.assertEqual(event['direction'], 'SHORT' if short else 'LONG')
                self.assertEqual(event['key_level'], 98 if short else 102)
                self.assertEqual(event['risk'], 1)
                self.assertEqual(event['target'], 95 if short else 105)
                self.assertEqual(event['invalidation'], 98 if short else 102)
                self.assertEqual(event['activity_reason'], 'rvol')
                self.assertEqual(event['snapshot_minutes'], 15)
                self.assertEqual(rejected, Counter())
                self.assertIsNone(events['G20_HOLD'])
                self.assertIsNone(events['F20_FAIL'])

    def test_break_requires_two_strict_closes_and_open_inside_including_boundary(self):
        for opening in (98, 102):
            self.assertIsNotNone(detect_events(bars(opening=opening, count=3), levels())[0]['B20_BREAK'])
        for prior in (101, 102):
            events, _ = detect_events(bars(prices={1: prior}, count=3), levels())
            self.assertIsNone(events['B20_BREAK'])
        self.assertIsNone(detect_events(bars(opening=102.01, count=3), levels())[0]['B20_BREAK'])

    def test_gap_hold_strict_wick_boundary_and_continuation(self):
        rows = bars(opening=103, prices={i: 104 for i in range(3)}, count=3)
        for short in (False, True):
            current = mirror(rows) if short else rows
            self.assertIsNotNone(detect_events(current, levels())[0]['G20_HOLD'])
            touched = list(current)
            touched[1] = replace(touched[1], **({'high': 98} if short else {'low': 102}))
            self.assertIsNone(detect_events(touched, levels())[0]['G20_HOLD'])
        for close in (103, 102.9):
            flat = bars(opening=103, prices={i: close for i in range(3)}, count=3)
            self.assertIsNone(detect_events(flat, levels())[0]['G20_HOLD'])

    def test_gap_fail_is_two_inside_closes_not_touch_overshoot_or_pure_wick(self):
        rows = bars(opening=103, prices={i: 100.5 for i in range(3)}, count=3)
        for short in (False, True):
            current = mirror(rows) if short else rows
            event = detect_events(current, levels())[0]['F20_FAIL']
            self.assertEqual(event['direction'], 'LONG' if short else 'SHORT')
            self.assertEqual(event['key_level'], 98 if short else 102)
            self.assertNotEqual(event['invalidation'], event['key_level'])
        for close in (98, 102, 97, 103):
            bad = bars(opening=103, prices={i: close for i in range(3)}, count=3)
            self.assertIsNone(detect_events(bad, levels())[0]['F20_FAIL'])
        one_inside = bars(opening=103, prices={0: 104, 1: 103, 2: 100}, count=3)
        self.assertIsNone(detect_events(one_inside, levels())[0]['F20_FAIL'])
        inside_open = bars(opening=100, prices={i: 101 for i in range(3)}, count=3)
        inside_open[0] = replace(inside_open[0], high=104)
        self.assertIsNone(detect_events(inside_open, levels())[0]['F20_FAIL'])

    def test_early_gap_hold_and_later_failure_are_independent_and_retained(self):
        rows = bars(opening=103, prices={0: 104, 1: 104, 2: 104, 3: 101, 4: 101, 5: 100}, count=6)
        early = detect_events(rows[:3], levels())[0]['G20_HOLD']
        later = detect_events(rows, levels())[0]
        self.assertEqual(later['G20_HOLD'], early)
        self.assertEqual(later['F20_FAIL']['time'], rows[5].close_time.isoformat())
        self.assertEqual(later['G20_HOLD']['direction'], 'LONG')
        self.assertEqual(later['F20_FAIL']['direction'], 'SHORT')

    def test_each_fixed_clock_can_first_trigger_but_nine_fifty_five_cannot(self):
        for index in (2, 3, 5):
            rows = bars(prices={i: 101 for i in range(index - 1)})
            event = detect_events(rows, levels())[0]['B20_BREAK']
            self.assertEqual(event['time'], rows[index].close_time.isoformat())
        rows = bars(prices={0: 101, 1: 101, 2: 101, 3: 103, 4: 103, 5: 101}, count=6)
        self.assertIsNone(detect_events(rows, levels())[0]['B20_BREAK'])

    def test_activity_can_delay_first_eligible_event_and_unknown_never_passes(self):
        rows = bars(volumes={0: 10, 1: 10, 2: 10, 3: 100})
        event = detect_events(rows, levels())[0]['B20_BREAK']
        self.assertEqual(event['snapshot_minutes'], 20)
        events, rejected = detect_events(rows[:3], levels(mean_opening_volume={15: None}))
        self.assertTrue(all(value is None for value in events.values()))
        self.assertEqual(rejected, Counter(rvol_unknown=1))
        event = detect_events(bars(opening=103, prices={i: 104 for i in range(3)}, count=3),
                              levels(mean_opening_volume={15: None}))[0]['G20_HOLD']
        self.assertEqual(event['activity_reason'], 'gap')

    def test_later_bad_prices_do_not_erase_earlier_event_and_missing_prefix_never_fires(self):
        rows = bars()
        early = detect_events(rows[:3], levels())[0]['B20_BREAK']
        changed = rows[:3] + [replace(bar, low=0, code='US.WRONG') for bar in rows[3:]]
        self.assertEqual(detect_events(changed, levels())[0]['B20_BREAK'], early)
        events, rejected = detect_events(rows[1:], levels())
        self.assertTrue(all(value is None for value in events.values()))
        self.assertEqual(rejected, Counter(invalid_prefix=3))
        self.assertEqual(detect_events(rows[:2], levels())[1], Counter())

    def test_no_ds1_chase_body_or_room_filters_and_existing_label_is_reused(self):
        rows = bars(prices={i: 110 for i in range(12)})
        rows[0] = replace(rows[0], high=150)
        event = detect_events(rows, levels())[0]['B20_BREAK']
        self.assertIsNotNone(event)
        self.assertEqual(event['reference'], 110)
        self.assertEqual(event['invalidation'], 109)
        label = evaluate_signal_quality(rows, event)
        self.assertEqual(label['label_status'], 'complete')
        self.assertEqual(label['return_30m'], 0)
        self.assertLess(label['mfe_r'], 1)  # Excludes the trigger-prefix high=150.
        self.assertEqual(evaluate_signal_quality(rows[:8], event)['label_status'], 'missing_future')


if __name__ == '__main__':
    unittest.main()
