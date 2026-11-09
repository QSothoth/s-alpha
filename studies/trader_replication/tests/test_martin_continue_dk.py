import unittest

import numpy as np

from studies.trader_replication.martin_continue_dk import next_open_outcome, strong_close


class PriorSignalTest(unittest.TestCase):
    def test_signal_close_position_and_invalid_bar(self):
        self.assertTrue(strong_close(10., 20., 10., 17.))
        self.assertFalse(strong_close(10., 20., 10., 16.9))
        self.assertIsNone(strong_close(10., 10., 10., 10.))
        self.assertIsNone(strong_close(10., 9., 8., 10.))

    def test_same_day_stop_takes_precedence_over_high(self):
        o = np.array([10., 10.]); h = np.array([14., 10.]); l = np.array([8., 9.]); c = np.array([12., 10.])
        out = next_open_outcome(o, h, l, c, np.array([10., 10.]), 0, 9.)
        self.assertEqual(out['status'], 'stop_day0')
        self.assertFalse(out['quick'])
        self.assertAlmostEqual(out['ret'], 9. / 10. * .9995 - 1.0005)

    def test_entry_day_fast_move_survives_unknown_later_data(self):
        o = np.array([10., np.nan]); h = np.array([14., np.nan]); l = np.array([9.5, np.nan]); c = np.array([12., np.nan])
        out = next_open_outcome(o, h, l, c, np.array([10., np.nan]), 0, 9.)
        self.assertTrue(out['quick'])
        self.assertIsNone(out['ret'])
        self.assertEqual(out['reason'], 'invalid_bar')
        self.assertEqual(next_open_outcome(o, h, l, c, o, 0, 10.)['status'], 'cancel_gap')


if __name__ == '__main__':
    unittest.main()
