import unittest

import numpy as np

from studies.trader_replication.martin_continue_n import peer_flags


class PeerFlags(unittest.TestCase):
    def test_only_rising_correlated_leaders_count_toward_second_flag(self):
        x = np.arange(40, dtype=float)
        candidates = np.column_stack((x, -x))
        leaders = np.column_stack((x, x * 2))
        one, two = peer_flags(candidates, leaders, np.array([True, True]))
        np.testing.assert_array_equal(one, [True, False])
        np.testing.assert_array_equal(two, [True, False])
        _, two = peer_flags(candidates, leaders, np.array([True, False]))
        self.assertFalse(two.any())

    def test_no_leaders_produces_no_flags(self):
        one, two = peer_flags(np.ones((40, 2)), np.empty((40, 0)), np.empty(0, bool))
        self.assertFalse(one.any())
        self.assertFalse(two.any())


if __name__ == '__main__':
    unittest.main()
