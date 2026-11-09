import math
import unittest

from studies.trader_replication.martin_continue_dw import raw_position


class RawPositionTests(unittest.TestCase):
    def test_midpoint_and_uniform_scale(self):
        self.assertEqual(raw_position([10, 12, 8, 10, 100, 1000]), .5)
        self.assertEqual(raw_position([20, 24, 16, 20, 100, 1000]), .5)

    def test_widens_invalid_high_low_like_standard_panel(self):
        self.assertEqual(raw_position([10, 9, 8, 12, 100, 1000]), 1.)

    def test_missing_or_zero_range_are_unknown(self):
        self.assertTrue(math.isnan(raw_position([10, 10, 10, 10, 0, 0])))
        self.assertTrue(math.isnan(raw_position([float('nan'), 11, 9, 10, 1, 1])))


if __name__ == '__main__':
    unittest.main()
