import unittest
from studies.trader_replication import martin_continue_fn as fn, system


class LeveragedTimingTests(unittest.TestCase):
    def test_shifted_core_keeps_list_and_short_then_removes_only_short(self):
        original = [[(0, 0, 1, 10., 9., 'n1'), (2, 1, 1, 10., 9., 'list'),
                     (1, 2, -1, 10., 11., 's_Z15')], []]
        shifted_core = [[], [(0, 0, 1, 11., 9., 'n1')]]
        shifted, only_long = fn.build_books(original, shifted_core)
        self.assertEqual([e[5] for e in shifted[0]], ['list', 's_Z15'])
        self.assertEqual([e[5] for e in only_long[0]], ['list'])
        self.assertEqual(shifted[1], shifted_core[1])
        self.assertEqual(len(original[0]), 3)

    def test_removing_adds_keeps_other_management(self):
        rules = system.Rules(add_levels=(1, 3), add_r=2, add_signal='x', max_gross=2.8,
                             management_by_kind={'list': {'add_levels': (1, 3), 'trail': 'e9'}})
        result = fn.no_adds(rules)
        self.assertEqual((result.add_levels, result.add_r, result.add_signal), ((), 0., ''))
        self.assertEqual(result.management_by_kind['list']['add_levels'], ())
        self.assertEqual((result.management_by_kind['list']['trail'], result.max_gross), ('e9', 2.8))


if __name__ == '__main__':
    unittest.main()
