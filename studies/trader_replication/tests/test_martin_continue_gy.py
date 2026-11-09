import unittest

import numpy as np

from studies.trader_replication.martin_continue_gy import trade_contributions, summarize
from studies.trader_replication.system import Rules, simulate


class ContributionTest(unittest.TestCase):
    def test_open_long_and_short_marked_across_year_end(self):
        days = np.array(['2024-12-30', '2024-12-31', '2025-01-02', '2025-01-03'])
        opening = np.array([[10., 10.], [10., 10.], [11., 9.], [12., 8.]])
        prices = {'dates': days, 'codes': np.array(['US.LONG', 'US.SHORT']),
                  'open': opening, 'high': opening, 'low': opening, 'close': opening}
        rules = Rules(trail='', trims=(), risk=.03, max_position=.8, max_gross=2.,
                      intraday_kinds=('long', 'short'), borrow_rate=.05, margin_rate=.07)
        book = [[(0, 0, 1, 10., 8., 'long'), (1, 1, -1, 10., 12., 'short')], [], [], []]
        track = {}
        curve, dates, trades = simulate(prices, {}, rules, book, days[0], days[-1], audit=True, track=track)
        contrib, per_day = trade_contributions(trades, days, prices['codes'], prices['close'], rules, 0, 3)
        finance = summarize(curve, dates, 0, 3, per_day, track['margin'])
        self.assertEqual(len(contrib), 2)
        self.assertTrue(all(row['virtual_end_fee'] > 0 for row in contrib.values()))
        self.assertAlmostEqual(sum(per_day) + sum(finance), curve[-1] - 1.)
        self.assertGreater(contrib[('US.LONG', 1, 'long', days[0])]['by_year']['2025'], 0)
        self.assertGreater(contrib[('US.SHORT', -1, 'short', days[0])]['by_year']['2025'], 0)

    def test_partial_and_final_close_preserve_cross_year_accounting(self):
        days = np.array(['2024-12-31', '2025-01-02', '2025-01-03'])
        op = np.array([[10.], [10.], [11.]])
        close = np.array([[10.], [11.], [12.]])
        prices = {'dates': days, 'codes': np.array(['US.A']), 'open': op,
                  'high': np.array([[10.], [12.], [12.]]),
                  'low': np.array([[10.], [10.], [11.]]), 'close': close}
        rules = Rules(trail='', trims=(1,), trim_frac=.5, risk=.02, max_position=.5,
                      max_days=2, intraday_kinds=('long',))
        book = [[(0, 0, 1, 10., 9., 'long')], [], []]
        track = {}
        curve, dates, trades = simulate(prices, {}, rules, book, days[0], days[-1], audit=True, track=track)
        contributions, per_day = trade_contributions(trades, days, prices['codes'], close, rules, 0, 2)
        finance = summarize(curve, dates, 0, 2, per_day, track['margin'])
        self.assertEqual([e['action'] for e in trades[0]['executions']], ['entry', 'trim', 'time'])
        self.assertEqual(contributions[next(iter(contributions))]['virtual_end_fee'], 0)
        self.assertAlmostEqual(sum(per_day) + sum(finance), curve[-1] - 1.)

    def test_margin_is_reconciled_separately_from_marked_trades(self):
        days = np.array(['2024-12-31', '2025-01-02'])
        prices_at_open = np.full((2, 2), 10.)
        prices = {'dates': days, 'codes': np.array(['US.A', 'US.B']),
                  'open': prices_at_open, 'high': prices_at_open,
                  'low': prices_at_open, 'close': prices_at_open}
        rules = Rules(trail='', trims=(), risk=.2, max_position=.8, max_gross=2.,
                      intraday_kinds=('long',), borrow_rate=.05, margin_rate=.07)
        book = [[(0, 0, 1, 10., 8., 'long'), (1, 1, 1, 10., 8., 'long')], []]
        track = {}
        curve, dates, trades = simulate(prices, {}, rules, book, days[0], days[-1], audit=True, track=track)
        _, per_day = trade_contributions(trades, days, prices['codes'], prices['close'], rules, 0, 1)
        finance = summarize(curve, dates, 0, 1, per_day, track['margin'])
        self.assertGreater(track['margin'], 0)
        self.assertAlmostEqual(sum(finance), -track['margin'])
        self.assertAlmostEqual(sum(per_day) + sum(finance), curve[-1] - 1.)


if __name__ == '__main__':
    unittest.main()
