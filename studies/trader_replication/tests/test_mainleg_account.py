"""Account metrics use actual lots; future labels cannot enter account decisions."""
import unittest
from unittest.mock import patch

import numpy as np

from studies.trader_replication import mainleg as M


def trade(fills, code='X', name='a', pnl=None, confirmed=None):
    rows = M.lots([dict(index=i, quantity=q, price=p) for i, q, p in fills], pnl)
    return dict(id=name, code=code, entry=rows[0]['entry'], lots=rows,
                pnl=sum(r['pnl'] for r in rows), closed=True, confirmed=confirmed)


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.calendar = [f'2024-01-{i+1:02}' for i in range(30)]
        c = np.full(30, 100.)
        c[10:21] = np.linspace(100., 200., 11)
        c[21:] = 250.
        self.prices = {c_: dict(c=c.copy(), o=c.copy(), h=c.copy(), l=c.copy()) for c_ in ('X', 'Y')}
        self.leg = dict(key='x', code='X', first=10, peak=20, top=200., gain=1.,
                        censored=False, precision='exact', entries=[dict(index=10, gain=1.)])

    def summary(self, trades, legs=None, equity=None, **kw):
        return M.summary_account(trades, [self.leg] if legs is None else legs,
                                 self.prices, self.calendar, equity, **kw)

    def test_account_fill_uses_trade_fill_not_next_open(self):
        self.prices['X']['o'][13] = 150.
        out = self.summary([trade([(12, 1., 120.), (19, -1., 190.)])])
        self.assertTrue(out['legs'][0]['covered'])
        self.assertEqual(out['legs'][0]['first_fill']['price'], 120.)

    def test_peak_day_and_after_never_count(self):
        for day in (20, 21):
            out = self.summary([trade([(day, 1., 100.), (25, -1., 250.)])])
            self.assertFalse(out['legs'][0]['covered'])
            self.assertEqual(out['years']['2024']['H'], 0.)

    def test_lead_boundary_and_add_anchor_does_not_reset_gain(self):
        self.assertIsNotNone(M.leg_at('X', 7, [self.leg], 100.))
        self.assertIsNone(M.leg_at('X', 6, [self.leg], 100.))
        self.leg['entries'].append(dict(index=15, gain=.2))
        self.assertIsNotNone(M.leg_at('X', 12, [self.leg], 120.))
        self.assertIsNone(M.leg_at('X', 15, [self.leg], 160., keep=.5))

    def test_adds_use_lot_weighted_capture(self):
        out = self.summary([trade([(10, 1., 100.), (15, 2., 150.), (20, -3., 200.)])])
        g = out['legs'][0]
        self.assertAlmostEqual(g['capture_total'], 200./400.)
        self.assertAlmostEqual(g['capture_rem'], 1.)
        self.assertEqual(g['lots'], 2)

    def test_partial_exit_before_peak_lowers_capture(self):
        full = self.summary([trade([(10, 2., 100.), (20, -2., 200.)])])['legs'][0]
        part = self.summary([trade([(10, 2., 100.), (15, -1., 150.), (20, -1., 200.)])])['legs'][0]
        self.assertLess(part['capture_total'], full['capture_total'])
        self.assertLess(part['capture_rem'], full['capture_rem'])
        self.assertAlmostEqual(part['pnl'], 150.)

    def test_lots_sum_to_trade_pnl_and_residual_is_visible(self):
        t = trade([(10, 2., 100.), (12, 1., 120.), (13, -1., 130.), (20, -2., 200.)], pnl=205.)
        self.assertAlmostEqual(sum(x['pnl'] for x in t['lots']), 205.)
        self.assertAlmostEqual(sum(x['residual'] for x in t['lots']), -5.)
        self.assertEqual([x['price'] for x in t['lots']], [100., 100., 120.])

    def test_same_ticker_two_legs_one_assignment(self):
        later = dict(self.leg, key='later', first=12, top=220., gain=1.2)
        out = self.summary([trade([(12, 1., 120.), (18, -1., 180.)])], [self.leg, later])
        self.assertEqual(out['lots'][0]['leg'], 'later')
        self.assertEqual(sum(g['pnl'] for g in out['legs']), 60.)
        tied = dict(later, top=200.)
        self.assertEqual(M.leg_at('X', 12, [tied, self.leg], 120.)['key'], 'x')

    def test_ticker_outside_leg_is_t3(self):
        out = self.summary([trade([(1, 1., 100.), (3, -1., 110.)])], ticker_years={('X', '2024')})
        self.assertEqual(out['years']['2024']['buckets']['T3']['pnl'], 10.)
        self.assertEqual(out['years']['2024']['H'], 0.)

    def test_pre_entry_exit_before_his_entry(self):
        out = self.summary([trade([(7, 1., 100.), (9, -1., 110.)])], equity=np.ones(30))
        self.assertTrue(out['legs'][0]['covered'])
        self.assertEqual(out['years']['2024']['H'], 0.)
        self.assertEqual(out['years']['2024']['cap_equity'], 0.)

    def test_censored_leg_with_and_without(self):
        self.leg['censored'] = True
        s = self.summary([])['years']['2024']['coverage']
        self.assertEqual(s['including_censored']['n'], 1)
        self.assertEqual(s['including_censored']['censored_uncovered'], 1)
        self.assertEqual(s['excluding_censored']['n'], 0)
        self.assertIsNone(s['excluding_censored']['capture_total'])

    def test_gross_purity_invariant_to_outside_loss(self):
        h = trade([(10, 1., 100.), (19, -1., 190.)])
        o = trade([(1, 1., 100.), (4, -1., 110.)], 'Y', 'b')
        loss = trade([(2, 1., 100.), (5, -1., 90.)], 'Y', 'c')
        a = self.summary([h, o])['years']['2024']
        b = self.summary([h, o, loss])['years']['2024']
        self.assertAlmostEqual(a['purity_gross'], b['purity_gross'])
        self.assertLess(a['purity_net'], b['purity_net'])

    def test_net_purity_none_when_total_nonpositive(self):
        for price in (100., 90.):
            s = self.summary([trade([(1, 1., 100.), (4, -1., price)])])['years']['2024']
            self.assertIsNone(s['purity_net'])

    def test_equity_days_cash_dilutes_cap_equity(self):
        ts = [trade([(10, 1., 100.), (19, -1., 190.)])]
        a = self.summary(ts, equity=np.ones(30))['years']['2024']
        self.calendar.append('2024-02-01')
        b = self.summary(ts, equity=np.ones(31))['years']['2024']
        self.assertAlmostEqual(a['cap_share'], b['cap_share'])
        self.assertLess(b['cap_equity'], a['cap_equity'])

    def test_no_future_trade_changes_earlier_bucket(self):
        ts = [trade([(10, 1., 100.), (19, -1., 190.)])]
        before = self.summary(ts)
        after = self.summary(ts+[trade([(24, 1., 250.), (25, -1., 260.)], name='later')])
        self.assertEqual(before['lots'], after['lots'][:len(before['lots'])])
        self.assertEqual(before['legs'], after['legs'])

    def test_post_peak_pnl_not_in_t1(self):
        t = trade([(10, 1., 100.), (25, -1., 300.)])
        s = self.summary([t])
        self.assertEqual(s['years']['2024']['H'], 100.)
        self.assertEqual(s['years']['2024']['buckets']['post_peak']['pnl'], 100.)
        self.assertEqual(s['legs'][0]['capture_total'], 1.)
        self.assertEqual(s['daily']['his'][21], 0.)

    def test_confirmation_starts_on_confirmation_day(self):
        out = self.summary([trade([(10, 1., 100.), (19, -1., 190.)], confirmed=15)])
        self.assertEqual(out['daily']['confirmed'][14], 0.)
        self.assertEqual(out['daily']['confirmed'][15], 150.)
        self.assertEqual(out['daily']['gross'][19], 0.)

    def test_first_actual_fill_is_not_reset_by_add(self):
        out = self.summary([trade([(10, 1., 150.), (15, 1., 100.), (20, -2., 200.)])])
        self.assertFalse(out['legs'][0]['covered'])
        self.assertEqual(out['legs'][0]['first_fill']['price'], 150.)

    def test_other_public_small_leg_is_t2(self):
        small = dict(self.leg, key='small', code='Y', gain=.2, top=120.)
        out = self.summary([trade([(10, 1., 100.), (19, -1., 110.)], code='Y')], other_legs=[small])
        self.assertEqual(out['years']['2024']['H'], 0.)
        self.assertEqual(out['years']['2024']['buckets']['T2']['pnl'], 10.)

    def test_peak_cutoff_uses_close_not_high(self):
        self.prices['X']['c'][20] = 180.
        out = self.summary([trade([(10, 1., 100.), (25, -1., 250.)])])
        self.assertEqual(out['years']['2024']['H'], 80.)
        self.assertEqual(out['legs'][0]['capture_total'], .8)
        self.assertEqual(out['legs'][0]['avg_exit'], 180.)

    def test_fees_and_invalid_inventory(self):
        rows = M.lots([dict(index=1, quantity=2., price=100., fee=2.),
                       dict(index=2, quantity=-2., price=120., fee=3.)])
        self.assertEqual(rows[0]['pnl'], 35.)
        with self.assertRaisesRegex(ValueError, 'inventory'):
            M.lots([dict(index=1, quantity=-1., price=100.)])
        with self.assertRaisesRegex(ValueError, 'unmarked'):
            M.lots([dict(index=1, quantity=1., price=100.)])

    def test_account_decisions_do_not_read_evaluation_labels(self):
        from studies.trader_replication import system as Y
        from studies.trader_replication.tests.test_system import px, one
        prices = px([(10., 10., 10., 10.), (10., 10.2, 9.4, 9.6)])
        rules = Y.Rules(trail='', buy_cost=0., sell_cost=0., margin_rate=0.)
        with patch.object(M, 'leg_at', side_effect=AssertionError('future label read')), \
             patch.object(M, 'summary_account', side_effect=AssertionError('future account metric read')):
            _, _, trades = Y.simulate(prices, {}, rules, one(2, 0, 1, 10., 9.5),
                                      prices['dates'][0], prices['dates'][-1])
        self.assertEqual(trades[0]['why'], 'stop')


