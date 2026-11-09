"""P3 timing, own-feedback isolation, tier budgets and unchanged entry management."""
from pathlib import Path
import tempfile
import unittest

import numpy as np

from studies.martin_luk import p3_signal as S, p3_research as P
from studies.trader_replication import allocation, regime as R


def market(n=40, m=6):
    days = np.array([str(np.datetime64('2024-01-01')+np.timedelta64(t, 'D')) for t in range(n)])
    codes = np.array([f'US.{j}' for j in range(m)])
    close = np.full((n, m), 10.)
    return dict(days=days, codes=codes, close=close, open=close.copy(), high=close+1, low=close-1,
        turnover=np.full((n, m), 200e6), to20=np.full((n, m), 200e6), adr=np.full((n, m), 5.),
        e21=close.copy(), e50=close.copy(), upgrade=np.zeros((n, m), bool),
        ordered={str(d): list(codes) for d in days}, inside={})


class P3Tests(unittest.TestCase):
    def test_confirmation_and_insufficient_feedback_do_not_backfill(self):
        confirm = S.Confirm()
        self.assertEqual([confirm.update(v) for v in (1, 1, None, 1, 1, 1, -1, -1, None)],
                         [0, 0, 0, 0, 0, 1, 1, 1, 1])

    def test_feedback_waits_for_two_completed_bars_and_expires_after_ten_nights(self):
        A = market(20, 2)
        nominations = {0: ['US.0'], 1: ['US.1'], 10: ['US.0']}
        ci = {'US.0': 0, 'US.1': 1}
        self.assertEqual(S.feedback(A, 2, nominations, ci), [])
        first = S.feedback(A, 3, nominations, ci)
        self.assertEqual([(r['night'], r['known'], r['good']) for r in first], [(0, 2, True)])
        A['close'][3, 1] = 8.
        later = S.feedback(A, 4, nominations, ci)
        self.assertEqual([r['good'] for r in later], [True, False])
        self.assertEqual(S.feedback(A, 12, nominations, ci), [])
        self.assertEqual([r['night'] for r in S.feedback(A, 13, nominations, ci)], [10])

    def test_candidate_feedback_uses_exact_S_new_names_and_future_tail_is_irrelevant(self):
        A = market(45)
        width = np.ones(45, np.int8)
        full = S.timeline(A, 'C4_STATE', width)
        self.assertEqual(full['new'], allocation.nominations(full['picks'], maximum=3, cooldown=10))
        self.assertTrue(all(r['latest_known'] is None or r['latest_known'] < r['day'] for r in full['outcomes']))
        for key in ('close', 'low', 'e21'):
            A[key][25:] *= 9
        changed = S.timeline(A, 'C4_STATE', width)
        self.assertEqual(full['outcomes'][:25], changed['outcomes'][:25])
        self.assertEqual([full['picks'][t] for t in range(25)], [changed['picks'][t] for t in range(25)])
        view = {k: v[:25] if isinstance(v, np.ndarray) and k != 'codes' else v for k, v in A.items()}
        prefix = S.timeline(view, 'C4_STATE', width[:25])
        self.assertEqual(prefix['picks'], {t: full['picks'][t] for t in range(25)})
        np.testing.assert_array_equal(prefix['label'], full['label'][:25])

    def test_tier_reservations_preserve_each_tiers_order_and_fill_up_to_five(self):
        names = list('abcdef')
        tiers = dict(zip(names, [0, 1, 2, 2, 1, 0]))
        upgrades = dict(zip(names, [False, True, True, True, False, False]))
        self.assertEqual(S.tier_order(names, tiers, upgrades), list('cdb ae'.replace(' ', '')))
        self.assertEqual(S.tier_order(['a'], {'a': 2}, {'a': False}), ['a'])

    def test_near21_does_not_reward_one_ADR_over_three_ADR(self):
        A = market(2, 3)
        A['close'][:] = [10.5, 11.5, 12.5]
        A['e21'][:] = 10
        A['inside'] = {str(d): {c: 0. for c in A['codes']} for d in A['days']}
        # Both within four ADRs tie, even with their original order reversed.
        A['ordered'][str(A['days'][0])] = ['US.1', 'US.0', 'US.2']
        result = S.order(A, 0, 'C2_NEAR21', R.PULLBACK, {c: j for j, c in enumerate(A['codes'])})
        self.assertEqual(result, ['US.1', 'US.0', 'US.2'])

    def test_defensive_signal_is_large_tier_only_and_single_mode_ignores_failed_states(self):
        A = market(4, 3)
        A['to20'][:] = [50e6, 200e6, 2e9]
        columns = {c: j for j, c in enumerate(A['codes'])}
        for candidate in ('C4_STATE', 'C5_COMBO'):
            self.assertEqual(S.order(A, 0, candidate, R.WEAK, columns), ['US.2'])
        result = S.timeline(A, 'C4_STATE', -np.ones(4), single=True)
        self.assertTrue(np.all(result['label'] == R.PULLBACK))
        self.assertEqual(len(result['picks'][0]), 3)

    def test_first_retest_is_consumed_before_any_account_or_state_filter(self):
        close = np.array([11., 9., 9., 9., 11., 9., 9.])
        high = np.array([12., 9., 10., 11., 12., 9., 10.])
        result = S.first_retests(close, high, np.full(7, 10.))
        self.assertEqual(np.flatnonzero(result).tolist(), [2, 6])

    def test_later_high_cannot_validate_an_earlier_Z15_fill_below_50_EMA(self):
        A = market(2, 2)
        A['e50'][:] = 11.
        A['weekly_bad'] = np.ones((2, 2), bool)
        early = (0., 0, -1, 10., 10.5, 's_Z15', None)
        observed = (1., 1, -1, 12., 12.5, 's_Z15', None)
        entries = [[], [early, observed]]
        self.assertEqual(P.first_short_entries(A, entries, np.ones((2, 2), bool)), [[], [observed]])

    def test_market_features_and_completed_week_filter_are_prefix_causal(self):
        A = market(32, 2)
        A['close'][:, 0] += np.arange(32)*.1
        with tempfile.TemporaryDirectory() as folder:
            full = P.derive(A, Path(folder)/'full')
            for cut in (10, 17, 24):
                view = {k: v[:cut] if isinstance(v, np.ndarray) and k != 'codes' else v for k, v in A.items()}
                short = P.derive(view, Path(folder)/str(cut))
                for key in full:
                    np.testing.assert_array_equal(short[key], full[key][:cut], err_msg=key)

    def test_paired_account_filters_only_new_entries_and_keeps_fill_stop_kind(self):
        A = market(3, 2)
        long = (99., 0, 1, 10., 9.5, 'n1', None)
        short = (-1., 1, -1, 10., 10.5, 's_Z15', 10.5)
        labels = [R.UP, R.PULLBACK, R.WEAK]
        picks = {str(d): ['US.0'] for d in A['days']}
        book = P.candidate_book(A, picks, [[long]]*3, [[short]]*3, labels, True)
        self.assertEqual([[e[2] for e in row] for row in book], [[1], [1], [-1]])
        self.assertEqual(book[0][0][1:], long[1:])
        self.assertEqual(book[2][0][1:], short[1:])


if __name__ == '__main__':
    unittest.main()
