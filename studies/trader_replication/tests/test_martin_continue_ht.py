import unittest

import numpy as np

from studies.trader_replication.martin_continue_ht import turnover_books


class TurnoverPriorityTest(unittest.TestCase):
    def test_prior_turnover_before_limit_preserves_candidates_and_core(self):
        core = ((0., 0.), 9, 1, 10., 9., 'n1')
        trial = [((2., 1., float(j)), j, 1, 10., 9., 'list') for j in range(7)]
        book = [[], [core, *trial], []]
        values = np.zeros((3, 10))
        values[0, :7] = [1, 2, 3, 4, 5, np.nan, 8]
        values[1, :7] = [100, 0, 0, 0, 0, 0, 0]
        ranked, counts = turnover_books(book, [1], values, np.array(list('ABCDEFGHIJ')))
        ordered = sorted(ranked[1][1:], key=lambda e: e[0])
        self.assertEqual([x[1] for x in ordered], [6, 4, 3, 2, 1, 0, 5])
        self.assertEqual(ranked[1][0], core)
        self.assertEqual(book[1][1:], trial)
        self.assertEqual(counts, {'1': 7})

    def test_equal_and_missing_turnover_break_ties_by_code(self):
        trial = [((2., 1., float(j)), j, 1, 10., 9., 'list') for j in range(4)]
        values = np.array([[4., 4., np.nan, np.nan], [0., 0., 0., 0.]])
        ranked, _ = turnover_books([[], trial], [1], values, np.array(['B', 'A', 'D', 'C']))
        self.assertEqual([x[1] for x in sorted(ranked[1], key=lambda e: e[0])], [1, 0, 3, 2])


if __name__ == '__main__':
    unittest.main()
