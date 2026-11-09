import unittest

import numpy as np

from studies.trader_replication import system


class GrossRoomRotation(unittest.TestCase):
    def test_full_gross_rotates_only_after_minimum_age(self):
        n = 6
        close = np.array([[100.] * n, [100. + 2 * i for i in range(n)], [50.] * n]).T
        px = dict(open=close, high=close * 1.001, low=close * .999, close=close,
                  dates=np.array([f'2024-01-0{i + 1}' for i in range(n)]), codes=np.array(['A', 'B', 'C']))
        entries = [[] for _ in range(n)]
        entries[0] = [(0., 0, 1, 100., 80., 'x'), (1., 1, 1, 100., 80., 'x')]
        entries[3] = [(0., 2, 1, 50., 40., 'x')]
        def run(age):
            rules = system.Rules(max_gross=.6, max_position=.3, risk=.1, trims=(), trail='',
                                 rotate_below=.02, rotate_min_days=age, buy_cost=0, sell_cost=0)
            return system.simulate(px, {}, rules, entries, px['dates'][0], px['dates'][-1])[2]
        trades = {t['code']: t for t in run(3)}
        self.assertEqual(trades['A']['why'], 'rotate')
        self.assertEqual(trades['A']['exit'], '2024-01-04')
        self.assertIn('C', trades)
        self.assertNotIn('C', {t['code'] for t in run(4)})
