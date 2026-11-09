import unittest

from studies.trader_replication.martin_continue_gq import sets_for_year


class TestOpportunityAccounting(unittest.TestCase):
    def test_shared_and_unique_orders_and_unknowns(self):
        rows = {
            ('a', 'X'): {'original': True, 'candidate': True, 'status': 'filled',
                         'leader': True, 'hit3': True, 'hit5': None, 'hit30': False},
            ('a', 'Y'): {'original': True, 'candidate': False, 'status': 'cancel',
                         'leader': False, 'hit3': False, 'hit5': False, 'hit30': False},
            ('a', 'Z'): {'original': False, 'candidate': True, 'status': 'filled',
                         'leader': True, 'hit3': True, 'hit5': True, 'hit30': None},
        }
        result = sets_for_year(rows, lambda r: r['original'], lambda r: r['candidate'])
        self.assertEqual([result[k]['orders'] for k in ('shared', 'original_only', 'gp_only')], [1, 1, 1])
        self.assertEqual(result['shared']['hit5']['unknown'], 1)
        self.assertEqual(result['gp_only']['hit30']['known'], 0)
        self.assertEqual(result['original_only']['status'], {'cancel': 1})
