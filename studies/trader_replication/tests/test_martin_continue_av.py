import unittest
from types import SimpleNamespace

import numpy as np

from studies.trader_replication.martin_continue_av import premier_books


class PremierBooks(unittest.TestCase):
    def test_prior_turnover_filters_and_prioritizes_without_touching_core(self):
        D = SimpleNamespace(days=['2024-01-02', '2024-01-03'],
                            to20=np.array([[1e8, 9e7, np.nan], [1., 1e12, 1e12]]))
        core = ((1.,), 2, 1, 10., 9., 'n1')
        rows = [((2., 1., float(i)), i, 1, 10., 9., 'list') for i in range(3)]
        book = [[], [core, *rows]]
        hard, priority, counts = premier_books(D, book)
        self.assertEqual(hard[1], [core, rows[0]])
        self.assertEqual(priority[1][0], core)
        self.assertLess(priority[1][1][0], priority[1][2][0])
        self.assertEqual(counts, {'2024:eligible': 1, '2024:ineligible': 1, '2024:missing': 1})
        D.to20[1] = 0
        self.assertEqual(premier_books(D, book), (hard, priority, counts))
