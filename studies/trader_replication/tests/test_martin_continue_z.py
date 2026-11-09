import unittest
from types import SimpleNamespace

import numpy as np

from studies.trader_replication.martin_continue_z import waiting_book


class WaitingBook(unittest.TestCase):
    def test_next_close_never_promotes_a_seventh_name_after_missing_fill(self):
        c = np.full((4, 8), 10.)
        c[2, 0] = np.nan
        D = SimpleNamespace(days=['a', 'b', 'c', 'd'], A={'close': c}, adr=np.full(c.shape, .04, np.float32))
        broad = [[], [((float(i),), i, 1, 10., 9., 'list') for i in range(8)], [], []]
        row = waiting_book(D, broad)[2]
        self.assertEqual([e[1] for e in row], [1, 2, 3, 4, 5])
        self.assertTrue(all(e[5] == 'wait' for e in row))
        self.assertAlmostEqual(row[0][4], 9.8, places=6)

    def test_entry_price_is_a_fill_not_a_selection_input(self):
        c = np.full((4, 3), 10.)
        D = SimpleNamespace(days=['a', 'b', 'c', 'd'], A={'close': c}, adr=np.full(c.shape, .04, np.float32))
        broad = [[], [((float(i),), i, 1, 10., 9., 'list') for i in range(3)], [], []]
        before = waiting_book(D, broad)[2]
        c[2] *= 2
        after = waiting_book(D, broad)[2]
        self.assertEqual([e[1] for e in before], [e[1] for e in after])
        self.assertTrue(all(a[3] == 2*b[3] and a[4] == 2*b[4] for a, b in zip(after, before)))


if __name__ == '__main__':
    unittest.main()
