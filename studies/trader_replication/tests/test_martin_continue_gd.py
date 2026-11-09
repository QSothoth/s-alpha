import unittest
from studies.trader_replication.martin_continue_gd import order_state


class ForcedEntryTest(unittest.TestCase):
    def test_prior_stop_and_day_zero_are_distinguished(self):
        self.assertEqual(order_state(100., 92., 90.), 'fillable')
        self.assertEqual(order_state(100., 89., 90.), 'day0_stop')
        self.assertEqual(order_state(89., 88., 90.), 'open_below_stop')

    def test_float_precision_and_missing_are_unknown(self):
        self.assertEqual(order_state(90., 89., 90.), 'opening_precision_unknown')
        self.assertEqual(order_state(100., 90., 90.), 'stop_precision_unknown')
        self.assertEqual(order_state(float('nan'), 89., 90.), 'opening_missing')
        self.assertEqual(order_state(100., float('nan'), 90.), 'low_missing')
        self.assertEqual(order_state(100., 89., 0.), 'signal_low_missing')


if __name__ == '__main__':
    unittest.main()
