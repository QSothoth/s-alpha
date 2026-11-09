import unittest

import numpy as np

from studies.trader_replication.martin_continue_db import anchored_levels


def sample():
    cols = [
        [10., 11., 11.4, 11.7, 13., 13.5],
        [10.5, 12., 12., 12., 14., 14.],
        [9.5, 10.8, 11., 11., 12.9, 13.],
        [10., 11.5, 11.7, 11.8, 13.5, 13.7],
        [100., 100., 200., 0., 100., 100.],
        [1000., 1140., 2300., 0., 1350., 1360.],
    ]
    return [np.array(x, dtype=float)[:, None] for x in cols]


class GapAnchoredVwapTests(unittest.TestCase):
    def test_only_completed_gap_and_valid_bars_contribute(self):
        arrays = sample()
        levels, valid, gaps = anchored_levels(*arrays)
        self.assertTrue(np.isnan(levels[1, 0]))
        self.assertAlmostEqual(float(levels[2, 0]), 11.4, places=5)
        self.assertAlmostEqual(float(levels[3, 0]), 3440 / 300, places=5)
        self.assertFalse(valid[3, 0])
        self.assertTrue(np.isnan(levels[4, 0]))
        self.assertTrue(gaps[1, 0])
        self.assertTrue(gaps[4, 0])
        self.assertAlmostEqual(float(levels[5, 0]), 13.5, places=5)
        arrays[5][3:] = 1
        levels2, _, _ = anchored_levels(*arrays)
        np.testing.assert_array_equal(levels[:4], levels2[:4])

    def test_consistent_reanchoring_scales_price_without_changing_validity(self):
        arrays = sample()
        original, valid, gaps = anchored_levels(*arrays)
        scaled = [a.copy() for a in arrays]
        for a in scaled[:4]:
            a *= 2
        scaled[4] /= 2
        result, valid2, gaps2 = anchored_levels(*scaled)
        np.testing.assert_allclose(result, original * 2, equal_nan=True)
        np.testing.assert_array_equal(valid2, valid)
        np.testing.assert_array_equal(gaps2, gaps)

    def test_out_of_range_turnover_invalidates_the_anchor(self):
        arrays = sample()
        arrays[5][2] = 100000
        levels, valid, _ = anchored_levels(*arrays)
        self.assertFalse(valid[2, 0])
        self.assertTrue(np.isnan(levels[3, 0]))


if __name__ == '__main__':
    unittest.main()
