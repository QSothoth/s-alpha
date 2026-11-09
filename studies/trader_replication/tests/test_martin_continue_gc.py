import unittest
import numpy as np
from studies.trader_replication.martin_continue_gc import price_opportunity


class PriceOpportunityTest(unittest.TestCase):
    def make_arrays(self):
        a = [np.full(121, 100., dtype=np.float32) for _ in range(4)]
        a[1][:] = 101.
        a[2][:] = 99.
        return a

    def test_gap_priority_and_dual_touch_unknown(self):
        a = self.make_arrays()
        a[0][1], a[1][1], a[2][1], a[3][1] = 140., 141., 89., 100.
        self.assertEqual(price_opportunity(*a, 0, 90.), ('filled', 'gap_target', True))
        a[0][1] = 100.
        self.assertEqual(price_opportunity(*a, 0, 90.), ('filled', 'same_day_both', None))
        a[0][1], a[2][1] = 89., 88.
        self.assertEqual(price_opportunity(*a, 0, 90.), ('filled', 'gap_stop', False))

    def test_entry_cancel_and_precision_are_separate(self):
        a = self.make_arrays()
        self.assertEqual(price_opportunity(*a, 0, 101.), ('cancel', 'open_below_stop', False))
        self.assertEqual(price_opportunity(*a, 0, 100.), ('unknown', 'opening_precision', None))
        a[2][0] = 90.
        self.assertEqual(price_opportunity(*a, 0, 90.), ('filled', 'intraday_precision', None))

    def test_unmatured_and_missing_not_losses(self):
        a = self.make_arrays()
        self.assertEqual(price_opportunity(*(v[:10] for v in a), 0, 90.), ('filled', 'end_unmatured', None))
        a[1][1] = np.nan
        self.assertEqual(price_opportunity(*a, 0, 90.), ('filled', 'invalid_bar', None))


if __name__ == '__main__':
    unittest.main()
