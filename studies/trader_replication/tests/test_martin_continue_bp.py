import unittest

import numpy as np

from studies.trader_replication import system
from studies.trader_replication.martin_continue_bp import list_e9


class ListEmaExit(unittest.TestCase):
    def test_only_list_uses_the_faster_exit(self):
        close = np.array([[100., 100.], [98., 98.], [97., 97.], [97., 97.]])
        dates = np.array(['2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05'])
        px = dict(open=close, high=close * 1.001, low=close * .999, close=close,
                  dates=dates, codes=np.array(['LIST', 'CORE']))
        ema = {'e9': np.full(close.shape, 99.), 'e21': np.full(close.shape, 95.)}
        entries = [[(0., 0, 1, 100., 80., 'list'), (1., 1, 1, 100., 80., 'n1')], [], [], []]
        base = system.Rules(trail='e21', trims=(), arm_trail_on_entry=True, buy_cost=0, sell_cost=0,
                            management_by_kind={'list': {'add_levels': (1, 3)}})
        changed = list_e9(base)
        trades = {t['code']: t for t in system.simulate(px, ema, changed, entries, dates[0], dates[-1])[2]}
        self.assertEqual(trades['LIST']['why'], 'trail')
        self.assertEqual(trades['LIST']['exit'], '2024-01-03')
        self.assertEqual(trades['CORE']['why'], 'end')
        self.assertEqual(changed.management_by_kind['list']['add_levels'], (1, 3))
        self.assertNotIn('trail', base.management_by_kind['list'])
