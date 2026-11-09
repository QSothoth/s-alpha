"""Margin calls use the previous completed close and the next opening prices."""
import unittest

import numpy as np

from studies.trader_replication import system


class MarginCallTests(unittest.TestCase):
    def replay(self, closes, opens=None, sides=(1, 1, 1), method='weakest_first',
               maintenance=.45, buy_cost=0., sell_cost=0., entries_extra=None):
        closes = np.array(closes, dtype=float)
        opens = np.array(opens if opens is not None else closes, dtype=float)
        dates = np.array([f'2025-01-{i + 1:02d}' for i in range(len(closes))])
        px = dict(open=opens, high=np.maximum(opens, closes), low=np.minimum(opens, closes),
                  close=closes, dates=dates, codes=np.array(['A', 'B', 'C']))
        entries = [[] for _ in dates]
        for j, (side, cap) in enumerate(zip(sides, (.7, .8, .5))):
            entries[0].append((j, j, side, 10., 1. if side > 0 else 19., 'close', None, None, cap))
        if entries_extra:
            for day, event in entries_extra:
                entries[day].append(event)
        rules = system.Rules(risk=1., max_position=1., max_gross=2., trail='', trims=(),
                             margin_rate=0., buy_cost=buy_cost, sell_cost=sell_cost,
                             maintenance=maintenance, deleverage=method)
        track = {}
        curve, _, trades = system.simulate(px, {}, rules, entries, dates[0], dates[-1], audit=True, track=track)
        fills = [(trade['code'], event) for trade in trades for event in trade['executions']
                 if event['action'] == 'margin_call']
        return curve, track, trades, fills

    def test_close_breach_sells_next_open_and_uses_gap_price(self):
        close = [[10, 10, 10], [8, 9, 9], [7, 8, 9]]
        curve, track, _, fills = self.replay(close, opens=[[10, 10, 10], [10, 10, 10], [7, 8, 9]])
        self.assertAlmostEqual(curve[1], .73)
        self.assertGreater(track['gross'][1], 1/.45)
        self.assertEqual([(name, e['time'], e['price']) for name, e in fills], [('A', '2025-01-03', 7.)])
        self.assertAlmostEqual(fills[0][1]['shares'], .42/7)
        self.assertAlmostEqual(track['gross'][2], 2.)
        self.assertEqual(fills[0][1]['why'], 'margin_call')
        _, _, _, before_open = self.replay(close[:2], opens=[[10, 10, 10], [10, 10, 10]])
        self.assertFalse(before_open)

    def test_three_methods_select_positions_and_amounts(self):
        close = [[10, 10, 10], [8, 9, 9], [7, 8, 9]]
        for method, expected in (
            ('weakest_first', {'A': .42/7}),
            ('largest_first', {'B': .42/8}),
            ('pro_rata', {'A': .07*.42/1.58, 'B': .08*.42/1.58, 'C': .05*.42/1.58}),
        ):
            with self.subTest(method=method):
                _, track, _, fills = self.replay(close, method=method)
                self.assertEqual({name for name, _ in fills}, set(expected))
                for name, event in fills:
                    self.assertAlmostEqual(event['shares'], expected[name])
                self.assertAlmostEqual(track['gross'][-1], 2.)

    def test_between_initial_and_maintenance_no_forced_sale(self):
        _, track, _, fills = self.replay([[10, 10, 10], [9.5, 9.5, 9.5], [9.5, 9.5, 9.5]])
        self.assertGreater(track['gross'][1], 2.)
        self.assertLess(track['gross'][1], 1/.45)
        self.assertFalse(fills)

    def test_short_market_value_counts_as_gross(self):
        close = [[10, 10, 10], [12, 11, 11], [13, 12, 11]]
        _, track, _, fills = self.replay(close, sides=(-1, -1, -1))
        self.assertGreater(track['gross'][1], 1/.45)
        self.assertEqual([name for name, _ in fills], ['A', 'B'])
        self.assertAlmostEqual(fills[0][1]['shares'], .07)
        self.assertAlmostEqual(fills[1][1]['shares'], .35/12)
        self.assertAlmostEqual(track['gross'][-1], 2.)

    def test_recovery_by_next_open_cancels_the_sale(self):
        _, track, _, fills = self.replay([[10, 10, 10], [8, 9, 9], [10, 10, 10]])
        self.assertEqual(len(track['margin_calls']), 1)
        self.assertFalse(fills)
        self.assertAlmostEqual(track['gross'][-1], 2.)

    def test_add_is_blocked_between_initial_and_maintenance(self):
        close = np.array([[10., 10., 10.], [10.5, 8.5, 10.]])
        px = dict(open=close, high=close, low=close, close=close,
                  dates=np.array(['2025-01-01', '2025-01-02']), codes=np.array(['A', 'B', 'C']))
        entries = [[(0, 0, 1, 10., 1., 'close', None, None, 1.),
                    (1, 1, 1, 10., 1., 'close', None, None, 1.)], []]
        rules = system.Rules(risk=1., max_position=2., max_gross=2., maintenance=.4,
            trail='', trims=(), buy_cost=0., sell_cost=0., margin_rate=0.,
            add_signal='signal', add_signal_frac=1., add_signal_profit=True)
        track = {}
        _, _, trades = system.simulate(px, {'signal': np.ones_like(close, bool)}, rules,
                                       entries, *px['dates'], audit=True, track=track)
        self.assertGreater(track['gross'][-1], 2.)
        self.assertLess(track['gross'][-1], 1/.4)
        self.assertFalse(any(e['action'] == 'add' for t in trades for e in t['executions']))

    def test_transaction_cost_is_included_in_target(self):
        _, track, _, fills = self.replay([[10, 10, 10], [8, 9, 9], [7, 8, 9]], sell_cost=.01)
        self.assertTrue(fills)
        self.assertLessEqual(track['gross'][-1], 2. + 1e-12)

    def test_missing_open_waits_without_using_stale_price_as_a_fill(self):
        close = [[10, 10, 10], [8, 9, 9], [8, 9, 9], [7, 8, 9]]
        opens = [[10, 10, 10], [10, 10, 10], [np.nan, np.nan, np.nan], [7, 8, 9]]
        for method in ('weakest_first', 'pro_rata', 'largest_first'):
            with self.subTest(method=method):
                _, track, _, fills = self.replay(close, opens=opens, method=method)
                self.assertTrue(fills)
                self.assertTrue(all(event['time'] == '2025-01-04' for _, event in fills))
                self.assertLessEqual(track['gross'][-1], 2. + 1e-12)

    def test_no_new_position_between_lines(self):
        close = np.array([[10., 10., 10.], [9., 9., 10.]])
        px = dict(open=close, high=close, low=close, close=close,
                  dates=np.array(['2025-01-01', '2025-01-02']), codes=np.array(['A', 'B', 'C']))
        entries = [[(0, 0, 1, 10., 1., 'close'), (1, 1, 1, 10., 1., 'close')],
                   [(0, 2, 1, 10., 1., 'close')]]
        rules = system.Rules(risk=1., max_position=1., max_gross=2., maintenance=.4, gross_close=True,
                             trail='', trims=(), buy_cost=0., sell_cost=0., margin_rate=0.)
        track = {}
        _, _, trades = system.simulate(px, {}, rules, entries, *px['dates'], audit=True, track=track)
        self.assertGreater(track['gross'][-1], 2.)
        self.assertLess(track['gross'][-1], 1/.4)
        self.assertEqual({t['code'] for t in trades}, {'A', 'B'})
        self.assertFalse(track.get('margin_calls'))

    def test_invalid_maintenance_and_method_are_rejected(self):
        for options in ({'maintenance': 0.}, {'maintenance': .6},
                        {'maintenance': float('nan')}, {'method': 'unknown'}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.replay([[10, 10, 10]], **options)


if __name__ == '__main__':
    unittest.main()
