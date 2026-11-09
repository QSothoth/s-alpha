import unittest

from studies.trader_replication.martin_continue_dz import fee_risk, precision_unknown


class PrecisionAndRiskTests(unittest.TestCase):
    def test_indistinguishable_fill_is_unknown(self):
        outcome = {'status': 'stop_day0'}
        self.assertTrue(precision_unknown(3.9600000381469727, 3.96, outcome))
        self.assertFalse(precision_unknown(3.97, 3.96, outcome))
        self.assertFalse(precision_unknown(3.9600000381469727, 3.96, {'status': 'cancel_gap'}))

    def test_fees_are_part_of_initial_risk(self):
        self.assertAlmostEqual(fee_risk(100, 98), (100 * 1.0005 - 98 * .9995) / 100)
        self.assertAlmostEqual(fee_risk(100, 100), .001)


if __name__ == '__main__':
    unittest.main()
