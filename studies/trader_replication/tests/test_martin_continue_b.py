import unittest
from types import SimpleNamespace

import numpy as np

from studies.trader_replication.martin_continue_b import limit_execution, support_book


class LimitExecution(unittest.TestCase):
    def test_order_paths(self):
        self.assertIsNone(limit_execution(99, 97, 102.5, 100))
        self.assertIsNone(limit_execution(104, 103, 102.5, 100))
        self.assertEqual(limit_execution(101, 100.5, 102.5, 100), (101, None))
        self.assertEqual(limit_execution(104, 101, 102.5, 100), (102.5, None))
        self.assertEqual(limit_execution(104, 99, 102.5, 100), (102.5, 100))
        self.assertEqual(limit_execution(101, 99, 102.5, 100), (101, 100))

    def test_unfilled_first_order_does_not_select_a_later_fill(self):
        D = SimpleNamespace(days=['1', '2', '3'],
                            l=np.array([[10., 10.], [10., 10.], [11., 9.]]),
                            o=np.array([[10., 10.], [10., 10.], [12., 11.]]))
        broad = [[], [((0.,), 0, 1, 11., 10., 'list'), ((1.,), 1, 1, 11., 10., 'list')], []]
        orders, submitted = support_book(D, broad, [[], [], []])
        self.assertEqual(submitted[2], 1)
        self.assertEqual(orders[2], [])


if __name__ == '__main__':
    unittest.main()
