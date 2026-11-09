import unittest

import numpy as np

from studies.trader_replication.martin_continue_cg import lagged_fresh20, leader_stack
from studies.trader_replication.martin_list import ema


class FreshLeaderTests(unittest.TestCase):
    def test_chunked_stack_matches_original_full_formula(self):
        rng = np.random.default_rng(13)
        c = rng.uniform(10, 100, (40, 70))
        c[10, 1] = np.nan
        e9, e21, e50 = (ema(c, n) for n in (9, 21, 50))
        expected = (e9 > e21) & (e21 > e50) & (c > e21)
        stack, known = leader_stack(c)
        np.testing.assert_array_equal(stack, expected)
        self.assertFalse(known[10, 1])

    def test_prior_day_and_twenty_day_comparison_are_causal(self):
        stack = np.zeros((25, 2), bool)
        known = np.ones(stack.shape, bool)
        stack[20, :] = True
        known[0, 1] = False
        result = lagged_fresh20(stack, known)
        self.assertTrue(result[21, 0])
        self.assertFalse(result[21, 1])
        stack[21:] = True
        changed = lagged_fresh20(stack, known)
        np.testing.assert_array_equal(result[:22], changed[:22])


if __name__ == '__main__':
    unittest.main()
