"""Timing tests for the replication stages: weekly EMA as charted mid-week, 5-minute triggers, previous-day masks."""
import unittest

import numpy as np

from studies.martin_luk import replicate as R
from studies.martin_luk.intraday import NB


def bars(rows):
    """rows: (open, high, low) for the first bars of a day; the rest are NaN."""
    o5, h5, l5 = (np.full(NB, np.nan) for _ in range(3))
    for b, (o, h, l) in enumerate(rows):
        o5[b], h5[b], l5[b] = o, h, l
    return o5, h5, l5


class TriggerTests(unittest.TestCase):
    def test_pdh_break_fills_at_the_prior_high_with_low_of_day_so_far(self):
        o5, h5, l5 = bars([(10.0, 10.2, 9.8), (10.1, 10.6, 10.0), (10.5, 10.9, 10.4)])
        self.assertEqual(R.first_trigger(o5, h5, l5, 'E2', pdh=10.5, e9p=9.0), (1, 10.5, 9.8))

    def test_open_above_the_prior_high_waits_for_the_first_bar_high(self):
        o5, h5, l5 = bars([(11.0, 11.2, 10.8), (11.1, 11.1, 10.7), (11.0, 11.4, 10.9)])
        self.assertEqual(R.first_trigger(o5, h5, l5, 'E2', pdh=10.5, e9p=9.0), (2, 11.2, 10.7))

    def test_pullback_needs_a_dip_then_a_break_of_the_previous_bar_high(self):
        o5, h5, l5 = bars([(10.0, 10.1, 9.6), (9.7, 9.8, 9.4), (9.5, 9.7, 9.45), (9.7, 9.9, 9.6)])
        # dip below e9 = 9.5 on bar 1; bar 2 does not exceed bar 1's high; bar 3 does
        self.assertEqual(R.first_trigger(o5, h5, l5, 'E4', pdh=11.0, e9p=9.5), (3, 9.7, 9.4))

    def test_handshake_dips_to_the_higher_of_prior_high_and_ema9(self):
        o5, h5, l5 = bars([(11.0, 11.2, 10.6), (10.6, 10.7, 10.45), (10.5, 10.8, 10.5)])
        # gap above the prior high 10.5 (EMA9 9.8): the fade to 10.45 counts, bar 2 breaks bar 1's high
        self.assertEqual(R.first_trigger(o5, h5, l5, 'E11', pdh=10.5, e9p=9.8), (2, 10.7, 10.45))
        self.assertIsNone(R.first_trigger(o5, h5, l5, 'E4', pdh=10.5, e9p=9.8))

    def test_skipping_the_first_bars_moves_the_trigger_but_not_the_low_of_day(self):
        rows = [(10.0, 10.6, 9.8)] + [(10.4, 10.5, 10.3)] * 5 + [(10.4, 10.7, 10.35)]
        o5, h5, l5 = bars(rows)
        self.assertEqual(R.first_trigger(o5, h5, l5, 'E2', pdh=10.5, e9p=9.0), (0, 10.5, 9.8))
        self.assertEqual(R.first_trigger(o5, h5, l5, 'E2', pdh=10.5, e9p=9.0, b_start=6), (6, 10.5, 9.8))

    def test_no_trigger_returns_none(self):
        o5, h5, l5 = bars([(10.0, 10.2, 9.9), (10.1, 10.3, 10.0)])
        self.assertIsNone(R.first_trigger(o5, h5, l5, 'E2', pdh=10.5, e9p=9.0))


def tiny(rows, adr=8.0, to20=100e6, turnover=None):
    """A one-stock panel: rows of (open, high, low, close)."""
    a = np.array(rows, float)
    T = len(a)
    A = {k: a[:, i:i + 1] for i, k in enumerate(('open', 'high', 'low', 'close'))}
    A['adr'] = np.full((T, 1), adr)
    A['to20'] = np.full((T, 1), to20)
    A['turnover'] = np.full((T, 1), to20) if turnover is None else np.array(turnover, float)[:, None]
    return A


