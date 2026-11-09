import unittest
from types import SimpleNamespace

import numpy as np

from studies.trader_replication.martin_continue_ax import fast_books


class FastBeforeShortlistTest(unittest.TestCase):
    def test_prior_adr_prioritizes_without_removing_slower_names(self):
        adr = np.full((3, 7), .04)
        adr[0, 6] = .06
        adr[1, 0] = .20  # Signal-day values are not available to the original AX2 ranking.
        data = SimpleNamespace(adr=adr, days=['2025-01-01', '2025-01-02', '2025-01-03'])
        row = [((2., 1., float(j)), j, 1, 10., 9., 'list') for j in range(7)]
        _, priority, _ = fast_books(data, [[], row, []])
        ranked = sorted(priority[1], key=lambda e: e[0])
        self.assertEqual(ranked[0][1], 6)
        self.assertEqual({x[1] for x in ranked}, set(range(7)))
        self.assertEqual(row[0][0], (2., 1., 0.))


if __name__ == '__main__':
    unittest.main()
