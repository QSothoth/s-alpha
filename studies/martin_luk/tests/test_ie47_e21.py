"""E21 measures real close fills without changing the frozen S1 account."""
import unittest

import numpy as np

from studies.martin_luk import e21_review as R


class E21Tests(unittest.TestCase):
    def test_mainleg_limits_use_actual_close_and_remaining_percentage(self):
        c = np.full((16, 1), 10.)
        c[6, 0], c[7, 0] = 12., 12.01
        A = dict(codes=['US.X'], close=c, high=np.full_like(c, 18.), low=np.full_like(c, 8.), open=c*2)
        leg = dict(code='US.X', peak=12, top=18., entries=[dict(index=5, label='x', gain=1.)], censored=False)
        # Half of a 100% move remains at 12, not halfway in absolute dollars.
        c[8, 0], c[9, 0] = 12., 12.01
        got = R.qualified_days(leg, range(16), R.prices(A))
        self.assertNotIn(1, got)
        self.assertIn(2, got)
        self.assertIn(8, got)
        self.assertNotIn(9, got)
        self.assertNotIn(12, got)

    def test_lifecycle_position_uses_low_and_high(self):
        self.assertEqual(R.position(12., dict(low=8., top=20.)), 1/3)

    def test_end_mark_is_not_a_realized_win_and_any_realized_win_counts(self):
        end = dict(pnl=1., why='end')
        loss = dict(pnl=-.1, why='stop')
        win = dict(pnl=.2, why='trail')
        self.assertEqual(R.stage([], [], [], [end]), 'bought_lost')
        self.assertEqual(R.stage([], [], [], [loss, win]), 'bought_won')
        self.assertEqual(R.stage([], [], [dict(day='x')], []), 'triggered_blocked')

    def test_same_stock_peak_merges_duplicate_and_later_entry(self):
        p = {'US.X': dict(c=np.full(80, 10.), h=np.r_[np.full(20, 11.), 30., np.full(59, 11.)],
                          l=np.full(80, 8.), o=np.full(80, 10.))}
        legs = R.mainleg.legs([('US.X', 2, 'a'), ('US.X', 2, 'b'), ('US.X', 4, 'c')], p, big=-np.inf)
        self.assertEqual(len(legs), 1)
        self.assertEqual(len(legs[0]['entries']), 2)

    def test_winner_cohorts_reconcile_and_recent_nonwinner_is_censored(self):
        A = dict(days=np.array(['2024-01-02', '2024-01-03', '2024-01-04']), codes=['US.X'],
                 high=np.array([[10.], [14.], [10.]]))
        rows = [dict(code='US.X', entry='2024-01-02', fill=10., pnl=.3, why='stop'),
                dict(code='US.X', entry='2024-01-04', fill=10., pnl=-.1, why='end')]
        out = R.big_winners(A, rows)['all']
        self.assertEqual((out['big_tickers'], out['big_trades'], out['unknown']), (1, 1, 1))
        self.assertAlmostEqual(out['big_pnl']+out['other_pnl'], .2)
        self.assertEqual(out['other_realized'], 0.)

    def test_no_breakout_and_expired_observation_are_different(self):
        n = 20
        A = dict(days=np.array([f'2024-01-{d+1:02d}' for d in range(n)]),
                 open=np.full((n, 1), 10.),
                 close=np.full((n, 1), 10.), high=np.full((n, 1), 11.),
                 low=np.full((n, 1), 9.8), adr=np.full((n, 1), 6.))
        leg = dict(entries=[dict(index=10)], peak=15)
        self.assertEqual(R.no_trigger(A, 0, leg, {10, 11}, [], [], [1])['reason'], 'no_breakout')
        A['close'][10] = 12.
        self.assertEqual(R.no_trigger(A, 0, leg, {10, 11}, [], [], [1])['reason'], 'observation_expired')
        A['adr'][9] = np.nan
        self.assertEqual(R.no_trigger(A, 0, leg, {10}, [], [], [1])['reason'], 'invalid_stop')

    def test_missing_panel_label_keeps_the_record_without_inventing_a_leg(self):
        h = dict(id='x', entry_date='2024-01-02', window_lo='2024-01-02', window_hi='2024-01-03', precision='exact')
        self.assertIsNone(R.raw_leg('US.MISSING', 1, 'x', {}))
        r = R.missing_label(h, 'US.MISSING', h['entry_date'])
        self.assertEqual((r['id'], r['category']), ('x', 'not_in_pool'))
        self.assertIsNone(r['leg_key'])
        self.assertIsNone(r['his_position'])


if __name__ == '__main__':
    unittest.main()
