import unittest

import numpy as np

from studies.trader_replication.system import Rules, simulate


class TestCashChannelCompetition(unittest.TestCase):
    def test_core_precedes_list_and_openings_fit_cash_and_six_positions(self):
        dates = np.array(['2025-01-02', '2025-01-03'])
        price = np.full((2, 7), 10.)
        px = {'dates': dates, 'codes': np.array([f'US.{i}' for i in range(7)]),
              'open': price, 'high': price, 'low': price, 'close': price}
        core = [((1, 0), 0, 1, 10., 9., 'n1')]
        listed = [((2, i), i, 1, 10., 9., 'list', None, None, None, .5) for i in range(7)]
        rules = Rules(risk=.05, max_position=1 / 6, max_gross=1., max_open=6, gross_cost=True,
                      max_new_long=6, no_rebuy_day=True, intraday_kinds=('n1', 'list'),
                      trail='', trims=(), buy_cost=.001, sell_cost=0, margin_rate=0)
        _, _, trades = simulate(px, {}, rules, [core + listed, []], dates[0], dates[-1], audit=True)
        self.assertEqual(len(trades), 6)
        self.assertEqual([(t['code'], t['kind']) for t in trades if t['code'] == 'US.0'], [('US.0', 'n1')])
        total_cost = sum(t['executions'][0]['shares'] * 10 * 1.001 for t in trades)
        self.assertLessEqual(total_cost, 1 + 1e-12)
