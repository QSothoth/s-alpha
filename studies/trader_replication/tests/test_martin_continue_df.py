import unittest

import numpy as np

from studies.trader_replication.martin_continue_df import capped, ledger_result, qqq_gate


class GateComparisonTest(unittest.TestCase):
    def test_today_qqq_close_does_not_change_todays_gate(self):
        prices = np.linspace(100, 80, 80)
        changed = prices.copy()
        changed[60:] = 1000
        original, after = qqq_gate(prices), qqq_gate(changed)
        np.testing.assert_array_equal(original[:61], after[:61])
        self.assertFalse(original[0])
        self.assertTrue(original[60])
        self.assertFalse(after[61])

    def test_short_daily_priority_and_ledger_stages(self):
        candidate = (2., 0, -1, 10., 11., 's_Z15', None, None)
        second = (1., 1, -1, 10., 11., 's_Z15', None, None)
        raw = [[candidate, second]]
        cap = capped(raw)
        self.assertEqual(cap[0][0][1], 1)
        ref = [{'id': 'x', 'entry_date': '2025-01-02', 'ticker': 'A', 'days': [
            {'day': '2025-01-02', 'stages': [True, True, True],
             'prior_e21_limit': 10., 'open': 9., 'high': 11.}]}]
        ledger = ledger_result(ref, np.array([True]), raw, cap, [], ['2025-01-02'], ['US.A', 'US.B'])
        self.assertEqual(ledger['ledger'][0]['days'][0]['stages'],
                         [True, True, True, True, True, True, False, False])
        self.assertEqual(ledger['ledger'][0]['first_missing'], 'daily_cap')


if __name__ == '__main__':
    unittest.main()
