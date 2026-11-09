import unittest

import numpy as np

from studies.trader_replication.system import Rules, simulate


class FillRelativeStopTest(unittest.TestCase):
    def run_account(self, opening, low, hit=True, cost=0.):
        days = np.array(['2025-01-01', '2025-01-02'])
        px = {'dates': days, 'codes': np.array(['US.A']), 'open': np.array([[10.], [opening]]),
              'high': np.array([[10.], [max(opening, 10.)]]), 'low': np.array([[10.], [low]]),
              'close': np.array([[10.], [opening]])}
        # The old exit must be ignored for the fill-relative order.
        book = [[], [((0,), 0, 1, opening, 9., 'list', 7.5)]]
        rules = Rules(trail='', trims=(), risk=.01, max_gross=1., max_position=1., gross_cost=True,
                      intraday_kinds=('list',), buy_cost=cost, sell_cost=cost, margin_rate=0.)
        track = {}
        curve, _, trades = simulate(px, {}, rules, book, days[1], days[1], audit=True, track=track,
                                    preopen=True, preopen_fill_stop_pct_by_kind={'list': .025},
                                    preopen_fill_stop_hit=hit)
        return curve, trades, track['preopen_plans'][0]

    def test_next_open_and_low_do_not_change_reserved_shares_or_risk(self):
        _, first, a = self.run_account(8., 7.9, cost=.001)
        _, _, b = self.run_account(11., np.nan, cost=.001)
        x, y = a['orders'][0], b['orders'][0]
        self.assertEqual((x['shares'], x['limit'], x['planned_loss_per_share']),
                         (y['shares'], y['limit'], y['planned_loss_per_share']))
        self.assertAlmostEqual(x['planned_loss_per_share'], 10.5 * (1.001 - .975 * .999))
        self.assertLessEqual(x['shares'] * x['planned_loss_per_share'], .01 + 1e-12)
        self.assertEqual(y['execution'], 'limit_expired')
        self.assertEqual(first[0]['why'], 'end')
        self.assertAlmostEqual(first[0]['stop'], 7.8)

    def test_filled_order_missing_low_is_unknown(self):
        with self.assertRaisesRegex(ValueError, 'no valid same-day low'):
            self.run_account(8., np.nan)

    def test_float_boundary_has_two_paths_with_same_reservation(self):
        _, hit, a = self.run_account(10., 9.75, True)
        _, nohit, b = self.run_account(10., 9.75, False)
        self.assertEqual(a['orders'][0]['shares'], b['orders'][0]['shares'])
        self.assertTrue(a['orders'][0]['stop_precision_unknown'])
        self.assertEqual(hit[0]['why'], 'stop_day0')
        self.assertEqual(nohit[0]['why'], 'end')

    def test_confirmed_add_uses_actual_fill_stop_as_risk_unit(self):
        days = np.array(['2025-01-01', '2025-01-02', '2025-01-03', '2025-01-06'])
        opens = np.array([[10.], [10.], [10.], [10.3]])
        closes = np.array([[10.], [10.], [10.3], [10.3]])
        px = {'dates': days, 'codes': np.array(['US.A']), 'open': opens, 'close': closes,
              'high': np.maximum(opens, closes), 'low': np.array([[10.], [9.9], [9.9], [10.2]])}
        book = [[], [((0,), 0, 1, 10., 9., 'list', None)], [], []]
        rules = Rules(trail='', trims=(), risk=.01, max_gross=2., max_position=1.,
                      intraday_kinds=('list',), buy_cost=0., sell_cost=0., margin_rate=0.,
                      add_levels=(1,), add_next_open=True, add_frac=.5)
        track = {}
        _, _, trades = simulate(px, {}, rules, book, days[1], days[-1], audit=True, track=track,
                                preopen=True, preopen_fill_stop_pct_by_kind={'list': .025})
        self.assertAlmostEqual(trades[0]['stop'], 9.75)
        adds = [x for x in trades[0]['executions'] if x['action'] == 'add']
        self.assertEqual([(x['time'], x['price']) for x in adds], [('2025-01-06', 10.3)])
        self.assertAlmostEqual(track['preopen_plans'][-1]['orders'][0]['level'], 10.25)

    def test_relative_stop_cannot_run_without_preopen(self):
        days = np.array(['2025-01-01'])
        one = np.array([[10.]])
        px = {'dates': days, 'codes': np.array(['US.A']), 'open': one, 'high': one, 'low': one, 'close': one}
        with self.assertRaisesRegex(ValueError, 'require preopen'):
            simulate(px, {}, Rules(), [[]], days[0], days[0], preopen_fill_stop_pct_by_kind={'list': .025})


if __name__ == '__main__':
    unittest.main()
