import unittest

from studies.trader_replication.martin_continue_cp import pair_groups


def trade(code, pnl, kind='n1'):
    return {'entry': '2025-04-01', 'code': code, 'side': 1, 'kind': kind,
            'why': 'stop', 'days': 3, 'ret': pnl / 10, 'ret_invested': pnl / 10,
            'risk_pct': .05, 'pnl': pnl,
            'executions': [{'action': 'entry', 'price': 10., 'shares': 1.}]}


class AccountPairTests(unittest.TestCase):
    def test_common_and_unique_positions_are_disjoint_and_reconcile(self):
        left = [trade('US.A', 1.), trade('US.B', -1.)]
        right = [trade('US.A', 2.), trade('US.C', 3., 'list')]
        result = pair_groups(left, right, {'2025-04-01': 100.}, {'2025-04-01': 200.})['2025']
        self.assertEqual(result['left_common']['other']['entries'], 1)
        self.assertEqual(result['right_common']['other']['entries'], 1)
        self.assertEqual(result['left_only']['other']['closed_pnl'], -1.)
        self.assertEqual(result['right_only']['list']['closed_pnl'], 3.)
        self.assertAlmostEqual(result['left_common']['other']['median_entry_vs_prior_close_equity'], .1)
        self.assertAlmostEqual(result['right_common']['other']['median_entry_vs_prior_close_equity'], .05)

    def test_repeated_identity_is_rejected(self):
        with self.assertRaises(ValueError):
            pair_groups([trade('US.A', 1.), trade('US.A', 2.)], [], {'2025-04-01': 100.}, {})


if __name__ == '__main__':
    unittest.main()
