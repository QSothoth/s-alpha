"""Synthetic fixtures only; checks P2 definitions, never market data."""
from datetime import date, timedelta
import json
from pathlib import Path
import tempfile
import unittest

from studies.us_0dte_picks import daily_k


def flat(n=260, price=100.0, volume=1000.0):
    """n quiet bars (range 2, alternating closes) on consecutive weekdays."""
    day, bars = date(2023, 1, 2), []
    while len(bars) < n:
        if day.weekday() < 5:
            close = price + (0.5 if len(bars) % 2 else -0.5)
            bars.append((day.isoformat(), price, price + 1, price - 1, close, volume, 1e7))
        day += timedelta(days=1)
    return bars


def replace(bars, index, o, h, low, c, volume=None):
    day, *_, v, turnover = bars[index]
    bars[index] = (day, o, h, low, c, v if volume is None else volume, turnover)


class SignalTests(unittest.TestCase):
    def test_nr7_needs_strictly_the_narrowest_of_seven(self):
        bars = flat()
        i = len(bars) - 1
        replace(bars, i - 1, 100, 100.4, 99.8, 100.1)
        self.assertEqual(daily_k.signals(bars, i, set())['K2_NR7'], daily_k.BOTH)
        replace(bars, i - 3, 100, 100.4, 99.8, 100.1)  # a tie inside the window
        self.assertNotIn('K2_NR7', daily_k.signals(bars, i, set()))

    def test_52_week_close_extremes_give_direction(self):
        bars = flat()
        i = len(bars) - 1
        replace(bars, i - 1, 100, 103, 99.5, 102.9)
        self.assertEqual(daily_k.signals(bars, i, set())['K3_52W'], daily_k.LONG)
        replace(bars, i - 1, 100, 100.5, 97, 97.1)
        self.assertEqual(daily_k.signals(bars, i, set())['K3_52W'], daily_k.SHORT)

    def test_thrust_needs_volume_range_and_close_location(self):
        bars = flat()
        i = len(bars) - 1
        replace(bars, i - 1, 100, 104, 99, 103.8, volume=2500)
        self.assertEqual(daily_k.signals(bars, i, set())['K4_THRUST'], daily_k.LONG)
        self.assertEqual(daily_k.signals(bars, i, set())['K4B_THRUST_ANY'], daily_k.BOTH)  # post-hoc twin
        replace(bars, i - 1, 100, 104, 99, 103.8, volume=1500)  # volume below 2x
        self.assertNotIn('K4_THRUST', daily_k.signals(bars, i, set()))
        replace(bars, i - 1, 103, 104, 99, 99.2, volume=2500)
        self.assertEqual(daily_k.signals(bars, i, set())['K4_THRUST'], daily_k.SHORT)

    def test_exhaustion_needs_three_down_closes_and_a_hammer(self):
        bars = flat()
        i = len(bars) - 1
        for k, close in ((4, 101), (3, 100.6), (2, 100.2)):
            replace(bars, i - k, 101, 101.5, 99.5, close)
        replace(bars, i - 1, 99.9, 100.1, 98, 100.0)  # lower shadow 1.9 of 2.1, close near the high
        self.assertEqual(daily_k.signals(bars, i, set())['K5_EXHAUST'], daily_k.LONG)
        replace(bars, i - 1, 99.9, 100.1, 98, 98.5)
        self.assertNotIn('K5_EXHAUST', daily_k.signals(bars, i, set()))

    def test_earnings_flag_uses_the_given_reaction_days(self):
        bars = flat()
        i = len(bars) - 1
        self.assertEqual(daily_k.signals(bars, i, {bars[i][0]})['K1_EARN'], daily_k.BOTH)


class EventTests(unittest.TestCase):
    def test_reaction_day_follows_release_timing(self):
        calendar = ['2024-07-30', '2024-07-31', '2024-08-01', '2024-08-02']
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'earnings').mkdir()
            rows = [{'pub_trading_day_str': '2024-07-30', 'pub_type': 'AFTER_MARKET'},
                    {'pub_trading_day_str': '2024-08-02', 'pub_type': 'PRE_MARKET'},
                    {'pub_trading_day_str': '2024-08-02', 'pub_type': 'AFTER_MARKET'},  # no next session: dropped
                    {'pub_trading_day_str': '2024-08-01', 'pub_type': 'None'}]
            (root / 'earnings' / 'X.json').write_text(json.dumps(rows))
            self.assertEqual(daily_k.reaction_days('X', calendar, root), {'2024-07-31', '2024-08-02'})

    def test_schedule_flags(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'expiry').mkdir()
            (root / 'expiry' / 'A.json').write_text(json.dumps(
                [{'strike_time': d} for d in ('2026-09-28', '2026-10-02', '2026-10-09')]))
            (root / 'expiry' / 'B.json').write_text(json.dumps([{'strike_time': '2026-10-16'}]))
            self.assertEqual(daily_k.schedule('A', root), (True, True))
            self.assertEqual(daily_k.schedule('B', root), (False, False))

    def test_outcomes_and_rows_compare_with_the_same_day_pool(self):
        records = [{'symbol': 'A', 'up': 1.2, 'dn': .3, 'oc': .5, 'signals': {'K3_52W': daily_k.LONG}},
                   {'symbol': 'B', 'up': .2, 'dn': 1.5, 'oc': -.9, 'signals': {}},
                   {'symbol': 'C', 'up': .4, 'dn': .4, 'oc': 0, 'signals': {}},
                   {'symbol': 'D', 'up': 1.1, 'dn': 1.1, 'oc': .1, 'signals': {'K3_52W': daily_k.SHORT}}]
        rows = daily_k.rows_for({'2024-01-05': records}, 'K3_52W', 1.0)
        self.assertEqual(rows[0][1:5], (True, False, .5, .5))   # long: up hit, dn miss vs pool up 2/4, dn 2/4
        self.assertEqual(rows[1][1:5], (True, True, .5, .5))
        self.assertAlmostEqual(daily_k.delta(rows), .5)
        self.assertAlmostEqual(daily_k.tilt(rows), .5)

    def test_validation_gate_needs_enough_picks(self):
        self.assertEqual(daily_k.validate_gates({'picks': 50}), {'picks>=100': False})


if __name__ == '__main__':
    unittest.main()
