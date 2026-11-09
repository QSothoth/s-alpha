import unittest

from studies.trader_replication.martin_continue_hx import winner_add_rules
from studies.trader_replication.martin_continue_hy import later_trial_add
from studies.trader_replication.system import Rules


class LaterTrialAddTest(unittest.TestCase):
    def test_only_trial_add_levels_change(self):
        cash = Rules(gross_cost=True, max_open=11, max_position=1 / 11, max_gross=1.,
                     trims=(), add_levels=(), add_r=0., management_by_kind={})
        early = winner_add_rules(cash)
        late = later_trial_add(early)
        self.assertEqual(late.management_by_kind['n1'], {'add_levels': (10, 20)})
        self.assertEqual(late.management_by_kind['list'], {'add_levels': (3, 6)})
        self.assertEqual(early.management_by_kind['list'], {'add_levels': (1, 3)})
        self.assertEqual(late.max_position, early.max_position)
        self.assertEqual(late.add_cap_limit, early.add_cap_limit)
        self.assertEqual(late.trail, early.trail)
        self.assertTrue(late.gross_cost)
        self.assertTrue(late.add_next_open)


if __name__ == '__main__':
    unittest.main()
