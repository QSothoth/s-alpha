import unittest

import numpy as np

from studies.martin_luk import luk, replicate
from studies.trader_replication.martin_continue_ci import higher_low, prefer_higher_low


class HigherLowTests(unittest.TestCase):
    def test_streamed_condition_matches_r50_and_ignores_future(self):
        rng = np.random.default_rng(41)
        lows = rng.uniform(10, 100, (45, 8))
        lows[0:16, 0] = np.nan
        lows[5, 2] = np.nan
        recent = replicate.prior_low(lows, 5)
        older = luk.lag(replicate.prior_low(lows, 15), 5)
        states = higher_low(lows)
        np.testing.assert_array_equal(states == 1, recent > older)
        np.testing.assert_array_equal(states == -1, np.isnan(recent) | np.isnan(older))
        changed = lows.copy()
        changed[30:] = 1e6
        np.testing.assert_array_equal(states[:31], higher_low(changed)[:31])

    def test_priority_preserves_signals_and_original_order_within_groups(self):
        book = [[((1., -.8), 0, 1, 10., 9., 'list'), ((1., -.5), 1, 1, 11., 10., 'list'),
                 ((1., -.7), 2, 1, 12., 11., 'list')]]
        states = np.array([[-1, 1, 0]])
        changed = prefer_higher_low(book, states)
        self.assertEqual([e[1] for e in sorted(changed[0])], [1, 0, 2])
        self.assertEqual([e[1:] for e in changed[0]], [e[1:] for e in book[0]])


if __name__ == '__main__':
    unittest.main()
