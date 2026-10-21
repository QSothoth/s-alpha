"""Shared daily mechanisms of the G rounds (2026-10-21): the strength percentile and the market regime are read as of
the day before the entry; the regime scales a long's risk without touching shorts; the strength ranking orders the
day's longs before the daily cap."""
import unittest

import numpy as np

from studies.trader_replication import common as C, human as H

DAYS = np.array(['2025-01-%02d' % (i + 1) for i in range(8)])


def arrays(close):
    c = np.asarray(close, float)
    return {'close': c, 'open': c, 'high': c, 'low': c, 'has': np.isfinite(c), 'days': DAYS[:len(c)],
            'turnover': np.ones_like(c), 'to20': np.ones_like(c), 'adr': np.full_like(c, 5.0)}


class Strength(unittest.TestCase):
    def test_percentile_of_the_best_window_across_names(self):
        T = 130
        c = np.ones((T, 3))
        c[:, 0] = np.linspace(1, 3, T)                      # the strongest on every window
        c[:, 1] = np.linspace(1, 2, T)
        c[:, 2] = np.linspace(1, .5, T)
        s = C.strength(arrays(c))
        self.assertTrue(np.isnan(s[0]).all())               # no window yet
        self.assertEqual(list(s[-1]), [1.0, .5, 0.0])

    def test_ranking_uses_the_day_before(self):
        T = 30
        c = np.ones((T, 2))
        c[:, 0] = np.linspace(1, 2, T)
        c[:, 1] = np.linspace(1, 1.5, T)
        c[-1, 1] = 10.0                                     # name 1 jumps on the entry day itself
        A = arrays(c)
        e = [[] for _ in range(T)]
        e[-1] = [(0, 1, 1, 10.0, 9.0, 'x'), (1, 0, 1, 2.0, 1.9, 'x')]
        out = C.rerank(A, e, 'strength')
        self.assertEqual([x[1] for x in sorted(out[-1], key=lambda x: x[0])], [0, 1])

    def test_ep_strength_keeps_eps_first(self):
        T = 30
        c = np.ones((T, 2))
        c[:, 0] = np.linspace(1, 2, T)
        A = arrays(c)
        e = [[] for _ in range(T)]
        e[-1] = [(0, 0, 1, 2.0, 1.9, 'brk'), (1, 1, 1, 1.0, .9, 'ep')]
        out = C.rerank(A, e, 'ep_strength', ep=lambda d, x: x[5] == 'ep')
        self.assertEqual([x[1] for x in sorted(out[-1], key=lambda x: x[0])], [1, 0])


class Regime(unittest.TestCase):
    def test_down_is_the_equal_weight_index_below_its_average_as_of_the_day_before(self):
        c = np.ones((8, 2))
        c[5:] = .5                                          # the pool falls on day 5
        A = arrays(c)
        down = H.regime_down(A, 3)
        self.assertEqual(list(down), [False] * 6 + [True, True])   # known from day 6 (the day after the fall)

    def test_longs_on_down_days_take_the_multiplier_and_shorts_are_untouched(self):
        c = np.ones((8, 2))
        c[5:] = .5
        A = arrays(c)
        e = [[] for _ in range(8)]
        e[6] = [(0, 0, 1, .5, .45, 'x'), (1, 1, -1, .5, .55, 's_x')]
        e[4] = [(0, 0, 1, 1.0, .9, 'x', None, None, None, 2.0)]
        out = H.regime(A, e, {'risk': .5, 'sma': 3})
        self.assertEqual(out[6][0][9], .5)
        self.assertEqual(len(out[6][1]), 6)                 # the short as it was
        self.assertEqual(out[4][0][9], 2.0)                 # an up day: the tier's own multiplier stays


    def test_breadth_is_the_share_above_the_average_as_of_the_day_before(self):
        c = np.tile(np.linspace(1, 1.7, 8)[:, None], (1, 4))   # all rising: every name above its average
        c[5:, :3] = .5                                      # three of four names fall on day 5
        down = H.regime_down(arrays(c), 3, kind='breadth', below=.5)
        self.assertEqual(list(down), [False] * 6 + [True, True])

    def test_a_zero_multiplier_opens_nothing(self):
        from studies.trader_replication import system as Y
        c = np.ones((8, 2))
        c[5:] = .5
        A = arrays(c)
        e = [[] for _ in range(8)]
        e[6] = [(0, 0, 1, .5, .45, 'x')]
        e[7] = [(0, 1, 1, .5, .45, 'x')]
        e = H.regime(A, e, {'risk': 0, 'sma': 3})
        px = {'open': c, 'high': c, 'low': c, 'close': c, 'dates': DAYS, 'codes': np.array(['US.A', 'US.B'])}
        _, _, tr = Y.simulate(px, {}, Y.Rules(trail='', trims=()), e, DAYS[0], DAYS[-1])
        self.assertEqual(tr, [])



class DrawdownBrake(unittest.TestCase):
    def test_risk_scales_down_while_equity_at_the_previous_close_is_far_below_its_peak(self):
        from studies.trader_replication import system as Y
        # day 0: buy 10 with the stop at 9 (risk 20% of equity -> 2x equity); day 1: stopped at 9, equity 0.8;
        # day 2: a new long at 10, stop 9.5: 20% risk wants 4x equity, braked (20% below the peak) to half
        c = np.array([[10.0], [9.0], [10.0], [10.0]])
        low = c.copy()
        low[1] = 9.0
        px = {'open': c, 'high': c, 'low': low, 'close': c, 'dates': DAYS[:4], 'codes': np.array(['US.A'])}
        e = [[(0, 0, 1, 10.0, 9.0, 'x')], [], [(0, 0, 1, 10.0, 9.5, 'x')], []]

        def size(**kw):
            _, _, tr = Y.simulate(px, {}, Y.Rules(trail='', trims=(), risk=.2, max_position=10, max_gross=10,
                                                  buy_cost=0, sell_cost=0, margin_rate=0, **kw),
                                  e, DAYS[0], DAYS[3], audit=True)
            t = [t for t in tr if t['entry'] == DAYS[2]][0]
            return t['executions'][0]['shares'] * t['executions'][0]['price']
        self.assertAlmostEqual(size(), .8 * 4)
        self.assertAlmostEqual(size(dd_risk=.10, dd_risk_mult=.5), .8 * 2)
        self.assertAlmostEqual(size(dd_risk=.25, dd_risk_mult=.5), .8 * 4)    # 20% down: not past 25%


if __name__ == '__main__':
    unittest.main()
