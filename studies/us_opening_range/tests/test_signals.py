import unittest
from dataclasses import replace
from datetime import datetime, timedelta

from custody.marketdata import Bar
from custody.models import ET, Session
from studies.us_opening_range.signals import CANDIDATES, Signal, exit_signal, find_signal, opening_range


OPEN = datetime(2026, 9, 25, 9, 30, tzinfo=ET)
SESSION = Session('2026-09-25', OPEN, OPEN.replace(hour=16, minute=0))


def append_bars(bars, count, close=100, high=None, low=None, volume=10):
    for _ in range(count):
        bars.append(Bar('US.SPY', OPEN + timedelta(minutes=len(bars) + 1), close,
                        close if high is None else high, close if low is None else low,
                        close, volume))
    return bars


def breakout(minutes=15):
    bars = append_bars([], minutes, high=101, low=99)
    return append_bars(bars, 5, close=101.4, low=100.8)


def mirror(bars):
    return [replace(bar, open=200-bar.open, high=200-bar.low, low=200-bar.high,
                    close=200-bar.close) for bar in bars]


class SignalTests(unittest.TestCase):
    def test_fixed_candidates_and_completed_five_minute_confirmation(self):
        self.assertEqual(list(CANDIDATES), ['OR15_breakout', 'OR15_retest',
                                          'OR30_breakout', 'OR30_retest'])
        for minutes in (15, 30):
            with self.subTest(minutes=minutes):
                bars = breakout(minutes)
                candidate = f'OR{minutes}_breakout'
                self.assertIsNone(opening_range(bars[:minutes-1], SESSION, minutes))
                self.assertEqual(opening_range(bars, SESSION, minutes), (101, 99))
                for count in range(minutes, minutes + 5):
                    self.assertIsNone(find_signal(bars[:count], SESSION, candidate))
                signal = find_signal(iter(bars), SESSION, candidate)
                self.assertEqual(signal.time, OPEN + timedelta(minutes=minutes + 5))
                self.assertEqual((signal.range_high, signal.range_low, signal.stop), (101, 99, 100))
                self.assertAlmostEqual(signal.target, 104.2)

    def test_intrabar_breakout_is_not_a_completed_five_minute_breakout(self):
        bars = breakout()
        bars[-1] = replace(bars[-1], open=100, low=100, close=100)
        self.assertIsNone(find_signal(bars, SESSION, 'OR15_breakout'))

    def test_future_does_not_change_or_retract_signal(self):
        bars = breakout()
        expected = find_signal(bars, SESSION, 'OR15_breakout')
        append_bars(bars, 40, close=50)
        self.assertEqual(find_signal(bars, SESSION, 'OR15_breakout'), expected)

        def prefix_then_unavailable_future():
            yield from bars[:20]
            raise AssertionError('a signal must not inspect future observations')

        self.assertEqual(find_signal(prefix_then_unavailable_future(), SESSION,
                                     'OR15_breakout'), expected)

    def test_retest_requires_a_later_complete_block_and_is_symmetric(self):
        for minutes in (15, 30):
            for reflected in (False, True):
                with self.subTest(minutes=minutes, reflected=reflected):
                    bars = breakout(minutes)
                    candidate = f'OR{minutes}_retest'
                    self.assertIsNone(find_signal(mirror(bars) if reflected else bars, SESSION, candidate))
                    append_bars(bars, 4, close=101.2, low=100.9)
                    self.assertIsNone(find_signal(mirror(bars) if reflected else bars, SESSION, candidate))
                    append_bars(bars, 1, close=101.2, low=101.1)
                    signal = find_signal(mirror(bars) if reflected else bars, SESSION, candidate)
                    self.assertEqual(signal.time, OPEN + timedelta(minutes=minutes + 10))
                    self.assertEqual(signal.direction, 'SHORT' if reflected else 'LONG')
                    self.assertAlmostEqual(signal.target, 96.4 if reflected else 103.6)

    def test_return_inside_cancels_retest_until_another_breakout(self):
        bars = breakout()
        append_bars(bars, 5, close=100.9)
        append_bars(bars, 5, close=101.2, low=100.9)
        self.assertIsNone(find_signal(bars, SESSION, 'OR15_retest'))
        append_bars(bars, 5, close=101.2, low=100.9)
        self.assertEqual(find_signal(bars, SESSION, 'OR15_retest').time, OPEN.replace(hour=10, minute=5))

    def test_no_chasing_flat_range_zero_volume_or_wrong_vwap(self):
        chased = append_bars([], 15, high=101, low=99)
        append_bars(chased, 5, close=101.6)
        flat = append_bars([], 15)
        append_bars(flat, 5, close=100.1)
        wrong_vwap = append_bars([], 15, high=101, low=99)
        append_bars(wrong_vwap, 5, close=101.2, high=110, volume=1000)
        for bars in (chased, flat, [replace(bar, volume=0) for bar in breakout()], wrong_vwap):
            with self.subTest(bars=bars[-1]):
                self.assertIsNone(find_signal(bars, SESSION, 'OR15_breakout'))
                self.assertIsNone(find_signal(mirror(bars), SESSION, 'OR15_breakout'))

    def test_deadline_is_exclusive(self):
        bars = append_bars([], 15, high=101, low=99)
        append_bars(bars, 70)
        append_bars(bars, 5, close=101.2)
        self.assertIsNone(find_signal(bars, SESSION, 'OR15_breakout'))

    def test_missing_duplicate_unsorted_nonpositive_or_mixed_minutes_are_rejected(self):
        bars = breakout()
        bad_inputs = [bars[1:], bars[:5] + bars[6:], bars[:5] + bars[4:]]
        bad_inputs.append([bars[1], bars[0]] + bars[2:])
        bad_inputs.append([replace(bars[0], open=0, low=0)] + bars[1:])
        bad_inputs.append([replace(bars[0], interval='5m')] + bars[1:])
        bad_inputs.append(bars[:1] + [replace(bars[1], code='US.QQQ')] + bars[2:])
        for invalid in bad_inputs:
            with self.subTest(first=invalid[0]):
                with self.assertRaises(ValueError):
                    find_signal(invalid, SESSION, 'OR15_breakout')

    def test_exit_checks_later_closes_not_highs_or_lows(self):
        for reflected in (False, True):
            bars = breakout()
            signal = find_signal(mirror(bars) if reflected else bars, SESSION, 'OR15_breakout')
            append_bars(bars, 1, close=101, high=110, low=90)
            data = mirror(bars) if reflected else bars
            self.assertIsNone(exit_signal(data, SESSION, signal))
            append_bars(bars, 1, close=100)
            data = mirror(bars) if reflected else bars
            self.assertEqual(exit_signal(data, SESSION, signal), (bars[-1].close_time, 'stop'))
            bars[-1] = replace(bars[-1], open=105, high=105, low=105, close=105)
            data = mirror(bars) if reflected else bars
            self.assertEqual(exit_signal(data, SESSION, signal), (bars[-1].close_time, 'target'))

    def test_timeout_and_early_close_flatten(self):
        bars = breakout()
        signal = find_signal(bars, SESSION, 'OR15_breakout')
        append_bars(bars, 59, close=101)
        self.assertIsNone(exit_signal(bars, SESSION, signal))
        append_bars(bars, 1, close=101)
        self.assertEqual(exit_signal(bars, SESSION, signal), (OPEN.replace(hour=10, minute=50), 'timeout'))
        early = Session(SESSION.day, SESSION.opens, OPEN.replace(hour=13, minute=0))
        late_signal = Signal('LONG', OPEN.replace(hour=12, minute=30), 101.4, 101, 99, 100, 104.2)
        bars = append_bars([], 195, close=101)
        self.assertEqual(exit_signal(bars, early, late_signal), (OPEN.replace(hour=12, minute=45), 'flatten'))
        self.assertIsNone(exit_signal(bars, SESSION, late_signal))


if __name__ == '__main__':
    unittest.main()
