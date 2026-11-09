import unittest

import numpy as np

from studies.trader_replication.martin_continue_cv import compare_cells, year_estimate


class MatchedCandidateTests(unittest.TestCase):
    def test_only_same_day_shape_and_volatility_cells_are_compared(self):
        a = {'quick': True, 'ret': .4}
        b = {'quick': False, 'ret': -.1}
        unknown = {'quick': None, 'ret': None}
        cells = {('pullback_only', 0): {'h3': [a, a, unknown], 'other': [b]},
                 ('breakout_only', 2): {'h3': [a], 'other': []},
                 ('both', 1): {'h3': [], 'other': [b]}}
        result = compare_cells(cells)
        self.assertEqual(result['quick']['h3_weight'], 2)
        self.assertEqual(result['quick']['other_n'], 1)
        self.assertEqual(result['quick']['unmatched_h3'], 1)
        self.assertEqual(result['quick']['numerator'], 2.)
        self.assertAlmostEqual(result['return']['numerator'], 1.)
        self.assertEqual(result['large']['numerator'], 2.)

    def test_cluster_bootstrap_preserves_candidate_weights(self):
        daily = [{'matched': {'quick': {'h3_weight': 2, 'numerator': 1., 'unmatched_h3': 0}}},
                 {'matched': {'quick': {'h3_weight': 1, 'numerator': -.25, 'unmatched_h3': 1}}}]
        a = year_estimate(daily, 'quick', np.random.default_rng(7))
        b = year_estimate(daily, 'quick', np.random.default_rng(7))
        self.assertEqual(a, b)
        self.assertEqual(a['days'], 2)
        self.assertEqual(a['h3_weight'], 3)
        self.assertAlmostEqual(a['difference'], .25)
        self.assertEqual(a['unmatched_h3'], 1)


if __name__ == '__main__':
    unittest.main()
