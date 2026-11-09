"""P4 entry timing, trigger consumption and causal state checks."""
import unittest

import numpy as np

from studies.martin_luk import p4_policy as S
from studies.trader_replication import regime as R


def market(n=12, m=1):
    close = np.full((n, m), 100.)
    return dict(days=np.array([f'2025-01-{t + 1:02d}' for t in range(n)]),
        codes=np.array([f'US.T{j}' for j in range(m)]), open=close.copy(), high=close + 1,
        low=close - 2, close=close.copy(), adr=np.full((n, m), 8.), to20=np.full((n, m), 200e6))


class EntryTests(unittest.TestCase):
    def run_book(self, A, name, picks=None, original=None, ok=None):
        return S.entries(A, picks if picks is not None else {0: ['US.T0']}, name,
            original if original is not None else [[] for _ in A['days']],
            ok if ok is not None else np.ones(len(A['days']), bool))

    def test_open_uses_previous_low_and_actual_open(self):
        A = market()
        A['open'][1, 0], A['low'][1, 0] = 104., 50.
        e = self.run_book(A, 'X1_OPEN')['raw'][1][0]
        self.assertEqual(e[3], 104.)
        self.assertAlmostEqual(e[4], 104. * .96)
        self.assertEqual(e[6], e[4])
        self.assertFalse(any(self.run_book(A, 'X1_OPEN')['raw'][2:]))

    def test_gap_below_prior_low_is_rejected_without_clamping(self):
        A = market()
        A['open'][1, 0] = 90.
        out = self.run_book(A, 'X1_OPEN')
        self.assertFalse(out['raw'][1])
        self.assertEqual(out['triggers'][0]['reason'], 'invalid_stop')

    def test_prior_high_strict_touch_does_not_trigger(self):
        A = market()
        A['high'][2, 0] = 102.
        rows = self.run_book(A, 'X2_PRIOR_HIGH')['raw']
        self.assertFalse(rows[1])
        self.assertEqual(rows[2][0][3], 101.)
        self.assertFalse(any(rows[3:]))

    def test_gap_above_breakout_fills_at_open(self):
        A = market()
        A['open'][1, 0], A['high'][1, 0] = 105., 106.
        self.assertEqual(self.run_book(A, 'X2_PRIOR_HIGH')['raw'][1][0][3], 105.)

    def test_trigger_does_not_retry_after_index_rejection(self):
        A = market()
        A['high'][1:, 0] = 102.
        ok = np.ones(len(A['days']), bool)
        ok[1] = False
        out = self.run_book(A, 'X2_PRIOR_HIGH', ok=ok)
        self.assertTrue(out['raw'][1])
        self.assertFalse(any(out['offered']))

    def test_pending_expires_after_third_session(self):
        A = market()
        A['high'][4:, 0] = 110.
        self.assertFalse(any(self.run_book(A, 'X2_PRIOR_HIGH')['raw']))

    def test_union_preserves_master_offers_and_order(self):
        A = market(m=6)
        A['high'][1] = 110.
        original = [[] for _ in A['days']]
        original[1] = [((-100 + k,), k, 1, 100., 98., 'n1', None) for k in range(4)]
        rows = self.run_book(A, 'X3_UNION', {0: ['US.T4', 'US.T5']}, original)['offered'][1]
        self.assertEqual([e[1] for e in rows], [0, 1, 2, 3])

    def test_union_deduplicates_original_stock(self):
        A = market()
        A['high'][1, 0] = 110.
        original = [[] for _ in A['days']]
        original[1] = [((0,), 0, 1, 103., 100., 'n1')]
        out = self.run_book(A, 'X3_UNION', original=original)
        self.assertEqual(len(out['raw'][1]), 1)
        self.assertEqual(out['triggers'][0]['reason'], 'master_duplicate')

    def test_three_day_queue_keeps_older_original_nomination_first(self):
        A = market(m=6)
        A['high'][2] = 105.
        out = self.run_book(A, 'X2_PRIOR_HIGH', {0: ['US.T2', 'US.T1', 'US.T0'], 1: ['US.T5', 'US.T4', 'US.T3']})
        self.assertEqual([e[1] for e in out['offered'][2]], [2, 1, 0, 5])


class RegimeTests(unittest.TestCase):
    def test_noadr_keeps_liquid_stocks_with_missing_adr(self):
        A = market(n=12)
        A['close'][:, 0] = np.arange(100., 112.)
        A['adr'][:] = np.nan
        self.assertEqual(int(S.breadth(A)['leaders'].sum()), 0)
        self.assertGreater(int(S.breadth(A, noadr=True)['leaders'].sum()), 0)

    def test_breadth_matches_p3_when_adr_is_present(self):
        from studies.martin_luk import p3_signal
        A = market()
        for k, v in S.breadth(A).items():
            np.testing.assert_array_equal(v, p3_signal.breadth(A)[k])

    def test_final_state_needs_three_days_and_has_only_two_values(self):
        from unittest.mock import patch
        A = market()
        judged = [dict(good=True, known=0, night=0)] * 5
        with patch.object(S.S, 'feedback', return_value=judged):
            out = S.timeline(A, {}, np.ones(len(A['days']), int))
        # Feedback confirms after three days; the composite then confirms after three.
        self.assertTrue(np.all(out['label'][:4] == R.WEAK))
        self.assertEqual(out['label'][4], R.UP)
        self.assertLessEqual(set(out['label']), {R.UP, R.WEAK})

    def test_either_bad_component_defends(self):
        from unittest.mock import patch
        A = market()
        judged = [dict(good=False, known=0, night=0)] * 5
        with patch.object(S.S, 'feedback', return_value=judged):
            out = S.timeline(A, {}, np.ones(len(A['days']), int))
        self.assertTrue(np.all(out['label'] == R.WEAK))

    def test_future_prices_do_not_change_completed_states(self):
        A = market(n=20)
        nominations = {0: ['US.T0'], 4: ['US.T0']}
        before = S.timeline(A, nominations, S.breadth(A)['state'])
        A['close'][12:] *= 2
        after = S.timeline(A, nominations, S.breadth(A)['state'])
        np.testing.assert_array_equal(before['label'][:12], after['label'][:12])
        self.assertEqual(before['outcomes'][:12], after['outcomes'][:12])

    def test_perturbations_drop_only_two_adr_checks(self):
        self.assertEqual(len(S.perturbations(False)), 16)
        self.assertEqual(len(S.perturbations(True)), 14)


if __name__ == '__main__':
    unittest.main()
