import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from studies.trader_replication.martin_continue_j import market_states
from studies.trader_replication.martin_continue_k import summarize


class MarketTiming(unittest.TestCase):
    def test_market_switches_do_not_read_todays_or_later_bars(self):
        c = np.full((6, 101), 10., dtype=np.float32)
        D = SimpleNamespace(c=c.copy(), U=np.ones(c.shape, bool), days=['x'] * len(c))
        F = {'act20': np.ones(c.shape, dtype=np.float32)}
        with patch('studies.trader_replication.martin_continue_j.bench', return_value=np.full(6, 10.)):
            original = market_states(D, F)
        D.c[3:] = 3.
        D.U[3:] = False
        F['act20'][3:] = -9.
        with patch('studies.trader_replication.martin_continue_j.bench', return_value=np.array([10., 10., 10., 3., 3., 3.])):
            changed = market_states(D, F)
        for first, second in zip(original, changed):
            np.testing.assert_array_equal(first[:4], second[:4])

    def test_paired_summary_counts_the_same_entries(self):
        pairs = [({'ret': .1, 'days': 4}, {'ret': .2, 'days': 6}),
                 ({'ret': -.05, 'days': 1}, {'ret': -.04, 'days': 2})]
        r = summarize(pairs)
        self.assertEqual(r['count'], 2)
        self.assertEqual(r['b2_winners'], 1)
        self.assertEqual(r['winner_kept'], 1)
        self.assertAlmostEqual(r['delta'], .055)


if __name__ == '__main__':
    unittest.main()
