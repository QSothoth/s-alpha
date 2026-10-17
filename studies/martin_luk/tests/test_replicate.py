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
