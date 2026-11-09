import unittest
from studies.trader_replication import martin_continue_ft as ft, system


class EmaTimingComparisonTests(unittest.TestCase):
    def test_only_list_trailing_line_changes_and_existing_management_stays(self):
        original = system.Rules(trail='e21', trail_next_open=True, add_next_open=True,
                                management_by_kind={'list': {'add_levels': (1, 3)},
                                                    'n1': {'max_position': .35}})
        changed = ft.list_ema9(original)
        self.assertEqual(changed.trail, 'e21')
        self.assertEqual(changed.management_by_kind['list'], {'add_levels': (1, 3), 'trail': 'e9'})
        self.assertEqual(changed.management_by_kind['n1'], {'max_position': .35})
        self.assertEqual(original.management_by_kind['list'], {'add_levels': (1, 3)})
        self.assertTrue(changed.trail_next_open and changed.add_next_open)


if __name__ == '__main__':
    unittest.main()
