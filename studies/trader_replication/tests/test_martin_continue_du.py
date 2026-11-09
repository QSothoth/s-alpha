import unittest

import numpy as np
from studies.trader_replication.martin_continue_du import blocks, signature
from studies.trader_replication.martin_continue_cv import METRICS


class SignalData:
    c = np.array([[10., 10.], [11., 9.], [999., 999.]])
    l = np.array([[9., 9.], [10., 8.], [1., 1.]])
    h = np.array([[10., 10.], [12., 10.], [1000., 1000.]])
    e9 = np.array([[9., 9.], [10., 10.], [1., 1.]])


class HistoricalSensitivityTests(unittest.TestCase):
    def test_signal_ignores_later_prices_and_identifies_types(self):
        data = SignalData()
        fields = {'lowe9': np.array([[0., 0.], [0., 0.], [0., 0.]]),
                  'cpos': np.array([[.5, .5], [.8, .2], [.5, .5]]),
                  'ext21': np.zeros((3, 2))}
        mask = np.ones((3, 2), bool)
        holding = np.array([[False, False], [True, False], [False, False]])
        first = signature(data, fields, mask, holding, 1)
        data.c[2] = 1
        self.assertEqual(signature(data, fields, mask, holding, 1), first)
        self.assertEqual(first['active'], [0, 1])
        self.assertEqual(first['holding'], [0])
        self.assertEqual([row[0] for row in first['candidates']], [0])
        self.assertAlmostEqual(first['candidates'][0][2], .95)

    def test_empty_bootstrap_denominator_is_unknown(self):
        row = {'matched': {key: {'h3_weight': 0, 'numerator': 0., 'unmatched_h3': 0} for key in METRICS}}
        result = blocks([row] * 21, np.random.default_rng(1))
        self.assertIsNone(result['quick']['difference'])
        self.assertIsNone(result['quick']['interval95'])
        self.assertEqual(result['quick']['zero_denominator_draws'], 1000)


if __name__ == '__main__':
    unittest.main()
