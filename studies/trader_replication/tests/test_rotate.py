"""rotate_below: a close entry with no slot sells the weakest long up less than the limit; a real winner stays."""
import unittest

import numpy as np

from studies.trader_replication import system as Y


def run(limit, rise):
    n = 6
    c = np.array([[100.] * n, [100. + rise * i for i in range(n)], [50.] * n]).T
    p = dict(open=c, high=c * 1.001, low=c * .999, close=c, dates=np.array([f'2024-01-0{i + 1}' for i in range(n)]),
             codes=np.array(['A', 'B', 'C']), kind_pools=None)
    e = [[] for _ in range(n)]
    e[0] = [(0., 0, 1, 100., 80., 'x'), (1., 1, 1, 100., 80., 'x')]
    e[3] = [(0., 2, 1, 50., 40., 'x')]
    r = Y.Rules(max_open=2, trims=(), trail='', risk=.01, max_position=.3, rotate_below=limit, buy_cost=0, sell_cost=0)
    return Y.simulate(p, {}, r, e, p['dates'][0], p['dates'][-1])[2]


class Rotate(unittest.TestCase):
    def test_off_blocks_the_new_name(self):
        self.assertNotIn('C', {t['code'] for t in run(0., 2.)})

    def test_sells_the_weakest_under_the_limit(self):
        tr = {t['code']: t for t in run(.05, 3.)}
        self.assertEqual(tr['A']['why'], 'rotate')
        self.assertEqual(tr['A']['exit'], '2024-01-04')
        self.assertNotEqual(tr['B']['why'], 'rotate')
        self.assertIn('C', tr)

    def test_a_winner_is_kept(self):
        tr = run(.05, 10.)
        tr2 = {t['code']: t['why'] for t in run(.0001, 10.)}
        self.assertNotIn('rotate', [tr2.get('B')])
        self.assertTrue(tr)


if __name__ == '__main__':
    unittest.main()
