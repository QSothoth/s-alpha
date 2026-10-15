"""PB24 chip helpers: causal cost line, turnover, profit ratio."""
import unittest

import numpy as np

from studies.trend_breakout import chips


class Chips(unittest.TestCase):
    def test_cost_line_moves_by_turnover_share_and_skips_gaps(self):
        close = np.array([[10.], [12.], [np.nan], [12.]])
        price = np.array([[10.], [12.], [np.nan], [14.]])
        h = np.array([[.1], [.5], [np.nan], [.25]])
        cost = chips.cost_line(close, price, h)[:, 0]
        self.assertEqual(cost[0], 10)
        self.assertAlmostEqual(cost[1], 11)
        self.assertAlmostEqual(cost[2], 11)
        self.assertAlmostEqual(cost[3], .75 * 11 + .25 * 14)

    def test_cost_line_is_causal(self):
        rng = np.random.default_rng(0)
        close = 10 + rng.random((50, 3))
        h = rng.random((50, 3)) * .1
        a = chips.cost_line(close, close, h)
        close2 = close.copy()
        close2[30:] = 99
        b = chips.cost_line(close2, close2, h)
        np.testing.assert_array_equal(a[:30], b[:30])

    def test_profit_ratio_bounds(self):
        high = np.array([[10.], [20.], [20.]])
        low = np.array([[10.], [20.], [20.]])
        h = np.array([[1.], [.5], [0.]])
        close = np.array([[10.], [20.], [10.]])
        pr = chips.profit_ratio(high, low, close, h, rows=[1, 2])[:, 0]
        self.assertAlmostEqual(pr[0], 1., places=5)   # every chip at or below 20
        self.assertAlmostEqual(pr[1], .5, places=5)   # half the chips were bought at 20, above a close of 10

    def test_turnover_uses_total_shares(self):
        p = {'mktcap': np.array([[1000.]]), 'raw_close': np.array([[10.]]), 'volume': np.array([[5.]])}
        self.assertAlmostEqual(chips.turnover_rate(p)[0, 0], .05)


if __name__ == '__main__':
    unittest.main()
