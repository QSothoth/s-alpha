import unittest
from types import SimpleNamespace

import numpy as np

from studies.trader_replication.martin_continue_ax import fast_books


class FastBooks(unittest.TestCase):
    def test_only_previous_adr_affects_list_and_core_is_unchanged(self):
        D = SimpleNamespace(days=['2024-01-02', '2024-01-03'],
                            adr=np.array([[.06, .04, np.nan], [.01, .2, .2]]))
        core = ((1.,), 2, 1, 10., 9., 'n1')
        rows = [((2., 1., float(i)), i, 1, 10., 9., 'list') for i in range(3)]
        book = [[], [core, *rows]]
        hard, priority, counts = fast_books(D, book)
        self.assertEqual(hard[1], [core, rows[0]])
        self.assertEqual(priority[1][0], core)
        self.assertLess(priority[1][1][0], priority[1][2][0])
        self.assertEqual(counts, {'2024:eligible': 1, '2024:ineligible': 1, '2024:missing': 1})
        D.adr[1] = 0
        self.assertEqual(fast_books(D, book), (hard, priority, counts))
