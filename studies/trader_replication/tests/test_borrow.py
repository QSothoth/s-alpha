"""Execution timing of the stock-borrow fee: off by default; when on, a short pays rate / 252 of its value at the
previous close at the start of every session it is held overnight, inside its own trade result."""
import unittest

import numpy as np

from studies.trader_replication import system as Y

NOCOST = dict(buy_cost=0, sell_cost=0, margin_rate=0, trail='', trims=(), risk=.01, max_position=10.0,
              max_gross=10.0)
ROWS = [(10, 10, 10, 10), (10, 10.2, 9.8, 9.9), (9.9, 10.1, 9.6, 9.7), (9.7, 9.8, 9.4, 9.5)]


def run(side=-1, stop=10.5, **kw):
    a = np.array(ROWS, float)
    p = {'open': a[:, :1], 'high': a[:, 1:2], 'low': a[:, 2:3], 'close': a[:, 3:4],
         'dates': np.array(['2025-01-%02d' % (i + 1) for i in range(len(a))]), 'codes': np.array(['US.AAA'])}
    e = [[] for _ in ROWS]
    e[0].append((0, 0, side, 10.0, stop, 'short' if side < 0 else 'x'))
    return Y.simulate(p, {}, Y.Rules(**{**NOCOST, **kw}), e, p['dates'][0], p['dates'][-1], audit=True)


class BorrowTests(unittest.TestCase):
    def test_default_is_off(self):
        self.assertEqual(Y.Rules().borrow_rate, 0.0)
        c0, _, (t0,) = run()
        c1, _, (t1,) = run(borrow_rate=0.0)
        self.assertEqual(list(c0), list(c1))
        self.assertEqual(t0['pnl'], t1['pnl'])

    def test_fee_per_overnight_on_the_previous_close(self):
        c0, _, (t0,) = run()
        c1, _, (t1,) = run(borrow_rate=.03)
        size = t1['executions'][0]['shares']
        fees = [.03 / 252 * size * c for c in (10.0, 9.9, 9.7)]    # held over the closes of days 1, 2, 3
        self.assertAlmostEqual(c0[0] - c1[0], 0.0)                 # the entry day pays nothing
        self.assertAlmostEqual(c0[1] - c1[1], fees[0])
        self.assertAlmostEqual(c0[3] - c1[3], sum(fees))
        self.assertAlmostEqual(t0['pnl'] - t1['pnl'], sum(fees))   # ... and it is inside the trade's result

    def test_longs_pay_no_borrow(self):
        c0 = run(side=1, stop=9.0)[0]
        c1 = run(side=1, stop=9.0, borrow_rate=.03)[0]
        self.assertEqual(list(c0), list(c1))


if __name__ == '__main__':
    unittest.main()
