import unittest

from studies.trader_replication.martin_continue_dp import opening_fill


class OpeningLimitTest(unittest.TestCase):
    def test_preexisting_sell_limit_marketable_at_open(self):
        status, fill, stop, day_exit = opening_fill(10.5, 11.1, 10., .05, True)
        self.assertEqual(status, 'marketable_open')
        self.assertEqual(fill, 10.5)
        self.assertGreaterEqual(fill, 10.)
        self.assertAlmostEqual(stop, 11.025)
        self.assertEqual(day_exit, stop)
        self.assertEqual(opening_fill(10.5, 11.1, 10., .05, False)[0], 'legacy_open_skipped')

    def test_below_limit_path_is_identical(self):
        for high in (9.9, 10.1, 10.6):
            self.assertEqual(opening_fill(9., high, 10., .05, True),
                             opening_fill(9., high, 10., .05, False))

    def test_missing_data_is_unknown(self):
        self.assertEqual(opening_fill(10., float('nan'), 9., .02, True)[0], 'unknown')
        self.assertEqual(opening_fill(10., 9., 9., .02, True)[0], 'unknown')


if __name__ == '__main__':
    unittest.main()
