import unittest

import numpy as np

from studies.trader_replication.martin_continue_cr import close_path


class ClosePathTests(unittest.TestCase):
    def test_realized_and_unrealized_returns_use_all_invested_capital(self):
        days = ['2025-01-02', '2025-01-03', '2025-01-06']
        trade = {'side': 1, 'why': 'stop', 'entry': days[0], 'exit': days[2],
                 'ret_invested': (-10.005 - 20.01 + 29.985) / 30,
                 'executions': [{'time': days[0], 'action': 'entry', 'price': 10., 'shares': 1.},
                                {'time': days[1], 'action': 'add', 'price': 20., 'shares': 1.},
                                {'time': days[2], 'action': 'stop', 'price': 15., 'shares': 2.}]}
        path = close_path(trade, days, np.array([15., 20., 15.]), .0005, .0005)
        self.assertEqual(path['peak_date'], days[0])
        self.assertAlmostEqual(path['peak_return'], (15 - 10.005) / 10)
        self.assertAlmostEqual(path['peak_minus_final'], path['peak_return'] - trade['ret_invested'])
        self.assertEqual(path['missing_days'], 0)

    def test_missing_close_is_not_imputed_and_bad_reconciliation_fails(self):
        days = ['2025-01-02', '2025-01-03']
        t = {'side': 1, 'why': 'stop', 'entry': days[0], 'exit': days[1], 'ret_invested': -.1,
             'executions': [{'time': days[0], 'action': 'entry', 'price': 10., 'shares': 1.},
                            {'time': days[1], 'action': 'stop', 'price': 9., 'shares': 1.}]}
        p = close_path(t, days, np.array([np.nan, 9.]), 0., 0.)
        self.assertEqual(p['missing_days'], 1)
        self.assertEqual(p['peak_date'], days[1])
        t['ret_invested'] = .1
        with self.assertRaises(AssertionError):
            close_path(t, days, np.array([10., 9.]), 0., 0.)


if __name__ == '__main__':
    unittest.main()
