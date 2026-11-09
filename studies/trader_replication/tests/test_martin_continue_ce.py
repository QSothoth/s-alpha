import unittest

import numpy as np

from studies.trader_replication.martin_continue_ce import first_touch


class FirstTouchTests(unittest.TestCase):
    def test_cross_first_touch_missing_and_new_cross(self):
        e9 = np.array([9, 11, 11, 11, 9, 11, 11, 11, 9, 11, 11, 11], float)[:, None]
        e21 = np.full(e9.shape, 10.)
        low = np.array([9, 10, 10.5, 10, 9, 10, np.nan, 10, 9, 10, 12, 10])[:, None]
        flags = first_touch(e9, e21, low)[:, 0]
        self.assertEqual(np.flatnonzero(flags).tolist(), [2, 11])
        low[-1, 0] = 12
        changed = first_touch(e9, e21, low)[:, 0]
        np.testing.assert_array_equal(flags[:-1], changed[:-1])
        self.assertFalse(changed[-1])


if __name__ == '__main__':
    unittest.main()
