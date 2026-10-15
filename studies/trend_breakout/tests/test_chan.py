"""PB16 weekly bars and the simplified, causal Chan structure."""
import unittest

import numpy as np

from studies.trend_breakout import chan
from studies.trend_breakout.tests.test_portfolio import sample


def zigzag(turns, step=1.):
    """Weekly highs/lows walking linearly through the turning mid prices, one bar per unit step."""
    mids = [turns[0]]
    for a, b in zip(turns, turns[1:]):
        n = int(round(abs(b - a) / step))
        mids += list(np.linspace(a, b, n + 1)[1:])
    mids = np.array(mids)
    return mids + .5, mids - .5


class Structure(unittest.TestCase):
    def test_third_buy_after_pullback_above_pivot(self):
        high, low = zigzag([15, 20, 10, 18, 12, 25, 20, 23])
        buy3, stop3, buy2, _, cap, support = chan.chan_stock(high, low)
        w = int(np.flatnonzero(buy3)[0])
        self.assertEqual(np.flatnonzero(buy3).tolist(), [w])
        self.assertAlmostEqual(low[w - 1], 19.5)  # the pullback low, confirmed one week later
        self.assertAlmostEqual(stop3[w], 18.5)   # ZG = lower of the two pivot tops
        self.assertAlmostEqual(cap[w], 25.5)     # the previous top
        self.assertAlmostEqual(support[w], 11.5)  # last confirmed bottom before the pullback
        self.assertFalse(buy2[w])

    def test_signal_reports_stroke_weeks_and_pullback_low(self):
        high, low = zigzag([15, 20, 10, 18, 12, 25, 20, 23])
        out = chan.chan_stock(high, low, weeks=True)
        w = int(np.flatnonzero(out[0])[0])
        w_low, w_top, w_bottom, bottom = (x[w] for x in out[6:])
        self.assertAlmostEqual(low[w_low], 11.5)
        self.assertAlmostEqual(high[w_top], 25.5)
        self.assertAlmostEqual(low[w_bottom], 19.5)
        self.assertAlmostEqual(bottom, 19.5)
        for a, b in zip(out[:6], chan.chan_stock(high, low)):
            np.testing.assert_array_equal(a, b)

    def test_no_third_buy_when_pullback_reenters_pivot(self):
        high, low = zigzag([15, 20, 10, 18, 12, 25, 16, 23])
        self.assertFalse(chan.chan_stock(high, low)[0].any())

    def test_second_buy_is_a_higher_low_after_a_52_week_low(self):
        high, low = zigzag([30, 10, 16, 11, 18])
        _, _, buy2, stop2, cap, _ = chan.chan_stock(high, low)
        w = int(np.flatnonzero(buy2)[0])
        self.assertAlmostEqual(low[w - 1], 10.5)
        self.assertAlmostEqual(stop2[w], 9.5)
        self.assertAlmostEqual(cap[w], 16.5)

    def test_outputs_never_use_later_weeks(self):
        rng = np.random.default_rng(5)
        mid = 20 + np.cumsum(rng.normal(0, 1, 160))
        high, low = mid + rng.uniform(.2, 1, 160), mid - rng.uniform(.2, 1, 160)
        full = chan.chan_stock(high, low)
        for cut in (40, 90, 130):
            part = chan.chan_stock(high[:cut], low[:cut])
            for a, b in zip(full, part):
                np.testing.assert_array_equal(a[:cut], b)

    def test_inclusion_merges_inside_bars(self):
        high = np.array([10, 12, 11.5, 13, 12, 11, 10, 9, 10, 11])
        low = np.array([9, 11, 11.2, 12, 11, 10, 9, 8, 9, 10])
        # Bar 2 lies inside bar 1 and is merged upward, so the top is bar 3 and not a spurious fractal at bar 1.
        support = chan.chan_stock(high, low)[5]
        self.assertTrue(np.isnan(support).all())

    def test_suspended_weeks_are_skipped(self):
        high, low = zigzag([15, 20, 10, 18, 12, 25, 20, 23])
        h, l = np.insert(high, 12, np.nan), np.insert(low, 12, np.nan)
        a, b = chan.chan_stock(high, low)[0], chan.chan_stock(h, l)[0]
        self.assertEqual(a.sum(), b.sum())


class Weekly(unittest.TestCase):
    def test_weekly_bars_from_daily(self):
        p = sample([[10, 1], [11, 2], [12, 3], [9, np.nan], [10, 5], [13, 6], [14, 7]])
        p['dates'] = np.array(['2024-01-04', '2024-01-05', '2024-01-08', '2024-01-09', '2024-01-10',
                               '2024-01-15', '2024-01-16'])
        p['high'][3, 0] = 15
        w = chan.weekly(p)
        self.assertEqual(w['dates'].tolist(), ['2024-01-05', '2024-01-10', '2024-01-16'])
        self.assertEqual(w['open'][1].tolist(), [12, 3])
        self.assertEqual(w['close'][1].tolist(), [10, 5])
        self.assertEqual(w['high'][1, 0], 15)
        self.assertEqual(w['low'][1, 0], 9)
        self.assertEqual(w['first'].tolist(), [0, 2, 5])


class MarketExit(unittest.TestCase):
    def test_market_exit_sells_at_the_next_open_after_the_down_close(self):
        from studies.trend_breakout import backtest
        p = sample([10, 10, 11, 12, 13, 14])
        entry = np.zeros((6, 1), bool)
        entry[0] = True
        down = np.array([False, False, True, False, False, False])
        a = chan.PullbackAccount(p, np.ones((6, 1)), (0, 0), np.full((6, 1), np.inf))
        backtest.run(p, entry, np.full((6, 1), 5.), True, np.ones((6, 1), bool), np.ones((6, 1)), 1, 5, (0, 0),
                     account=a, exit_rows=down)
        self.assertEqual(a.trades[0]['exit'], 3)  # down at row 2's close -> sold at row 3's open


class Pullback(unittest.TestCase):
    def test_open_at_or_above_previous_top_is_skipped(self):
        p = sample([[10, 10], [10, 10]])
        cap = np.array([[12., 9.], [np.nan, np.nan]])
        a = chan.PullbackAccount(p, np.ones((2, 2)), (0, 0), cap)
        got = a.allocate(1, np.array([True, True]), np.array([10., 10.]), np.array([8., 8.]),
                         np.array([1., 1.]), np.array([0, 0]))
        self.assertEqual(got.tolist(), [True, False])
        self.assertEqual(a.chased, 1)
        self.assertAlmostEqual(a.positions[0]['qty'] * 10, .1)


if __name__ == '__main__':
    unittest.main()
