"""Synthetic checks for exit-resolution aggregation; no market data loaded."""
import unittest

from studies.us_0dte_picks import p3, resolution
from studies.us_0dte_picks.tests.test_p3 import bars


class ResolutionTests(unittest.TestCase):
    def test_aggregation_preserves_entry_and_stop_first_in_both_directions(self):
        for side in (1, -1):
            with self.subTest(side=side):
                path = bars({2: (105, 95, 100), 6: (101.2, 100, 100), 7: (100, 98.8, 100)}
                            if side == 1 else {2: (105, 95, 100), 6: (100, 98.8, 100), 7: (101.2, 100, 100)})
                coarse = resolution.aggregate30(path)
                self.assertEqual(len(coarse), 13)
                self.assertEqual(coarse[0], ('10:00:00', *p3.daily_bar(path[:6])))
                self.assertEqual(p3.first_touch(path, 100, .01, side)[:3], (1.0, True, False))
                result = resolution.coarse_outcome(path, 100, .01, side)
                self.assertEqual(result[:3], (-.5, False, True))
                self.assertEqual(p3.GRID[result[4]], '10:30:00')
        quiet = bars({2: (105, 95, 100), 77: (100.3, 100, 100.2)})
        self.assertEqual(resolution.coarse_outcome(quiet, 100, .01, 1)[:3],
                         p3.first_touch(quiet, 100, .01, 1)[:3])
        with self.assertRaises(ValueError):
            resolution.aggregate30(quiet[:-1])


if __name__ == '__main__':
    unittest.main()
