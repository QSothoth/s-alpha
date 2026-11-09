"""Small behavioral checks for U1, plus real-data causal prefix verification."""
import unittest

import numpy as np

from . import u1_analysis as A, u1_research as U


class U1Checks(unittest.TestCase):
    def test_breakout_and_reclaim_are_visible_at_close(self):
        close = np.r_[np.full(20, 10.), 11., 12., 8., 9., 10., 11.]
        e21 = np.full(len(close), 10.)
        result = U.local_starts(close, e21)
        self.assertEqual(result[20], 3)
        self.assertEqual(result[21], 0)
        self.assertEqual(result[25], 2)
        changed = close.copy()
        changed[24:] *= 3
        np.testing.assert_array_equal(result[:24], U.local_starts(changed, e21)[:24])

    def test_mainleg_same_peak_merge_and_horizon(self):
        close = np.full(90, 10.)
        high = close.copy()
        high[35], high[75] = 15, 20
        prices = dict(o=close, h=high, l=close, c=close)
        result = U.mainleg.legs([('X', 0, 'first'), ('X', 1, 'second'), ('X', 20, 'third')], {'X': prices})
        self.assertEqual([(r['peak'], len(r['entries'])) for r in result], [(35, 2), (75, 1)])
        self.assertFalse(result[0]['censored'])

    def test_earnings_after_close_and_unknown_wait(self):
        days = ['2024-01-05', '2024-01-08', '2024-01-09', '2024-01-10']
        opening = np.array([10., 12., 14., 15.])
        close = np.array([10., 12., 14., 15.])
        age, gap, reactions = U.earnings_features(days, [('2024-01-05', 'AFTER'),
            ('2024-01-09', 'REGULAR')], opening, close)
        self.assertTrue(np.isnan(age[0]))
        self.assertEqual(age[1], 3)
        self.assertAlmostEqual(gap[1], 20)
        self.assertEqual(sorted(reactions), [1, 3])
        before, _, reactions = U.earnings_features(days, [('2024-01-08', 'BEFORE')], opening, close)
        self.assertEqual(before[1], 0)
        self.assertEqual(list(reactions), [1])

    def test_auc_ties_and_missing(self):
        self.assertEqual(A.auc([2, 3, 0, 1], [1, 1, 0, 0]), 1)
        self.assertEqual(A.auc([1, 1, 1, 1], [1, 1, 0, 0]), .5)
        self.assertEqual(A.auc([0, 1, 2, 3], [1, 1, 0, 0]), 0)
        self.assertIsNone(A.auc([np.nan, 1], [1, 0]))

    def test_cut_ties_have_no_code_order_bias(self):
        values = np.array([3., 2., 2., 2., 0.])
        weights = A.top_weights(values, 40)
        self.assertAlmostEqual(weights.sum(), 2)
        np.testing.assert_allclose(weights[1:4], 1/3)
        np.testing.assert_allclose(A.top_weights(values[::-1], 40), weights[::-1])

    def test_year_end_maturation_embargo(self):
        days = np.array(['2024-12-%02d' % i for i in range(1, 32)] +
                        ['2025-01-%02d' % i for i in range(1, 32)])
        legs = [dict(year='2024', first=0, censored=False), dict(year='2025', first=31, censored=True)]
        np.testing.assert_array_equal(A.mature_mask(legs, days, ('2024',), '2024-12-31'), [False, False])
        np.testing.assert_array_equal(A.mature_mask(legs, days, ('2024',), '2025-01-31'), [True, False])

    def test_fit_and_prediction_do_not_read_target_labels(self):
        rng = np.random.default_rng(7)
        values = rng.normal(size=(100, 7))
        y = values[:, 0] > .5
        model = A.fit_logistic(values[:70], y[:70])
        scores = A.score(model, values[70:])
        changed = y.copy()
        changed[70:] = ~changed[70:]
        other = A.fit_logistic(values[:70], changed[:70])
        np.testing.assert_allclose(scores, A.score(other, values[70:]), rtol=0, atol=0)
        self.assertGreater(A.auc(scores, y[70:]), .9)
        self.assertEqual(len(model['beta']), 8)

    def test_missing_offset_stays_missing(self):
        legs = [dict(first=0, code='X'), dict(first=1, code='X')]
        keys = np.array([0, 1])
        x = np.array([[1., 2.], [3., 4.]])
        values, valid = A.offset_values(legs, keys, ['X'], x, 1)
        np.testing.assert_array_equal(valid, [True, False])
        self.assertTrue(np.isnan(values[1]).all())

    def test_peers_match_existing_F2_and_exclude_self(self):
        rng = np.random.default_rng(21)
        returns = rng.normal(0, .02, (60, 5))
        returns[:, 1] = returns[:, 0]+rng.normal(0, .001, 60)
        close = np.vstack([np.full(5, 20.), 20*np.cumprod(1+returns, axis=0)])
        monthly = np.array([30., 40., -5., 5., 15.])
        rank = U.SI.midrank(monthly)
        expected = U.F2.peer_features(close, monthly, rank).T
        actual = U.peer_queries(close, close, monthly, rank, monthly, np.arange(5), np.arange(5), block=2)
        np.testing.assert_allclose(expected, actual, equal_nan=True)
        self.assertEqual(actual[1, 0], 0)
        self.assertEqual(actual[0, 0], 1)

    def test_oracle_cash_days_and_strict_window(self):
        p = dict(days=np.array(['2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05']),
                 o=np.full((4, 2), 10.), c=np.array([[10., 10.], [10., 10.], [20., 20.], [20., 20.]]))
        legs = [dict(code='H', first=0, peak=2, his=True, target='g'),
                dict(code='O', first=0, peak=2, his=False, target=None)]
        frozen = [dict(key='g', first=1, peak=2)]
        result = A.scenario(legs, np.ones(2), '2024', p, ['H', 'O'], frozen)
        self.assertAlmostEqual(result['relaxed_cap_equity_100'], .25)
        self.assertAlmostEqual(result['relaxed_gross'], .5)
        self.assertAlmostEqual(result['strict_gross'], .5)
        frozen[0]['first'] = 5
        result = A.scenario(legs, np.ones(2), '2024', p, ['H', 'O'], frozen)
        self.assertEqual(result['strict_cap_equity_100'], 0)
        self.assertEqual(result['strict_gross'], 0)

    def test_prior_cohort_carry_counts_in_calendar_funding(self):
        p = dict(days=np.array(['2024-12-31', '2025-01-02', '2025-01-03']),
                 o=np.full((3, 2), 10.), c=np.array([[10., 10.], [10., 10.], [20., 20.]]))
        legs = [dict(code='H', year='2024', first=0, peak=2, his=True, target='g'),
                dict(code='O', year='2025', first=1, peak=2, his=False, target=None)]
        result = A.scenario(legs, np.ones(2), '2025', p, ['H', 'O'], [dict(key='g', first=1, peak=2)])
        self.assertEqual(result['selected'], 1)
        self.assertEqual(result['selected_positive_weight'], 0)
        self.assertAlmostEqual(result['relaxed_cap_equity_100'], .75)
        self.assertEqual(result['relaxed_gross'], 0)

    def test_real_daily_features_ignore_future(self):
        p = U.load_panel()
        codes = p['codes'].tolist()
        j = codes.index('US.COIN')
        a = U.stock(p, j)
        from studies.trader_data.supplemental import benchmark
        q, _ = benchmark('US.QQQ', p['days'].tolist())
        records = U.earnings_rows().get('US.COIN', ())
        prefix = 580
        original, extras = U.base_features(a, q, records)
        full = U.SI.per_stock(a, q, extras, version='v1.1')
        truncated = {k: v[:prefix] for k, v in a.items()}
        baseline, ex = U.base_features(truncated, q[:prefix], records)
        short = U.SI.per_stock(truncated, q[:prefix], ex, version='v1.1')
        for name in original:
            np.testing.assert_allclose(original[name][:prefix], baseline[name], equal_nan=True, err_msg=name)
        for name in full:
            np.testing.assert_allclose(full[name][:prefix], short[name], equal_nan=True, err_msg=name)
        np.testing.assert_array_equal(U.local_starts(a['c'], U.SI.ema(a['c'], 21))[:prefix],
            U.local_starts(truncated['c'], U.SI.ema(truncated['c'], 21)))


def main():
    U.offline()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(U1Checks)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    U.write('self_checks.json', dict(ok=True, count=result.testsRun, resources=U.resources(),
        source_sha256=U.sha(__file__), real_data_prefix=580, synthetic_data_used_only_in_unit_tests=True))


if __name__ == '__main__':
    main()
