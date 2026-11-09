import unittest
from dataclasses import replace

from studies.trader_replication.martin_continue_gm import cap_list
from studies.trader_replication.system import Rules


class TestListCap(unittest.TestCase):
    def test_list_cap_preserves_other_rules_and_management(self):
        original = Rules(max_position=.35, management_by_kind={
            'list': {'add_levels': (1, 3), 'trail': 'e21'},
            'n1': {'trail': 'e9'},
        })
        candidate = cap_list(original)
        self.assertEqual(candidate.management_by_kind['list'],
                         {'add_levels': (1, 3), 'trail': 'e21', 'max_position': .25})
        self.assertEqual(candidate.management_by_kind['n1'], original.management_by_kind['n1'])
        self.assertEqual(replace(candidate, management_by_kind=original.management_by_kind), original)
        self.assertNotIn('max_position', original.management_by_kind['list'])

    def test_position_cap_changes_list_not_core_opening(self):
        import numpy as np
        from studies.trader_replication.system import simulate

        dates = np.array(['2025-01-02', '2025-01-03'])
        price = np.full((2, 2), 10.0)
        px = {'dates': dates, 'codes': np.array(['US.LIST', 'US.CORE']),
              'open': price, 'high': price, 'low': price, 'close': price}
        entries = [[(0, 0, 1, 10., 9.5, 'list'), (1, 1, 1, 10., 9.5, 'n1')], []]
        rules = Rules(risk=.02, max_position=.35, max_gross=2, trail='', trims=(),
                      buy_cost=0, sell_cost=0, margin_rate=0)
        def opened(rule):
            _, _, trades = simulate(px, {}, rule, entries, dates[0], dates[-1], audit=True)
            return {t['kind']: t['executions'][0]['shares'] * 10 for t in trades}
        self.assertAlmostEqual(opened(rules)['list'], .35)
        self.assertAlmostEqual(opened(cap_list(rules))['list'], .25)
        self.assertAlmostEqual(opened(cap_list(rules))['n1'], .35)

    def test_position_cap_also_limits_list_add(self):
        import numpy as np
        from studies.trader_replication.system import simulate

        dates = np.array(['2025-01-02', '2025-01-03', '2025-01-06'])
        px = {'dates': dates, 'codes': np.array(['US.LIST']),
              'open': np.array([[10.], [10.], [11.2]]),
              'high': np.array([[10.], [11.], [11.3]]),
              'low': np.array([[10.], [10.], [11.1]]),
              'close': np.array([[10.], [11.], [11.2]])}
        entries = [[(0, 0, 1, 10., 9.5, 'list')], [], []]
        rules = Rules(risk=.0075, max_position=.35, max_gross=2, trail='', trims=(),
                      add_r=2, add_next_open=True, buy_cost=0, sell_cost=0, margin_rate=0)
        def add_value(rule):
            _, _, trades = simulate(px, {}, rule, entries, dates[0], dates[-1], audit=True)
            add = [e for e in trades[0]['executions'] if e['action'] == 'add']
            self.assertEqual(len(add), 1)
            return add[0]['shares'] * add[0]['price']
        self.assertGreater(add_value(rules), add_value(cap_list(rules)))
