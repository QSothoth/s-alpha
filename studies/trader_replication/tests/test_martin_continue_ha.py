import unittest

import numpy as np

from studies.martin_luk.replicate import index_risk_scale
from studies.trader_replication.martin_continue_ha import describe, risk_drift


class RiskDriftTest(unittest.TestCase):
    def test_gap_changes_risk_for_same_shares_without_future_selection(self):
        result = risk_drift(100., 105., 99.)
        self.assertEqual(result['status'], 'known')
        self.assertAlmostEqual(result['gap'], .05)
        self.assertAlmostEqual(result['risk_ratio'], 6.)
        self.assertAlmostEqual(risk_drift(100., 99.5, 99.)['risk_ratio'], .5)

    def test_prior_close_missing_below_and_float_boundary_are_not_plannable(self):
        self.assertEqual(risk_drift(None, 101., 99.)['status'], 'missing_previous')
        self.assertEqual(risk_drift(98., 101., 99.)['status'], 'previous_not_above_stop')
        value = float(np.float32(100.))
        self.assertEqual(risk_drift(value, 101., value + 1e-7)['status'], 'previous_stop_precision_unknown')

    def test_index_scale_for_open_ignores_that_days_close_and_pool(self):
        close = np.full((80, 2), 10.)
        pool = np.ones((80, 2), dtype=bool)
        changed_close, changed_pool = close.copy(), pool.copy()
        changed_close[60:, :] = 20.
        changed_pool[60, 0] = False
        before = index_risk_scale({'close': close}, pool, pb=1., ext=.5, ext_at=.05)
        after = index_risk_scale({'close': changed_close}, changed_pool, pb=1., ext=.5, ext_at=.05)
        np.testing.assert_array_equal(before[:61], after[:61])
        self.assertNotEqual(before[61], after[61])

    def test_counts_unknown_separately(self):
        rows = [risk_drift(100., 105., 99.), risk_drift(100., 99.5, 99.), risk_drift(None, 101., 99.)]
        result = describe(rows)
        self.assertEqual((result['entries'], result['known']), (3, 2))
        self.assertEqual(result['risk_at_least_double'], 1)
        self.assertEqual(result['risk_at_most_half'], 1)


if __name__ == '__main__':
    unittest.main()