class SelectionTests(unittest.TestCase):
    setUp = AccountTests.setUp
    def diagnostics(self, picks, years=('2024', '2025')):
        return M.selection_diagnostics(picks, [self.leg], self.prices, self.calendar,
                                       {t: ['X', 'Y', 'Z', 'W'] for t in range(30)}, years)

    def test_selection_precision_training_only(self):
        self.calendar[25:] = [f'2026-01-{i+1:02}' for i in range(5)]
        a = self.diagnostics({10: ['X', 'Y', 'Z']})
        b = self.diagnostics({10: ['X', 'Y', 'Z'], 25: ['X']})
        self.assertEqual(a, b)
        future = dict(self.leg, key='future', first=25, peak=29, top=1000.)
        with_future = M.selection_diagnostics({10: ['X', 'Y', 'Z']}, [self.leg, future],
            self.prices, self.calendar, {t: ['X', 'Y', 'Z', 'W'] for t in range(30)})
        self.assertEqual(a, with_future)

    def test_selection_objective_penalizes_net_casting(self):
        focused = self.diagnostics({9: ['X'], 10: ['X']})
        broad = self.diagnostics({9: ['X', 'Y', 'Z'], 10: ['Y', 'Z', 'W']})
        self.assertEqual(focused['C_trig'], broad['C_trig'])
        self.assertGreater(focused['P_opp'], broad['P_opp'])
        self.assertGreater(focused['objective'], broad['objective'])

    def test_signal_year_uses_leg_anchor_including_previous_night(self):
        self.calendar[9] = '2023-12-29'
        out = M.selection_diagnostics({9: ['X']}, [self.leg], self.prices, self.calendar,
                                      {9: ['X']}, ('2024',), training=False)
        self.assertEqual(out['signal'], 1)
        self.assertEqual(out['trigger'], 1)

    def test_training_excludes_labels_whose_peak_needs_next_year(self):
        self.calendar[10:20] = [f'2025-12-{i+1:02}' for i in range(10)]
        self.calendar[20:] = [f'2026-01-{i+1:02}' for i in range(10)]
        out = self.diagnostics({10: ['X']})
        self.assertEqual(out['unavailable_training_labels'], 1)
        self.assertEqual(out['objective'], (0., 0., 0.))

    def test_fixed_slots_3(self):
        a = self.diagnostics({9: ['Y', 'Z', 'W', 'X']})
        self.assertEqual(a['picks'], 3)
        self.assertEqual(a['trigger'], 0)
        self.assertEqual(self.diagnostics({9: ['X', 'Y', 'Z']})['picks'], 3)
        from studies.martin_luk.ie47_e1 import select_nights
        chosen = select_nights([np.arange(5)], [np.arange(5.)], np.array(list('XYZWV')))
        self.assertEqual(len(chosen[0]), 3)


if __name__ == '__main__':
    unittest.main()
