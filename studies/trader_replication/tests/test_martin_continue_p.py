import unittest

import numpy as np

from studies.trader_replication.martin_continue_p import rank_peers


class PeerOrdering(unittest.TestCase):
    def test_strength_then_tightness_then_turnover_and_missing(self):
        near = np.ones((5, 2), dtype=bool)
        leaders = np.array([.1, .2])
        candidates = np.array([.25, .25, .25, .15, np.nan])
        tight = np.array([.5, .3, .3, .1, .0])
        turnover = np.array([1., 1., 2., 100., 1000.])
        codes = np.array(['A', 'B', 'C', 'D', 'E'])
        np.testing.assert_array_equal(rank_peers(near, candidates, leaders, tight, turnover, codes), [2, 1, 0, 3, 4])


if __name__ == '__main__':
    unittest.main()
