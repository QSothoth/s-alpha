import unittest

from studies.trader_replication.martin_continue_d import reconcile


def trade(code, entry, kind, pnl, why='stop'):
    return dict(code=code, entry=entry, exit=entry, kind=kind, pnl=pnl, ret=pnl, why=why)


class Pairing(unittest.TestCase):
    def test_account_change_decomposes_into_common_removed_and_added(self):
        first = [trade('A', '2025-01-02', 'list', .1), trade('B', '2025-01-02', 'list', -.02)]
        second = [trade('A', '2025-01-02', 'list', .12), trade('C', '2025-01-03', 'lim', .04)]
        r = reconcile(first, second)
        y = r['by_entry_year']['2025']
        self.assertEqual(y['common']['count'], 1)
        self.assertEqual(y['d1_only']['count'], 1)
        self.assertEqual(y['b2_limit_only']['count'], 1)
        delta = y['common_pnl_delta'] - y['d1_only']['pnl'] + y['b2_only']['pnl']
        self.assertAlmostEqual(delta, r['pnl_b2'] - r['pnl_d1'])

    def test_duplicate_identity_is_rejected(self):
        t = trade('A', '2025-01-02', 'list', .1)
        with self.assertRaises(ValueError):
            reconcile([t, t], [])


if __name__ == '__main__':
    unittest.main()
