"""Y2's optional time attribution conserves fills, money and held sessions."""
import unittest

import numpy as np

from studies.trader_replication import mainleg as M
from studies.trader_replication.tests.test_mainleg_account import trade


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.calendar = [str(d) for d in np.arange('2024-01-01', '2024-04-10', dtype='datetime64[D]')]
        close = np.arange(100., 200.)
        low = close-1
        low[30] = 1.
        self.prices = {'X': dict(c=close, o=close.copy(), h=close.copy(), l=low)}
        self.leg = dict(key='x', code='X', first=50, peak=70, top=200., gain=1.,
                        precision='exact', censored=False, entries=[dict(index=50, gain=1.)])

    def summary(self, ts, legs=None, **kwargs):
        return M.summary_account(ts, [self.leg] if legs is None else legs,
                                 self.prices, self.calendar, lifecycle=True, **kwargs)

    def test_old_default_remains_entry_attribution(self):
        ts = [trade([(10, 1., 110.), (80, -1., 180.)])]
        old = M.summary_account(ts, [self.leg], self.prices, self.calendar)
        self.assertEqual(old['years']['2024']['H'], 0.)
        self.assertEqual(old['lots'], M.attribute_lots(ts, [self.leg], self.prices, self.calendar))
        self.assertEqual(self.summary(ts)['years']['2024']['H'], 41.)

    def test_lot_crosses_both_boundaries_and_only_inside_days_count(self):
        out = self.summary([trade([(10, 1., 110.), (80, -1., 180.)])], equity=np.ones(100))
        self.assertEqual([r['pnl'] for r in out['lots']], [19., 41., 10.])
        self.assertEqual([r['bucket'] for r in out['lots']], ['other', 'T1', 'other'])
        self.assertEqual(out['years']['2024']['O'], 29.)
        np.testing.assert_array_equal(out['daily']['his'][30:71], np.arange(130., 171.))
        self.assertEqual(out['daily']['his'][29]+out['daily']['his'][71], 0.)
        np.testing.assert_array_equal(out['daily']['gross'][10:80], np.arange(110., 180.))

    def test_cost_and_first_holding_clock_are_not_boundary_fill(self):
        out = self.summary([trade([(10, 1., 180.), (80, -1., 180.)])])
        g = out['legs'][0]
        self.assertEqual(g['first_fill'], dict(index=30, actual_entry=10, price=180.))
        self.assertFalse(g['covered'])
        self.assertAlmostEqual(g['potential_total'], 180.)
        self.assertEqual(out['years']['2024']['H'], 41.)

    def test_later_add_does_not_reset_early_clock(self):
        out = self.summary([trade([(10, 1., 180.), (40, 1., 100.), (80, -2., 180.)])])
        self.assertFalse(out['legs'][0]['covered'])
        self.assertEqual(out['legs'][0]['first_fill']['actual_entry'], 10)

    def test_window_includes_peak_day_but_not_next_day(self):
        at_peak = self.summary([trade([(70, 1., 170.), (72, -1., 172.)])])
        self.assertTrue(at_peak['legs'][0]['any'])
        self.assertEqual(at_peak['daily']['his'][70], 170.)
        self.assertEqual(at_peak['daily']['his'][71], 0.)
        self.assertFalse(self.summary([trade([(71, 1., 171.), (72, -1., 172.)])])['legs'][0]['any'])

    def test_sale_on_start_has_pnl_but_no_end_of_day_inventory(self):
        out = self.summary([trade([(10, 1., 110.), (30, -1., 130.)])])
        self.assertEqual(out['years']['2024']['H'], 1.)
        self.assertEqual(out['daily']['his'].sum(), 0.)
        before = self.summary([trade([(10, 1., 110.), (29, -1., 129.)])])
        self.assertFalse(before['legs'][0]['any'])

    def test_actual_fill_used_when_bought_inside(self):
        out = self.summary([trade([(40, 1., 135.), (60, -1., 161.)])])
        self.assertEqual(out['years']['2024']['H'], 26.)
        self.assertEqual(out['legs'][0]['first_fill']['price'], 135.)

    def test_fees_and_residual_stay_on_actual_sides(self):
        fills = [dict(index=10, quantity=1., price=110., fee=2.),
                 dict(index=80, quantity=-1., price=180., fee=3.)]
        ts = [dict(id='fee', code='X', entry=10, closed=True, pnl=64., lots=M.lots(fills, pnl=64.))]
        out = self.summary(ts)
        self.assertEqual([r['pnl'] for r in out['lots']], [17., 41., 6.])
        self.assertEqual(sum(r['residual'] for r in out['lots']), -1.)
        self.assertEqual(sum(r['buy_fee']+r['sell_fee'] for r in out['lots']), 5.)

    def test_same_ticker_overlaps_never_double_count(self):
        later = dict(self.leg, key='later', first=55, peak=80, top=220., gain=1.2)
        ts = [trade([(10, 1., 110.), (90, -1., 190.)])]
        out = self.summary(ts, [self.leg, later])
        reverse = self.summary(ts, [later, self.leg])
        self.assertEqual(out['years'], reverse['years'])
        self.assertEqual(out['legs'][0]['pnl'], 0.)
        self.assertEqual(sum(g['pnl'] for g in out['legs']), 51.)
        self.assertTrue(np.all(out['daily']['his'] <= out['daily']['gross']))

    def test_one_original_lot_can_fund_two_disjoint_legs(self):
        self.prices['X']['l'][80] = .5
        later = dict(self.leg, key='later', first=85, peak=95, top=250., gain=1.5)
        out = self.summary([trade([(10, 1., 110.), (99, -1., 199.)])], [self.leg, later])
        self.assertEqual([g['window_start'] for g in out['legs']], [30, 80])
        self.assertEqual([g['pnl'] for g in out['legs']], [41., 16.])
        self.assertEqual(out['daily']['his'][75], 0.)
        self.assertAlmostEqual(out['years']['2024']['H']+out['years']['2024']['O'], 89.)

    def test_partial_fifo_sales_conserve_original_size(self):
        out = self.summary([trade([(10, 2., 110.), (40, -1., 140.), (80, -1., 180.)])])
        self.assertEqual(out['years']['2024']['H'], 52.)
        self.assertEqual(out['legs'][0]['potential_total'], 220.)
        self.assertEqual(out['daily']['his'][39], 278.)
        self.assertEqual(out['daily']['his'][40], 140.)

    def test_cash_days_stay_in_equity_denominator(self):
        ts = [trade([(10, 1., 110.), (80, -1., 180.)])]
        a = self.summary(ts, equity=np.full(100, 1000.))['years']['2024']
        self.calendar.append('2024-04-10')
        b = self.summary(ts, equity=np.full(101, 1000.))['years']['2024']
        self.assertEqual(a['cap_share'], b['cap_share'])
        self.assertAlmostEqual(a['cap_equity']*100, b['cap_equity']*101)

    def test_terminal_valuation_keeps_last_close_exposure(self):
        t = trade([(10, 1., 110.), (70, -1., 170.)])
        t['closed'] = False
        t['lots'][0]['open'] = True
        out = self.summary([t])
        self.assertEqual(out['daily']['his'][70], 170.)
        self.assertEqual(out['years']['2024']['top10'], [])

    def test_censor_exclusion_does_not_reassign_overlapping_piece(self):
        later = dict(self.leg, key='later', first=55, peak=80, top=220., censored=True)
        out = self.summary([trade([(10, 1., 110.), (90, -1., 190.)])], [self.leg, later])
        self.assertEqual(out['years']['2024']['excluding_censored']['H'], 0.)
        self.assertEqual(out['legs'][0]['pnl'], 0.)

    def test_rolling_low_has_fixed_60_session_lookback(self):
        self.prices['X']['l'][9] = .1
        g = M.lifecycle_windows([self.leg], self.prices)[0]
        self.assertEqual(g['window_start'], 30)
        self.assertNotIn('window_start', self.leg)


if __name__ == '__main__':
    unittest.main()
