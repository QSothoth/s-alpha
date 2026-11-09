import unittest
from studies.trader_replication.martin_continue_es import order_state


class OpeningFunnelTests(unittest.TestCase):
    def test_opening_then_intraday_stop_and_unknown(self):
        self.assertEqual(order_state(100., 97., 98.), 'stop_day0')
        self.assertEqual(order_state(100., 99., 98.), 'survives')
        self.assertEqual(order_state(97., 96., 98.), 'cancel_gap')
        self.assertEqual(order_state(float('nan'), 96., 98.), 'missing')
        self.assertEqual(order_state(3.9600000381469727, 3.9, 3.96), 'precision_unknown')


if __name__ == '__main__':
    unittest.main()
