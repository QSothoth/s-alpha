import unittest

import numpy as np

from studies.trader_replication.martin_continue_di import select_spaced


class SpacingTest(unittest.TestCase):
    def test_spacing_is_per_stock_and_only_uses_preceding_selections(self):
        last = np.full(3, -100, dtype=int)
        np.testing.assert_array_equal(select_spaced(5, np.array([0, 1]), last), [0, 1])
        np.testing.assert_array_equal(select_spaced(25, np.array([0, 2]), last), [2])
        np.testing.assert_array_equal(select_spaced(26, np.array([0, 1, 2]), last), [0, 1])
        np.testing.assert_array_equal(last, [26, 26, 25])

    def test_episode_does_not_reset_when_classification_changes(self):
        last = np.full(1, -100, dtype=int)
        self.assertEqual(len(select_spaced(1, np.array([0]), last)), 1)
        self.assertEqual(len(select_spaced(2, np.array([0]), last)), 0)
        self.assertEqual(len(select_spaced(22, np.array([0]), last)), 1)


if __name__ == '__main__':
    unittest.main()
