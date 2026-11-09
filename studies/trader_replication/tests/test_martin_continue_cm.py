import unittest

import numpy as np

from studies.trader_replication.martin_continue_ab import gap_group
from studies.trader_replication.martin_continue_cm import prefer_gap


class GapPriorityTests(unittest.TestCase):
    def test_priority_uses_prior_sessions_and_preserves_all_signals(self):
        opening = np.full((75, 3), 100.0)
        close = np.full((75, 3), 100.0)
        opening[[20, 30, 40], 1] = 96.0
        opening[:, 2] = np.nan
        day = 70
        self.assertEqual([gap_group(opening, close, day, j) for j in range(3)],
                         ['low', 'high', 'missing'])
        book = [[] for _ in range(75)]
        book[day] = [((1., -.8), 0, 1, 10., 9., 'list'),
                     ((1., -.5), 1, 1, 11., 10., 'list'),
                     ((1., -.7), 2, 1, 12., 11., 'list')]
        days = ['2025-01-01'] * 75
        ranked, counts = prefer_gap(book, opening, close, days)
        self.assertEqual([e[1] for e in sorted(ranked[day])], [1, 0, 2])
        self.assertEqual([e[1:] for e in ranked[day]], [e[1:] for e in book[day]])
        self.assertEqual(sum(counts.values()), 3)
        opening[day:] = 1.0
        close[day:] = 1.0
        self.assertEqual(prefer_gap(book, opening, close, days), (ranked, counts))


if __name__ == '__main__':
    unittest.main()
