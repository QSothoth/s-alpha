import unittest

import numpy as np

from studies.trader_replication.system import Rules, simulate


class TestConcurrentTrialLimit(unittest.TestCase):
    def test_trial_limit_applies_at_open_and_releases_next_day(self):
        days = np.array(['2025-01-02', '2025-01-03'])
        prices = np.full((2, 3), 10.)
        lows = prices.copy()
        lows[0, 1] = 9.
        px = {'dates': days, 'codes': np.array(['US.CORE', 'US.FIRST', 'US.SECOND']),
              'open': prices, 'high': prices, 'low': lows, 'close': prices}
        core = ((1, 0), 0, 1, 10., 9., 'n1', None)
        first = ((2, 0), 1, 1, 10., 9., 'list', 9.)
        second = ((2, 1), 2, 1, 10., 9., 'list', None)
        rules = Rules(trail='', trims=(), intraday_kinds=('n1', 'list'), max_open_by_kind={'list': 1},
                      no_rebuy_day=True, buy_cost=0, sell_cost=0, margin_rate=0)
        _, _, trades = simulate(px, {}, rules, [[core, first, second], [second]], days[0], days[-1])
        self.assertEqual([(t['code'], t['entry'], t['why']) for t in trades if t['kind'] == 'list'],
                         [('US.FIRST', '2025-01-02', 'stop_day0'), ('US.SECOND', '2025-01-03', 'end')])
        self.assertTrue(any(t['code'] == 'US.CORE' for t in trades))
