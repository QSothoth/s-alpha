"""Synthetic-only DS1 checks: causal snapshots and labels, not strategy returns."""
from collections import Counter
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
import unittest

from custody.marketdata import Bar
from custody.models import ET
from studies.us_opening_range.daily_signals import (
    CANDIDATES, daily_levels, detect_signals, evaluate_signal_quality,
)


TODAY = date(2024, 3, 18)
OPEN = datetime.combine(TODAY, time(9, 30), ET)


def history():
    days, day = [], TODAY
    while len(days) < 20:
        day -= timedelta(days=1)
        if day.weekday() < 5:
            days.append(Bar('US.SPY', datetime.combine(day, time(16), ET),
                            100, 102, 98, 100, 1000, '1d'))
    return list(reversed(days))


def levels(**changes):
    out = {'symbol': 'US.SPY', 'trade_date': TODAY.isoformat(),
           'yesterday_high': 100, 'yesterday_low': 96, 'range_high20': 110,
           'range_low20': 90, 'atr': 2, 'nr7': True, 'inside': True}
    return out | changes


def bars(prices=None, count=12, opening=99):
    out, previous = [], opening
    for index in range(count):
        close = (prices or {}).get(index, 100.2)
        out.append(Bar('US.SPY', OPEN + timedelta(minutes=5 * (index + 1)),
                       previous, max(previous, close) + .05,
                       min(previous, close) - .05, close, 10, '5m'))
        previous = close
    return out


def mirror(rows):
    return [replace(bar, open=200 - bar.open, high=200 - bar.low,
                    low=200 - bar.high, close=200 - bar.close) for bar in rows]


def mirror_levels(source):
    return source | {'yesterday_high': 200 - source['yesterday_low'],
                     'yesterday_low': 200 - source['yesterday_high'],
                     'range_high20': 200 - source['range_low20'],
                     'range_low20': 200 - source['range_high20']}


class DailyLevelsTests(unittest.TestCase):
    def test_atr_uses_fourteen_true_ranges_with_previous_close(self):
        past = history()
        past[5] = replace(past[5], high=111, close=110)
        out = daily_levels(past, TODAY)
        self.assertAlmostEqual(out['atr'], (12 + 13 * 4) / 14)
        self.assertEqual(out['range_high20'], 111)
        self.assertEqual(out['yesterday_high'], 102)
        self.assertEqual(out['yesterday_low'], 98)
        self.assertEqual(out['range_low20'], 98)
        self.assertEqual(out['symbol'], 'US.SPY')
        self.assertEqual(out['trade_date'], TODAY.isoformat())

    def test_nr7_includes_yesterday_allows_ties_and_ignores_eighth_day(self):
        past = history()
        self.assertTrue(daily_levels(past, TODAY)['nr7'])
        past[-8] = replace(past[-8], high=101, low=99)
        self.assertTrue(daily_levels(past, TODAY)['nr7'])
        past[-7] = replace(past[-7], high=101, low=99)
        self.assertFalse(daily_levels(past, TODAY)['nr7'])
        past[-1] = replace(past[-1], high=101, low=99)
        self.assertTrue(daily_levels(past, TODAY)['nr7'])

    def test_inside_requires_at_least_one_strict_side(self):
        past = history()
        self.assertFalse(daily_levels(past, TODAY)['inside'])
        for high, low, expected in [(102, 99, True), (101, 98, True),
                                     (101, 99, True), (103, 99, False),
                                     (101, 97, False)]:
            with self.subTest(high=high, low=low):
                changed = past[:-1] + [replace(past[-1], high=high, low=low)]
                self.assertEqual(daily_levels(changed, TODAY)['inside'], expected)

    def test_historical_half_day_and_utc_date_are_accepted(self):
        past = history()
        past[-1] = replace(past[-1], close_time=past[-1].close_time.replace(hour=13))
        expected = daily_levels(past, TODAY)
        utc = [replace(bar, close_time=bar.close_time.astimezone(timezone.utc)) for bar in past]
        self.assertEqual(daily_levels(utc, TODAY), expected)

    def test_rejects_wrong_count_future_duplicates_order_symbol_interval_and_price(self):
        past = history()
        invalid = [past[:-1], past + past[-1:], list(reversed(past)), past[:-1] + past[-2:-1],
                   past[:-1] + [replace(past[-1], close_time=OPEN)],
                   past[:-1] + [replace(past[-1], code='US.QQQ')],
                   past[:-1] + [replace(past[-1], interval='5m')],
                   past[:-1] + [replace(past[-1], low=0)]]
        for rows in invalid:
            with self.subTest(rows=len(rows)), self.assertRaises(ValueError):
                daily_levels(rows, TODAY)


