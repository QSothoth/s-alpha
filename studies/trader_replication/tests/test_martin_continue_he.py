import unittest

import numpy as np

from studies.trader_replication.system import Rules, simulate


class GapMarketOnCloseTest(unittest.TestCase):
    def test_gap_exit_follows_intraday_stop_and_feedback_waits_until_next_open(self):
        days = np.array(['2025-01-01', '2025-01-02', '2025-01-03', '2025-01-06'])
        op = np.array([[10., 10., 10.], [10., 10., 10.], [10., 8., 10.], [10., 8.5, 10.]])
        low = np.array([[10., 10., 10.], [10., 10., 10.], [8.5, 7.5, 10.], [10., 8.5, 10.]])
        close = op.copy()
        close[2, 1] = 8.5
        px = {'dates': days, 'codes': np.array(['US.A', 'US.B', 'US.C']), 'open': op,
              'high': np.maximum(op, close), 'low': low, 'close': close}
        a = ((0,), 0, 1, 10., 9., 'n1', None)
        b = ((0,), 1, 1, 8., 9., 'n1', 8.5)
        c = ((0,), 2, 1, 10., 9., 'n1', None)
        book = [[], [a], [b], [c]]
        rules = Rules(trail='', trims=(), risk=.01, risk_low=.005, risk_high=.02, feedback=1,
                      feedback_prior_close=True, max_gross=5., max_position=1.,
                      intraday_kinds=('n1',), buy_cost=0., sell_cost=0., margin_rate=0.)
        track = {}
        _, _, trades = simulate(px, {}, rules, book, days[1], days[-1], audit=True, track=track,
                                preopen=True, preopen_gap_moc=True)
        self.assertEqual([(t['code'], t['why']) for t in trades],
                         [('US.A', 'stop'), ('US.B', 'gap_moc'), ('US.C', 'end')])
        self.assertEqual(trades[1]['executions'][-1]['price'], 8.5)
        self.assertEqual(track['preopen_plans'][1]['orders'][0]['execution'], 'gap_moc')
        self.assertAlmostEqual(track['preopen_plans'][2]['fraction'], .02)

    def test_future_close_does_not_change_prior_reservation(self):
        days = np.array(['2025-01-01', '2025-01-02'])
        rules = Rules(trail='', trims=(), risk=.01, max_position=1., max_gross=1., gross_cost=True,
                      intraday_kinds=('n1',), buy_cost=0., sell_cost=0., margin_rate=0.)
        outputs = []
        for close in (7.5, 8.5):
            px = {'dates': days, 'codes': np.array(['US.A']), 'open': np.array([[10.], [8.]]),
                  'high': np.array([[10.], [max(8., close)]]), 'low': np.array([[10.], [7.]]),
                  'close': np.array([[10.], [close]])}
            book = [[], [((0,), 0, 1, 8., 9., 'n1', close)]]
            track = {}
            curve, _, trades = simulate(px, {}, rules, book, days[1], days[1], audit=True, track=track,
                                        preopen=True, preopen_gap_moc=True)
            outputs.append((curve, trades, track))
        a, b = outputs
        self.assertEqual(a[2]['preopen_plans'][0]['orders'][0]['shares'],
                         b[2]['preopen_plans'][0]['orders'][0]['shares'])
        self.assertEqual((a[1][0]['fill'], b[1][0]['fill']), (8., 8.))
        self.assertEqual((a[1][0]['executions'][-1]['price'], b[1][0]['executions'][-1]['price']), (7.5, 8.5))
        self.assertLess(a[0][-1], b[0][-1])

    def test_missing_close_fails_after_gap_order_is_eligible(self):
        days = np.array(['2025-01-01', '2025-01-02'])
        px = {'dates': days, 'codes': np.array(['US.A']), 'open': np.array([[10.], [8.]]),
              'high': np.array([[10.], [8.]]), 'low': np.array([[10.], [7.]]),
              'close': np.array([[10.], [np.nan]])}
        book = [[], [((0,), 0, 1, 8., 9., 'n1', np.nan)]]
        rules = Rules(trail='', trims=(), intraday_kinds=('n1',))
        with self.assertRaisesRegex(ValueError, 'valid same-day close'):
            simulate(px, {}, rules, book, days[1], days[1], preopen=True, preopen_gap_moc=True)

    def test_missing_close_for_unsubmitted_order_does_not_abort(self):
        days = np.array(['2025-01-01', '2025-01-02'])
        px = {'dates': days, 'codes': np.array(['US.A', 'US.B']),
              'open': np.array([[10., 10.], [10., 8.]]),
              'high': np.array([[10., 10.], [10., 8.]]),
              'low': np.array([[10., 10.], [10., 7.]]),
              'close': np.array([[10., 10.], [10., np.nan]])}
        book = [[], [((0,), 0, 1, 10., 9., 'n1', None),
                     ((1,), 1, 1, 8., 9., 'n1', np.nan)]]
        rules = Rules(trail='', trims=(), risk=.5, max_position=1., max_gross=1., gross_cost=True,
                      intraday_kinds=('n1',), buy_cost=0., sell_cost=0., margin_rate=0.)
        _, _, trades = simulate(px, {}, rules, book, days[1], days[1], audit=True,
                                preopen=True, preopen_gap_moc=True)
        self.assertEqual([t['code'] for t in trades], ['US.A'])

    def test_gap_moc_does_not_require_intraday_low(self):
        days = np.array(['2025-01-01', '2025-01-02'])
        px = {'dates': days, 'codes': np.array(['US.A']), 'open': np.array([[10.], [8.]]),
              'high': np.array([[10.], [8.5]]), 'low': np.array([[10.], [np.nan]]),
              'close': np.array([[10.], [8.5]])}
        book = [[], [((0,), 0, 1, 8., 9., 'n1', 8.5, None, None, None, None, False)]]
        rules = Rules(trail='', trims=(), intraday_kinds=('n1',))
        _, _, trades = simulate(px, {}, rules, book, days[1], days[1], audit=True,
                                preopen=True, preopen_gap_moc=True)
        self.assertEqual((trades[0]['why'], trades[0]['executions'][-1]['price']), ('gap_moc', 8.5))

    def test_moc_cannot_be_used_without_fixed_preopen_plan(self):
        days = np.array(['2025-01-01'])
        px = {'dates': days, 'codes': np.array(['US.A']), 'open': np.array([[10.]]),
              'high': np.array([[10.]]), 'low': np.array([[10.]]), 'close': np.array([[10.]])}
        with self.assertRaisesRegex(ValueError, 'requires preopen'):
            simulate(px, {}, Rules(), [[]], days[0], days[0], preopen_gap_moc=True)


if __name__ == '__main__':
    unittest.main()
