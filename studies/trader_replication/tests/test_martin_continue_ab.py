import unittest

import numpy as np

from studies.trader_replication.martin_continue_ab import gap_group


class PastGapGroup(unittest.TestCase):
    def test_uses_only_history_and_requires_three_gaps(self):
        opening = np.full((65, 1), 100.)
        close = np.full_like(opening, 100.)
        opening[[5, 12, 30], 0] = 97.
        self.assertEqual(gap_group(opening, close, 61, 0), 'high')
        opening[61:, 0] = 1.
        close[61:, 0] = 1.
        self.assertEqual(gap_group(opening, close, 61, 0), 'high')
        opening[30, 0] = 100.
        self.assertEqual(gap_group(opening, close, 61, 0), 'low')

    def test_insufficient_history_is_missing(self):
        opening = np.full((65, 1), 100.)
        close = np.full_like(opening, 100.)
        opening[1:17, 0] = np.nan
        self.assertEqual(gap_group(opening, close, 61, 0), 'missing')
        self.assertEqual(gap_group(opening, close, 60, 0), 'missing')