class DailySignalTests(unittest.TestCase):
    def test_first_shared_trigger_has_fixed_levels_and_candidate_flags(self):
        signals, rejected = detect_signals(bars(), levels(inside=False))
        self.assertEqual(tuple(signals), CANDIDATES)
        self.assertEqual(rejected, Counter())
        signal = signals['PD_BREAK']
        self.assertEqual(signal['time'], (OPEN + timedelta(minutes=15)).isoformat())
        self.assertEqual(signal['snapshot_minutes'], 15)
        self.assertEqual(signal['reference'], 100.2)
        self.assertEqual(signal['level'], 100)
        self.assertAlmostEqual(signal['invalidation'], 99.8)
        self.assertAlmostEqual(signal['risk'], .4)
        self.assertAlmostEqual(signal['target'], 101)
        self.assertEqual(signal['room_state'], 'room_to_20d_boundary')
        self.assertEqual(signals['NR7_BREAK'], signal | {'candidate': 'NR7_BREAK'})
        self.assertIsNone(signals['INSIDE_BREAK'])

    def test_each_registered_snapshot_is_the_earliest_and_later_prices_do_not_matter(self):
        for index in (2, 3, 5):
            with self.subTest(index=index):
                rows = bars({i: 99.8 for i in range(index)})
                expected, rejected = detect_signals(rows[:index + 1], levels())
                self.assertEqual(expected['PD_BREAK']['time'], rows[index].close_time.isoformat())
                self.assertEqual(sum(rejected.values()), {2: 0, 3: 1, 5: 2}[index])
                changed = rows[:index + 1] + [replace(bar, open=1, high=2, low=0, close=1,
                                                     code='US.WRONG') for bar in rows[index + 1:]]
                self.assertEqual(detect_signals(changed, levels()), (expected, rejected))
                self.assertEqual(detect_signals(rows, levels()), (expected, rejected))

    def test_unregistered_clock_never_fires_and_future_loss_does_not_erase_signal(self):
        rows = bars({i: 99.8 for i in range(12)})
        rows[4] = replace(rows[4], high=100.25, close=100.2)
        self.assertTrue(all(value is None for value in detect_signals(rows, levels())[0].values()))
        signal = detect_signals(bars(count=3), levels())[0]
        self.assertEqual(detect_signals(bars({i: 97 for i in range(3, 12)}), levels())[0], signal)

    def test_missing_duplicate_unordered_wrong_code_or_invalid_prefix_is_rejected(self):
        rows = bars(count=6)
        versions = [rows[1:], rows[:1] + rows[2:], rows[:2] + rows[1:2] + rows[2:],
                    [rows[1], rows[0]] + rows[2:],
                    [replace(rows[0], code='US.QQQ')] + rows[1:],
                    [replace(rows[0], low=0)] + rows[1:],
                    [replace(rows[0], interval='1m')] + rows[1:]]
        for changed in versions:
            with self.subTest(size=len(changed)):
                signals, rejected = detect_signals(changed, levels())
                self.assertTrue(all(value is None for value in signals.values()))
                self.assertEqual(rejected, Counter(invalid_prefix=3))

    def test_not_yet_reached_clocks_are_not_missing_and_wrong_day_is_rejected(self):
        self.assertEqual(detect_signals(bars(count=2), levels()), (dict.fromkeys(CANDIDATES), Counter()))
        self.assertEqual(detect_signals([], levels()), (dict.fromkeys(CANDIDATES), Counter()))
        tomorrow = [replace(bar, close_time=bar.close_time + timedelta(days=1)) for bar in bars()]
        self.assertEqual(detect_signals(tomorrow, levels())[1], Counter(invalid_prefix=3))

    def test_breakout_band_edges_are_inclusive_and_both_sides_are_mirrors(self):
        for price, expected in [(100.1, True), (100.5, True), (100.099, False), (100.501, False)]:
            for short in (False, True):
                with self.subTest(price=price, short=short):
                    rows, known = bars({i: price for i in range(3)}, count=3), levels()
                    if short:
                        rows, known = mirror(rows), mirror_levels(known)
                    signal = detect_signals(rows, known)[0]['PD_BREAK']
                    self.assertEqual(signal is not None, expected)
                    if signal:
                        self.assertEqual(signal['direction'], 'SHORT' if short else 'LONG')

    def test_directional_body_half_inclusive_and_wrong_direction_rejected(self):
        rows = [replace(bar, open=99, high=101.4, low=99, close=100.2) for bar in bars(count=3)]
        # Use exactly representable prices to test the 0.5 body boundary.
        rows = [replace(bar, open=99, high=102, low=99, close=100.5) for bar in rows]
        self.assertIsNotNone(detect_signals(rows, levels())[0]['PD_BREAK'])
        rows[0] = replace(rows[0], low=98.99)
        self.assertEqual(detect_signals(rows, levels())[1], Counter(directional_body=1))
        self.assertEqual(detect_signals(bars(count=3, opening=101), levels())[1], Counter(directional_body=1))

    def test_room_equality_and_beyond_observed_boundary(self):
        rows = bars({i: 100.5 for i in range(3)}, count=3)
        baseline = detect_signals(rows, levels())[0]['PD_BREAK']
        for short in (False, True):
            for boundary, accepted, state in [(baseline['target'], True, 'room_to_20d_boundary'),
                                               (100.5, False, None), (100.6, False, None),
                                               (100.4, True, 'beyond_observed_20d_range')]:
                with self.subTest(short=short, boundary=boundary):
                    known = levels(range_high20=boundary)
                    current = rows
                    if short:
                        known, current = mirror_levels(known), mirror(rows)
                    result, rejected = detect_signals(current, known)
                    signal = result['PD_BREAK']
                    self.assertEqual(signal is not None, accepted)
                    if accepted:
                        self.assertEqual(signal['room_state'], state)
                    else:
                        self.assertEqual(rejected, Counter(insufficient_room=1))

    def test_zero_range_zero_atr_and_gap_already_outside_level(self):
        flat = [replace(bar, open=100.2, high=100.2, low=100.2, close=100.2) for bar in bars(count=3)]
        self.assertEqual(detect_signals(flat, levels())[1], Counter(zero_range=1))
        self.assertEqual(detect_signals(bars(count=3), levels(atr=0))[1], Counter(invalid_atr=1))
        # Opening beyond yesterday's high is allowed; no cross within a bar is required.
        self.assertIsNotNone(detect_signals(bars(count=3, opening=100.05), levels())[0]['PD_BREAK'])


