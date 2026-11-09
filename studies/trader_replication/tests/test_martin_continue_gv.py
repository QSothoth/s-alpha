import unittest

import numpy as np

from studies.trader_replication.martin_continue_gv import sensitive_book
from studies.trader_replication.system import Rules, simulate


class TestPrecisionScenarios(unittest.TestCase):
    def test_only_registered_order_day_stop_changes(self):
        days, codes = ['2025-01-02', '2025-01-03'], ['US.X', 'US.Y']
        core = ((1, 0), 0, 1, 10., 9., 'n1', 9.)
        other = ((2, 0), 1, 1, 10., 9., 'list', 9., None, None, .5)
        original = [[core, other], []]
        key = (days[0], codes[0], 'n1')
        yes, first = sensitive_book(original, days, codes, {key}, True)
        no, second = sensitive_book(original, days, codes, {key}, False)
        self.assertEqual(first, second)
        self.assertEqual(yes[0][0][6], 9.)
        self.assertIsNone(no[0][0][6])
        self.assertEqual(no[0][1], other)
        self.assertEqual(original[0][0], core)

    def test_unresolved_first_day_can_change_account_path(self):
        days, codes = ['2025-01-02', '2025-01-03'], ['US.X']
        entry = ((1, 0), 0, 1, 10., 9., 'n1', 9.)
        book = [[entry], []]
        key = (days[0], codes[0], 'n1')
        a = np.array([[10., 10., 9., 10.], [11., 12., 10., 12.]])
        px = {'dates': np.array(days), 'codes': np.array(codes),
              **{name: a[:, i:i + 1] for i, name in enumerate(('open', 'high', 'low', 'close'))}}
        rules = Rules(trail='', trims=(), intraday_kinds=('n1',), buy_cost=0, sell_cost=0, margin_rate=0)
        def run(hit):
            scenario, _ = sensitive_book(book, days, codes, {key}, hit)
            curve, _, trades = simulate(px, {}, rules, scenario, days[0], days[-1], audit=True)
            return curve[-1], trades[0]['why']
        stopped, stopped_why = run(True)
        retained, retained_why = run(False)
        self.assertEqual((stopped_why, retained_why), ('stop_day0', 'end'))
        self.assertGreater(retained, stopped)
