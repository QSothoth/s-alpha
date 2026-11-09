import unittest
import numpy as np
from studies.trader_replication.martin_continue_gf import same_day_stop


class StopPrecisionTest(unittest.TestCase):
    def test_both_interpretations_and_clear_crossings(self):
        self.assertEqual(same_day_stop(97.5, 97.5, True), (True, True))
        self.assertEqual(same_day_stop(97.5, 97.5, False), (False, True))
        self.assertEqual(same_day_stop(97.4, 97.5, False), (True, False))
        self.assertEqual(same_day_stop(97.6, 97.5, True), (False, False))

    def test_missing_price_is_never_treated_as_a_fill(self):
        with self.assertRaises(ValueError):
            same_day_stop(np.nan, 97.5, True)
        with self.assertRaises(ValueError):
            same_day_stop(97.4, 0., False)


if __name__ == '__main__':
    unittest.main()
