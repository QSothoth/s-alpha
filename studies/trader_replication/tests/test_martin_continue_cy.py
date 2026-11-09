import unittest

import numpy as np

from studies.trader_replication.martin_continue_cv import compare_cells
from studies.trader_replication.martin_continue_cx import decompose_cells
from studies.trader_replication.martin_continue_cy import check_cv_cells, classify, prior_squeeze, summarize


class ConvergenceTests(unittest.TestCase):
    def test_threshold_uses_only_eligible_finite_prior_values(self):
        groups, median = classify(np.array([.1, .3, .5, 50., np.nan]),
                                  np.array([True, True, True, False, True]))
        self.assertAlmostEqual(median, .3)
        self.assertEqual(groups.tolist(), [0, 0, 1, 1, -1])
        empty, median = classify(np.array([np.nan]), np.array([True]))
        self.assertIsNone(median)
        self.assertEqual(empty.tolist(), [-1])

    def test_squeeze_uses_previous_close_and_invalid_adr_is_unknown(self):
        e9 = np.array([[101., 101.], [102., 102.], [103., 103.]], dtype=np.float32)
        e21 = np.full((3, 2), 100., dtype=np.float32)
        adr = np.array([[.05, .0], [.05, .05], [.05, .05]], dtype=np.float32)
        result = prior_squeeze(e9, e21, adr, 1)
        self.assertAlmostEqual(float(result[0]), .2, places=5)
        self.assertTrue(np.isnan(result[1]))
        e9[1:] = 900
        np.testing.assert_array_equal(result, prior_squeeze(e9, e21, adr, 1))

    def test_matched_difference_excludes_unknowns_and_unmatched_cells(self):
        def outcomes(*returns):
            return [{'quick': None if r is None else r > 0, 'ret': r} for r in returns]
        cells = {('both', 0): {'h3': outcomes(.4, -.1, None), 'other': outcomes(.1, -.2)},
                 ('pullback_only', 1): {'h3': outcomes(.5), 'other': []}}
        matched = compare_cells(cells)
        day = {'matched': matched, 'contributions': decompose_cells(cells)}
        result = summarize([day], np.random.default_rng(7))
        self.assertEqual(result['return']['days'], 1)
        self.assertEqual(result['return']['weight'], 2)
        self.assertEqual(result['return']['unmatched_near'], 1)
        self.assertAlmostEqual(result['return']['difference'], .2)
        self.assertAlmostEqual(result['contributions']['near']['return'], .15)
        self.assertAlmostEqual(result['contributions']['far']['return'], -.05)
        check_cv_cells(cells, matched)
        cells[('both', 0)]['h3'][0]['ret'] = .6
        with self.assertRaises(AssertionError):
            check_cv_cells(cells, matched)


if __name__ == '__main__':
    unittest.main()