class EntryTests(unittest.TestCase):
    def test_close_entry_stop_modes(self):
        # cap = min(5%, 0.5 x 8%) = 4%; the day ran from 9.0 to close 10.0, so the low is 10% away
        A = tiny([(9.5, 9.6, 9.4, 9.5), (9.0, 10.1, 9.0, 10.0)])
        m = np.array([[False], [True]])
        self.assertEqual(R.entries_close_stop(A, m, 'skip'), [[], []])
        (e,) = R.entries_close_stop(A, m, 'cap')[1]
        self.assertAlmostEqual(e[4], 9.6)                 # stop moved up to close x (1 - 4%)
        (e,) = R.entries_close_stop(A, m, 'half')[1]
        self.assertAlmostEqual(e[4], 9.8)
        B = tiny([(9.5, 9.6, 9.4, 9.5), (9.8, 10.1, 9.8, 10.0)])   # low 2% away: the low itself
        (e,) = R.entries_close_stop(B, m, 'cap')[1]
        self.assertAlmostEqual(e[4], 9.8)

    def test_short_stop_is_capped_and_can_be_sized_down(self):
        A = tiny([(10, 10, 10, 10), (11.0, 11.0, 9.9, 10.0)])      # high 10% above the close; cap 4%
        m = np.array([[False], [True]])
        (e,) = R.entries_short_capped(A, m)[1]
        self.assertEqual(e[2], -1)
        self.assertAlmostEqual(e[4], 10.4)
        self.assertIsNone(e[7])
        (e,) = R.entries_short_capped(A, m, size_mult=2.0)[1]
        self.assertAlmostEqual(e[7], .08)                           # sized as if the stop were twice as far

    def test_ep_needs_gap_volume_and_holding_the_open(self):
        rows = [(10, 10, 10, 10), (11.0, 11.5, 10.8, 11.2), (10.2, 10.3, 10.0, 10.1), (11.5, 11.6, 10.9, 11.0)]
        A = tiny(rows, adr=4.0, to20=100e6, turnover=[1e8, 3e8, 1e8, 3e8])
        pool = np.ones((4, 1), bool)
        # day 1: gap 10% >= 5%, volume 3x, close >= open -> EP; day 3: gap from 10.1 to 11.5 but closes below the open
        self.assertEqual(R.ep_signal(A, pool)[:, 0].tolist(), [False, True, False, False])


class RotationTests(unittest.TestCase):
    def test_rotation_only_uses_finished_outcomes(self):
        # rising prices; with lag 2 and lookback 3, day d looks at signals from days d-4 .. d-2
        c = np.array([[10.0], [10.5], [11.0], [11.5], [12.0], [12.5], [13.0]])
        A = {'close': c}
        y = np.zeros((7, 1), bool)
        x = np.zeros((7, 1), bool)
        x[[0, 6], 0] = True
        keep = R.rotate(A, {'X': x, 'Y': y}, lookback=3, lag=2)
        self.assertFalse(keep[6, 0])      # day 0 is outside days 2..4: no feedback, family off
        x[5, 0] = True                    # day 5's outcome needs day 7's close: not usable on day 6
        self.assertFalse(R.rotate(A, {'X': x, 'Y': y}, lookback=3, lag=2)[6, 0])
        x[3, 0] = True                    # day 3's outcome uses day 5's close: usable on day 6
        self.assertTrue(R.rotate(A, {'X': x, 'Y': y}, lookback=3, lag=2)[6, 0])


class MaskTests(unittest.TestCase):
    def test_prev_shifts_one_day(self):
        x = np.array([[True], [False], [True]])
        self.assertEqual(R.prev(x)[:, 0].tolist(), [False, True, False])

    def test_weekly_ema_uses_completed_weeks_plus_the_running_close(self):
        days = np.array(['2025-01-06', '2025-01-07', '2025-01-13', '2025-01-14'])     # Mon, Tue, Mon, Tue
        c = np.array([[10.0], [12.0], [14.0], [16.0]])
        e = R.weekly_ema(c, days, 3)                                                   # alpha = 0.5
        self.assertEqual(e[:, 0].tolist(), [10.0, 12.0, .5 * 14 + .5 * 12, .5 * 16 + .5 * 12])


if __name__ == '__main__':
    unittest.main()
