import unittest

import numpy as np

from studies.trader_replication.martin_continue_gn import candidates
from studies.trader_replication.system import Rules, simulate


class TestCashExitCandidates(unittest.TestCase):
    def test_ema9_exit_is_confirmed_then_executed_next_open(self):
        dates = np.array(['2025-01-02', '2025-01-03', '2025-01-06', '2025-01-07'])
        px = {'dates': dates, 'codes': np.array(['US.X']),
              'open': np.array([[10.], [10.], [11.], [10.4]]),
              'high': np.array([[10.], [11.], [11.], [10.5]]),
              'low': np.array([[10.], [10.], [10.2], [10.3]]),
              'close': np.array([[10.], [11.], [10.4], [10.4]])}
        ema = {'e9': np.array([[9.5], [10.], [10.5], [10.5]]),
               'e21': np.array([[9.], [9.], [9.], [9.]])}
        book = [[(0, 0, 1, 10., 9., 'n1')], [], [], []]
        base = Rules(trail='e21', trail_next_open=True, trims=(10,), trim_frac=.3,
                     buy_cost=0, sell_cost=0, margin_rate=0)
        for name, rule in candidates(base):
            _, _, trades = simulate(px, ema, rule, book, dates[0], dates[-1], audit=True)
            if name in ('GN9', 'GNB'):
                self.assertEqual((trades[0]['why'], trades[0]['exit']), ('trail_open', '2025-01-07'))
            else:
                self.assertEqual(trades[0]['why'], 'end')

    def test_partial_exits_use_fifteen_percent_at_three_and_five_r(self):
        dates = np.array(['2025-01-02', '2025-01-03'])
        px = {'dates': dates, 'codes': np.array(['US.X']),
              'open': np.array([[10.], [10.]]), 'high': np.array([[10.], [15.]]),
              'low': np.array([[10.], [10.]]), 'close': np.array([[10.], [14.]])}
        book = [[(0, 0, 1, 10., 9., 'n1')], []]
        base = Rules(trail='', trims=(10,), trim_frac=.3, buy_cost=0, sell_cost=0, margin_rate=0)
        _, _, trades = simulate(px, {}, dict(candidates(base))['GNT'], book, dates[0], dates[-1], audit=True)
        executions = trades[0]['executions']
        entry = executions[0]['shares']
        trims = [e for e in executions if e['action'] == 'trim']
        self.assertEqual([e['price'] for e in trims], [13., 15.])
        for trim in trims:
            self.assertAlmostEqual(trim['shares'], entry * .15)
