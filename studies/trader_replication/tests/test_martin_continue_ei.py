import unittest
from studies.trader_replication.martin_continue_ei import compare


class CutoffComparisonTests(unittest.TestCase):
    def test_detects_identity_price_pending_and_account_differences(self):
        row = {'code': 'US.A', 'side': 1, 'kind': 'list', 'extra': [],
               'fill_over_close': 1., 'stop_over_fill': .95, 'dayexit_over_fill': None}
        full = {'signals': {'2024-01-02': [row]}, 'pending': {'2024-01-02': ['US.A', .95]},
                'trade_keys': [['US.A', 1, 'list', '2024-01-02', '2024-01-03', 'stop']],
                'curve': [1., 1.1], 'dates': ['2024-01-02', '2024-01-03']}
        cut = {'signals': {'2024-01-02': [{**row, 'stop_over_fill': .90}]},
               'pending': {'2024-01-02': ['US.B', .95]}, 'trade_keys': [],
               'curve': [1., 1.], 'dates': full['dates']}
        result = compare(full, cut)
        self.assertEqual(result['price_days'], ['2024-01-02'])
        self.assertEqual(result['pending_days'], ['2024-01-02'])
        self.assertFalse(result['trade_identity_equal'])
        self.assertAlmostEqual(result['max_curve_abs_difference'], .1)


if __name__ == '__main__':
    unittest.main()
