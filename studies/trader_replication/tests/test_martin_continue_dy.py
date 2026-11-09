import unittest
from studies.trader_replication.martin_continue_dy import compare_r, describe, risk_return


class InitialRiskTests(unittest.TestCase):
    def test_cost_adjusted_return_uses_original_stop_risk(self):
        risk, value = risk_return(100., 98., {'status': 'entered', 'ret': .06})
        self.assertAlmostEqual(risk, .02)
        self.assertAlmostEqual(value, 3.)
        self.assertEqual(risk_return(97., 98., {'status': 'cancel_gap', 'ret': None}), (None, None))

    def test_unmatured_and_missing_loss_group_remain_unknown(self):
        risk, value = risk_return(100., 98., {'status': 'entered', 'ret': None})
        self.assertAlmostEqual(risk, .02)
        self.assertIsNone(value)
        self.assertIsNone(describe([risk], [3.])['payoff_ratio'])

    def test_three_and_five_r_thresholds_are_inclusive(self):
        cells = {('breakout', 0): {'h3': [3., 5.], 'other': [2., 4.]}}
        result = compare_r(cells)
        self.assertEqual(result['quick']['numerator'], 1.)
        self.assertEqual(result['large']['numerator'], 1.)
        self.assertEqual(result['return']['numerator'], 2.)


if __name__ == '__main__':
    unittest.main()
