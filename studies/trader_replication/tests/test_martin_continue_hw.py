import unittest

from studies.trader_replication import preopen
from studies.trader_replication.martin_continue_hw import cap_core
from studies.trader_replication.system import Rules


class CoreEntryCapTest(unittest.TestCase):
    def test_core_cap_preserves_stricter_cap_and_other_orders(self):
        orders = [{'kind': 'n1', 'max_position': None}, {'kind': 'n1', 'max_position': .1},
                  {'kind': 'list', 'max_position': .5}]
        result = cap_core(orders)
        self.assertEqual([r['max_position'] for r in result], [.25, .1, .5])
        self.assertIsNone(orders[0]['max_position'])
        self.assertEqual(orders[2]['max_position'], .5)

    def test_initial_cap_does_not_cap_pending_winner_add(self):
        rules = Rules(max_position=.35, max_gross=2.8, add_frac=1., cap_adds_entry=False)
        holding = {'j': 0, 'side': 1, 'mark': 10., 'shares': 2., 'shares0': 2.,
                   'kind': 'n1', 'pending': 1., 'trail_pending': False, 'entry_index': 0,
                   'code': 'A', 'management': rules, 'cap': .25, 'add_mult': None}
        entry = ((1.,), 1, 1, 9., 'n1', None, .25, 1., None)
        plan = preopen.plan([entry], [holding], [10., 10.], 100., 80., rules, .01, 0,
                            fill_stop_pct_by_kind={'n1': .025})
        self.assertAlmostEqual(plan['entries'][('n1', 1)]['shares'] * 10.5, 25.)
        self.assertAlmostEqual(plan['adds'][0]['shares'] * 10.5, 15.)


if __name__ == '__main__':
    unittest.main()
