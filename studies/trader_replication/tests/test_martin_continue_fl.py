import unittest
import numpy as np
from studies.trader_replication import martin_continue_fl as fl


class WinnerCaptureTests(unittest.TestCase):
    def test_exit_day_high_is_not_counted_but_executed_sales_are(self):
        trade = {'fill': 10., 'ret': .3, 'add_tries': 0,
                 'executions': [{'action': 'entry', 'price': 10.}, {'action': 'trim', 'price': 16.},
                                {'action': 'stop', 'price': 12.}]}
        result = fl.winner_capture(trade, np.array([12., 15., 100.]), 0, 2, 0., 0.)
        self.assertAlmostEqual(result['upper'], .6)
        self.assertAlmostEqual(result['capture'], .5)
        self.assertTrue(result['trimmed'])

    def test_missing_high_is_unknown_and_inconsistent_profit_is_rejected(self):
        trade = {'fill': 10., 'ret': .1, 'add_tries': 0,
                 'executions': [{'action': 'entry', 'price': 10.}, {'action': 'trail_open', 'price': 11.}]}
        self.assertIsNone(fl.winner_capture(trade, np.array([np.nan, 11.]), 0, 1, 0., 0.))
        trade['ret'] = .5
        with self.assertRaises(ValueError):
            fl.winner_capture(trade, np.array([11., 11.]), 0, 1, 0., 0.)


if __name__ == '__main__':
    unittest.main()
