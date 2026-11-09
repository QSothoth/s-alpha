import unittest

import numpy as np

from studies.trader_replication.martin_continue_do import choose_preopen, first_ready


class PreopenTest(unittest.TestCase):
    def test_entry_day_information_does_not_change_readiness(self):
        close = np.array([11., 9., 9., 9., 11., 9., 9.])[:, None]
        high = np.array([11., 11., 10., 10., 11., 11., 10.])[:, None]
        e50 = np.full_like(close, 10.)
        ready = first_ready(close, high, e50)
        self.assertEqual(np.flatnonzero(ready[:, 0]).tolist(), [2, 6])
        high[2, 0] = 9.5
        changed = first_ready(close, high, e50)
        np.testing.assert_array_equal(ready[:3], changed[:3])
        self.assertTrue(changed[3, 0])
        close[2, 0] = 12.
        high[2, 0] = 15.
        e50[2, 0] = 11.
        changed = first_ready(close, high, e50)
        np.testing.assert_array_equal(ready[:3], changed[:3])

    def test_missing_bar_clears_wait_after_not_before_it(self):
        close = np.array([11., 9., 9., 9., 11., 9., 9.])[:, None]
        high = np.array([11., 11., np.nan, 10., 11., 11., 10.])[:, None]
        ready = first_ready(close, high, np.full_like(close, 10.))
        self.assertTrue(ready[2, 0])
        self.assertFalse(ready[3, 0])
        self.assertTrue(ready[6, 0])

    def test_previous_turnover_selects_one_and_original_wins_exact_tie(self):
        original = np.array([[0, 0], [1, 1], [0, 0]], dtype=bool)
        alternate = np.array([[0, 0], [1, 0], [0, 0]], dtype=bool)
        turnover = np.array([[100., 80.], [1., 1000.], [1., 1.]])
        z, f = choose_preopen(original, alternate, turnover)
        self.assertTrue(z[1, 0])
        self.assertFalse(f.any())
        turnover[1] = [10000., 0.]
        z2, f2 = choose_preopen(original, alternate, turnover)
        np.testing.assert_array_equal(z, z2)
        np.testing.assert_array_equal(f, f2)


if __name__ == '__main__':
    unittest.main()
