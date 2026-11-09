import unittest

import numpy as np

from studies.trader_replication.martin_continue_cx import decompose_cells, summarize


class ReturnDecompositionTests(unittest.TestCase):
    def test_matched_weights_unknown_and_unmatched_returns(self):
        def outcomes(*values):
            return [{'ret': value} for value in values]
        cells = {('pullback_only', 0): {'h3': outcomes(.4, -.1, None), 'other': outcomes(.1, -.2)},
                 ('both', 1): {'h3': outcomes(-.2), 'other': outcomes(.3, .3, .3, -.1)},
                 ('breakout_only', 2): {'h3': outcomes(.9), 'other': outcomes(None)}}
        day = decompose_cells(cells)
        self.assertEqual(day['weight'], 3)
        self.assertEqual(day['unmatched_h3'], 1)
        result = summarize([day], np.random.default_rng(7))
        self.assertAlmostEqual(result['h3']['win_probability'], 1 / 3)
        self.assertAlmostEqual(result['other']['win_probability'], 7 / 12)
        self.assertAlmostEqual(result['h3']['positive_contribution'], .4 / 3)
        self.assertAlmostEqual(result['other']['positive_contribution'], (.1 + .225) / 3)
        self.assertAlmostEqual(result['h3']['mean_win'], .4)
        self.assertAlmostEqual(result['h3']['mean_nonwin'], -.15)
        self.assertAlmostEqual(result['difference']['mean_return']['estimate'],
                               result['h3']['mean_return'] - result['other']['mean_return'])
        self.assertEqual(result['difference']['mean_return']['interval95'][0],
                         result['difference']['mean_return']['interval95'][1])


if __name__ == '__main__':
    unittest.main()