class SignalQualityTests(unittest.TestCase):
    def signal_and_rows(self):
        rows = bars()
        return detect_signals(rows, levels())[0]['PD_BREAK'], rows

    def test_exact_six_future_bars_and_reference_not_next_bar_price(self):
        signal, rows = self.signal_and_rows()
        rows[8] = replace(rows[8], high=100.8, close=100.7)
        out = evaluate_signal_quality(rows, signal)
        self.assertEqual(out['label_status'], 'complete')
        self.assertAlmostEqual(out['return_30m'], 100.7 / 100.2 - 1)
        self.assertAlmostEqual(out['return_atr'], .5 / 2)
        self.assertEqual(out['path_status'], 'neither')
        self.assertEqual(evaluate_signal_quality(rows[:9], signal), out)
        rows[9] = replace(rows[9], high=999, close=999)
        self.assertEqual(evaluate_signal_quality(rows, signal), out)

    def test_missing_or_bad_future_leaves_every_label_missing_without_mutating_signal(self):
        signal, rows = self.signal_and_rows()
        original = dict(signal)
        versions = [rows[:8], rows[:4] + rows[5:], rows[:4] + rows[3:4] + rows[4:],
                    rows[:3] + [rows[4], rows[3]] + rows[5:],
                    rows[:3] + [replace(rows[3], low=0)] + rows[4:],
                    rows[:3] + [replace(rows[3], code='US.QQQ')] + rows[4:]]
        for changed in versions:
            with self.subTest(size=len(changed)):
                out = evaluate_signal_quality(changed, signal)
                self.assertEqual(out['label_status'], 'missing_future')
                self.assertTrue(all(value is None for key, value in out.items() if key != 'label_status'))
                self.assertEqual(signal, original)

    def test_signal_bar_never_contributes_to_mfe_mae_or_first_touch(self):
        signal, rows = self.signal_and_rows()
        original = evaluate_signal_quality(rows, signal)
        rows[2] = replace(rows[2], high=1000, low=1)
        self.assertEqual(evaluate_signal_quality(rows, signal), original)
        self.assertAlmostEqual(original['mfe_r'], .05 / signal['risk'])
        self.assertAlmostEqual(original['mae_r'], .05 / signal['risk'])

    def test_first_touch_inclusive_and_same_bar_ambiguity_never_guessed(self):
        signal, rows = self.signal_and_rows()
        for hit, expected in [('target', 'target_first'), ('stop', 'stop_first'), ('both', 'ambiguous')]:
            with self.subTest(hit=hit):
                future = list(rows)
                future[3] = replace(future[3],
                                    high=signal['target'] if hit in ('target', 'both') else 100.3,
                                    low=signal['invalidation'] if hit in ('stop', 'both') else 100.1)
                future[4] = replace(future[4], high=signal['target'], low=signal['invalidation'])
                self.assertEqual(evaluate_signal_quality(future, signal)['path_status'], expected)

    def test_short_mirror_excursions_and_normalized_return(self):
        signal, rows = self.signal_and_rows()
        rows[3] = replace(rows[3], high=signal['target'])
        rows[8] = replace(rows[8], high=100.8, close=100.7)
        short = detect_signals(mirror(rows[:3]), mirror_levels(levels()))[0]['PD_BREAK']
        long_result = evaluate_signal_quality(rows, signal)
        short_result = evaluate_signal_quality(mirror(rows), short)
        for key in ('mfe_r', 'mae_r', 'return_atr'):
            self.assertAlmostEqual(long_result[key], short_result[key])
        self.assertEqual(short_result['path_status'], 'target_first')
        self.assertAlmostEqual(short_result['return_30m'], -(99.3 / 99.8 - 1))

    def test_unfavorable_path_has_zero_mfe_not_negative_excursion(self):
        signal, rows = self.signal_and_rows()
        future = rows[:3] + [replace(bar, open=100, high=100.1, low=99.9, close=100)
                             for bar in rows[3:]]
        result = evaluate_signal_quality(future, signal)
        self.assertEqual(result['mfe_r'], 0)
        self.assertGreater(result['mae_r'], 0)


if __name__ == '__main__':
    unittest.main()
