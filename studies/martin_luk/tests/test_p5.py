"""P5 causal nominations, percentile breadth, and opening close-stop behavior."""
import unittest
from unittest.mock import patch

import numpy as np

from studies.martin_luk import p5_policy as S
from studies.trader_replication import regime as R, system as Y


def market(n=14, m=1):
    close = np.full((n, m), 100.)
    return dict(days=np.array([f'2025-01-{t + 1:02d}' for t in range(n)]),
        codes=np.array([f'US.T{j}' for j in range(m)]), open=close.copy(), high=close + 2,
        low=close - 1, close=close.copy(), adr=np.full((n, m), 8.), to20=np.full((n, m), 200e6), ordered={})


class OpeningStops(unittest.TestCase):
    def run_account(self, A, *, soft=True, picks=None, no_rebuy=False):
        book = S.entries(A, picks or {0: ['US.T0']}, np.ones(len(A['days']), bool), soft=soft)['offered']
        rules = Y.Rules(trail='', trims=(), margin_rate=0., close_stop_days=5 if soft else 0,
                        intraday_kinds=('p4_open',), no_rebuy_day=no_rebuy)
        px = dict(dates=A['days'], **{k: A[k] for k in ('codes', 'open', 'high', 'low', 'close')})
        return Y.simulate(px, {}, rules, book, str(A['days'][0]), str(A['days'][-1]),
                          audit=True, entry_close_stops=soft)[2]

    def test_day_zero_recovery_survives_only_soft_stop(self):
        A = market()
        A['low'][0, 0], A['low'][1, 0] = 98., 97.
        self.assertEqual(self.run_account(A)[0]['why'], 'end')
        self.assertEqual(self.run_account(A, soft=False)[0]['why'], 'stop_day0')

    def test_day_zero_close_breach_fills_at_close(self):
        A = market()
        A['low'][0, 0], A['low'][1, 0], A['close'][1, 0] = 98., 97., 97.5
        t = self.run_account(A)[0]
        self.assertEqual((t['why'], t['executions'][-1]['price']), ('close_stop', 97.5))

    def test_hard_stop_wins_over_recovered_close(self):
        A = market()
        A['low'][0, 0], A['low'][1, 0] = 98., 95.
        t = self.run_account(A)[0]
        self.assertEqual((t['why'], t['executions'][-1]['price']), ('stop_day0', 96.))

    def test_fifth_day_soft_sixth_day_restores_original(self):
        A = market()
        A['low'][0, 0] = 98.
        A['low'][1:7, 0] = 97.
        t = self.run_account(A)[0]
        self.assertEqual((t['days'], t['why'], t['executions'][-1]['price']), (5, 'stop', 98.))

    def test_gap_through_hard_stop_fills_at_open(self):
        A = market()
        A['low'][0, 0], A['open'][2, 0], A['low'][2, 0] = 98., 95., 94.
        t = self.run_account(A)[0]
        self.assertEqual((t['why'], t['executions'][-1]['price']), ('gap_stop', 95.))

    def test_normal_nomination_can_open_next_day_after_stop(self):
        A = market()
        A['low'][0, 0], A['low'][1, 0], A['close'][1, 0] = 98., 97., 97.5
        trades = self.run_account(A, picks={0: ['US.T0'], 1: ['US.T0']}, no_rebuy=True)
        self.assertEqual([t['entry'] for t in trades], [str(A['days'][1]), str(A['days'][2])])

    def test_peak_eve_sale_is_flat_but_terminal_valuation_is_still_held(self):
        from studies.martin_luk.p5_research import coverage
        A = market()
        A['low'][0, 0] = 98.
        trades = self.run_account(A)
        self.assertEqual(trades[0]['why'], 'end')
        eve = str(A['days'][4])
        trades[0]['exit'] = eve
        trades[0]['executions'][-1]['time'] = eve
        record = dict(trades=trades, curve=dict(days=list(A['days'][:5])))
        leg = dict(key='test', code='US.T0', first=1, peak=5, gain=.3, top=130.)
        rules = Y.Rules()
        valued = coverage(A, record, rules, [leg])['per_leg'][0]
        self.assertTrue(valued['peak_held'])
        trades[0]['why'] = 'trail'
        trades[0]['executions'][-1]['action'] = 'trail'
        sold = coverage(A, record, rules, [leg])['per_leg'][0]
        self.assertFalse(sold['peak_held'])


class SignalsAndStates(unittest.TestCase):
    def test_uncooked_order_top_three_can_repeat(self):
        A = market(m=6)
        A['ordered'] = {str(d): list(A['codes']) for d in A['days']}
        no_block = S.nominations(A, 'S1_NOBLOCK')
        cooled = S.nominations(A, 'S2_CLOSESTOP')
        self.assertEqual(no_block[0], no_block[1])
        self.assertEqual(no_block[1], list(A['codes'][:3]))
        self.assertEqual(cooled[1], list(A['codes'][3:]))

    def test_percentile_threshold_moves_with_whole_market_volatility(self):
        A = market(m=10)
        A['adr'][:] = np.arange(1., 11.)
        a = S.breadth(A)
        A['adr'] *= .1
        b = S.breadth(A)
        np.testing.assert_array_equal(a['pool_size'], np.full(len(A['days']), 3))
        np.testing.assert_array_equal(a['net'], b['net'])
        np.testing.assert_allclose(a['adr_cutoff'] * .1, b['adr_cutoff'])

    def test_breadth_prefix_is_unchanged_by_future_prices_and_liquidity(self):
        A = market(m=4)
        A['close'][:] = np.arange(100., 114.)[:, None]
        a = S.breadth(A)
        A['close'][8:] *= .1
        A['to20'][8:] = 0.
        b = S.breadth(A)
        for key in a:
            np.testing.assert_array_equal(a[key][:8], b[key][:8])

    def test_feedback_uses_only_completed_second_close(self):
        from studies.martin_luk.p3_signal import feedback
        A = market()
        picks = {0: ['US.T0']}
        self.assertEqual(feedback(A, 2, picks, {'US.T0': 0}), [])
        self.assertEqual(feedback(A, 3, picks, {'US.T0': 0})[0]['known'], 2)

    def test_final_state_requires_three_confirmed_inputs(self):
        A = market(n=10)
        judged = [dict(good=True, known=0, night=0) for _ in range(5)]
        with patch.object(S.S, 'feedback', return_value=judged):
            row = S.timeline(A, {}, np.ones(10), 'B4_PCT2')
        self.assertEqual(row['label'][:4].tolist(), [R.WEAK] * 4)
        self.assertEqual(row['label'][4], R.UP)

    def test_two_state_mixed_input_is_defensive(self):
        A = market()
        with patch.object(S.S, 'feedback', return_value=[]):
            a = S.timeline(A, {}, np.ones(len(A['days'])), 'B4_PCT2')
            b = S.timeline(A, {}, np.ones(len(A['days'])), 'B3_PCT3')
        self.assertEqual(set(a['label']), {R.WEAK})
        self.assertEqual(set(b['label']), {R.PULLBACK})


if __name__ == '__main__':
    unittest.main()
