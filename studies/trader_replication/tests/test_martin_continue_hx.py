import unittest

from studies.trader_replication import preopen
from studies.trader_replication.martin_continue_hx import winner_add_rules
from studies.trader_replication.system import Rules


class CashWinnerAddTest(unittest.TestCase):
    def cash_rules(self):
        return Rules(gross_cost=True, max_open=11, max_position=1 / 11, max_gross=1.,
                     trims=(), add_levels=(), add_r=0., management_by_kind={})

    def test_adding_winners_keeps_cash_rules_and_fixed_levels(self):
        baseline = self.cash_rules()
        rules = winner_add_rules(baseline)
        self.assertTrue(rules.gross_cost)
        self.assertEqual(rules.max_gross, 1.)
        self.assertEqual(rules.max_open, 11)
        self.assertEqual(rules.management_by_kind['n1']['add_levels'], (10, 20))
        self.assertEqual(rules.management_by_kind['list']['add_levels'], (1, 3))
        self.assertEqual(rules.add_cap_mult, 2.)
        self.assertEqual(rules.add_cap_limit, 2 / 11)
        self.assertTrue(rules.add_next_open)
        self.assertFalse(baseline.management_by_kind)

    def test_no_cash_means_no_pending_add(self):
        rules = winner_add_rules(self.cash_rules())
        holding = {'j': 0, 'side': 1, 'mark': 10., 'shares': 1., 'shares0': 1.,
                   'kind': 'n1', 'pending': 1., 'trail_pending': False, 'entry_index': 0,
                   'code': 'A', 'management': rules, 'cap': 1 / 11, 'add_mult': None}
        plan = preopen.plan([], [holding], [10.], 100., 0., rules, .05, 0,
                            fill_stop_pct_by_kind={'n1': .025, 'list': .025})
        self.assertEqual(plan['adds'], {})
        self.assertGreaterEqual(plan['unreserved_cash'], 0.)


if __name__ == '__main__':
    unittest.main()
