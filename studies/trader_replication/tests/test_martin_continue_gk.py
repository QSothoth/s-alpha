import unittest
from studies.trader_replication.martin_continue_gk import mix


class ChannelStopTest(unittest.TestCase):
    def test_each_channel_keeps_its_own_order_and_price(self):
        old = [[(1, 0, 1, 100., 90., 'n1'), (2, 1, 1, 100., 91., 'list')]]
        fixed = [[(1, 0, 1, 100., 97.5, 'n1'), (2, 1, 1, 100., 97.5, 'list')]]
        self.assertEqual([e[4] for e in mix(old, fixed, 'list')[0]], [90., 97.5])
        self.assertEqual([e[4] for e in mix(old, fixed, 'n1')[0]], [97.5, 91.])
        self.assertEqual(old[0][1][4], 91.)

    def test_invalid_channel_or_short_book_is_rejected(self):
        with self.assertRaises(ValueError):
            mix([[]], [], 'list')
        with self.assertRaises(ValueError):
            mix([[(1, 0, -1, 100., 101., 'short')]], [[]], 'list')


if __name__ == '__main__':
    unittest.main()
