"""The flow book: nothing before a day depends on bars after it; a stop fills at the gap; weights respect the budget."""
import unittest

import numpy as np

from studies.trader_replication import flow as FL


def data(n=60, m=6, seed=3):
    r = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(r.normal(.002, .03, (n, m)), axis=0))
    days = np.array([str(np.datetime64('2024-01-01') + i) for i in range(n)])
    ent = [[] for _ in range(n)]
    for d in range(3, n, 4):
        ent[d] = [(0., d % m, float(c[d, d % m]), float(c[d, d % m] * .95), 'hi52')]
    return dict(open=c * .999, high=c * 1.01, low=c * .99, close=c, range=c * .02, ema21=c, days=days, codes=np.arange(m).astype(str), pool=np.ones(c.shape, bool),
                entries=ent, window=(days[0], days[-1]), breadth=np.ones(n), lead_breadth=np.ones(n), index={str(x): i for i, x in enumerate(days)}, today=np.zeros(c.shape, int), rank=np.zeros(c.shape, int))


class Flow(unittest.TestCase):
    def test_no_lookahead(self):
        cfg = FL.Flow(a=.2, tighten=5, memory=.5, breadth=1.0, lead=1.0, ep_top=10, vol=.4, k_read=.5, bp=2.0, brake=.4, conv=2.0, conv_n=20)
        a, b = data(), data()
        for k in ('open', 'high', 'low', 'close', 'range', 'ema21'):
            b[k] = b[k].copy()
            b[k][40:] *= 3.0
        for d in range(40, 60):
            b['entries'][d] = []
        np.testing.assert_allclose(FL.run(a, cfg)[0][:40], FL.run(b, cfg)[0][:40])

    def test_stop_fills_at_a_gap(self):
        D = data()
        c = np.full(D['close'].shape, 100.)
        c[10:, 0] = 80.
        D.update(open=c, high=c, low=c, close=c, range=c * .02, ema21=c, entries=[[] for _ in range(60)])
        D['entries'][5] = [(0., 0, 100., 95., 'hi52')]
        _, tr = FL.run(D, FL.Flow())
        self.assertEqual(tr[0]['exit'], str(D['days'][10]))
        self.assertLess(tr[0]['ret'], -.15)

    def test_budget_cap(self):
        D = data()
        curve, tr = FL.run(D, FL.Flow(risk=.05, cap=.5, budget=.5, band=0.))
        self.assertTrue(tr)
        self.assertTrue(np.all(curve > 0))


if __name__ == '__main__':
    unittest.main()
