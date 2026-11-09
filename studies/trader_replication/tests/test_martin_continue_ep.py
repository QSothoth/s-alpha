import math
import unittest
from studies.trader_replication.martin_continue_ep import raw_ranges


class RawRangeTests(unittest.TestCase):
    def test_uniform_price_scaling_keeps_intraday_range(self):
        self.assertAlmostEqual(raw_ranges([10, 11, 9, 10]), raw_ranges([20, 22, 18, 20]))

    def test_widens_high_low_and_preserves_invalid_as_missing(self):
        self.assertAlmostEqual(raw_ranges([10, 9, 8, 12]), .5)
        self.assertTrue(math.isnan(raw_ranges([10, 11, 0, 10])))


if __name__ == '__main__':
    unittest.main()
