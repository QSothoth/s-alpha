import unittest
from unittest.mock import patch

from studies.trader_replication.martin_continue_cb import group_pair


def trade(day, code, kind, pnl):
    return {'entry': day, 'code': code, 'kind': kind, 'side': 1, 'pnl': pnl}


def simple_describe(rows):
    return {'entries': len(rows), 'closed_pnl': sum(t['pnl'] for t in rows), 'open_mark_pnl': 0}


class AccountAttributionTests(unittest.TestCase):
    def test_common_unique_and_kind_preserve_each_accounts_trades(self):
        left = [trade('2025-01-02', 'A', 'list', 1), trade('2025-01-03', 'B', 'core', -2)]
        right = [trade('2025-01-02', 'A', 'list', 3), trade('2025-01-03', 'B', 'list', 4)]
        with patch('studies.trader_replication.martin_continue_cb.describe', side_effect=simple_describe):
            groups = group_pair(left, right)['2025']
        self.assertEqual(groups['left_common']['list']['closed_pnl'], 1)
        self.assertEqual(groups['right_common']['list']['closed_pnl'], 3)
        self.assertEqual(groups['left_only']['other']['entries'], 1)
        self.assertEqual(groups['right_only']['list']['entries'], 1)

    def test_duplicate_identity_is_rejected(self):
        row = trade('2025-01-02', 'A', 'list', 1)
        with self.assertRaises(ValueError):
            group_pair([row, row], [])


if __name__ == '__main__':
    unittest.main()
