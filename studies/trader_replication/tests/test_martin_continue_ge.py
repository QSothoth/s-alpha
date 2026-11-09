import unittest
import numpy as np
from studies.trader_replication.martin_continue_ge import post_exit_event


class PostExitTest(unittest.TestCase):
    def test_early_clear_hit_even_if_other_days_missing(self):
        prices = np.full(20, 90., dtype=np.float32)
        prices[0], prices[1] = np.nan, 101.
        self.assertEqual(post_exit_event(prices, 0, 100.), (True, 'observed'))

    def test_missing_or_unmatured_not_negative(self):
        self.assertEqual(post_exit_event(np.full(19, 90.), 0, 100.), (None, 'unmatured'))
        a = np.full(20, 90.)
        a[1] = np.nan
        self.assertEqual(post_exit_event(a, 0, 100.), (None, 'missing_high'))
        a[1] = 100.
        self.assertEqual(post_exit_event(a, 0, 100.), (None, 'target_precision'))
        a[1] = 99.
        self.assertEqual(post_exit_event(a, 0, 100.), (False, 'not_reached'))

    def test_exit_day_is_not_used(self):
        prices = np.full(21, 90.)
        prices[0] = 200.
        self.assertEqual(post_exit_event(prices, 1, 100.), (False, 'not_reached'))


if __name__ == '__main__':
    unittest.main()
