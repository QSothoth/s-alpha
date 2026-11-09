"""F2 peers, source-only stability gates, and frozen inference behavior."""
import unittest

import numpy as np

from studies.trader_replication import martin_profile_f1 as F1
from studies.trader_replication import martin_profile_f2 as F


class PeerTests(unittest.TestCase):
    def test_blocked_peers_match_direct_correlations_and_exclude_self(self):
        rng = np.random.default_rng(201)
        common = rng.normal(0, .01, 75)
        returns = np.column_stack((common, common+.001*rng.normal(size=75),
                                  -common, rng.normal(0, .01, 75)))
        closes = 100*np.exp(np.vstack((np.zeros(4), np.cumsum(returns, axis=0))))
        monthly = np.array([20., 10., -10., 0.])
        ranks = F.SI.midrank(monthly)
        actual = F.peer_features(closes[-61:], monthly, ranks, block=2)
        daily = closes[-60:]/closes[-61:-1]-1
        corr = np.corrcoef(daily.T)
        expected = np.full_like(actual, np.nan)
        for i in range(4):
            peers = np.flatnonzero((corr[i] >= .6) & (np.arange(4) != i))
            expected[0, i] = sum(ranks[peers] >= 80)
            if len(peers):
                expected[1, i] = F.rank_against(np.array([np.median(monthly[peers])]), monthly)[0]
                expected[2, i] = F.SI.midrank(np.r_[monthly[peers], monthly[i]])[-1]
        np.testing.assert_allclose(actual, expected, equal_nan=True)
        self.assertEqual(actual[0, 0], 0)
        self.assertEqual(actual[0, 1], 1)
        self.assertEqual(actual[2, 0], 100)
        self.assertEqual(actual[2, 1], 0)

    def test_future_prices_do_not_change_tonights_peers(self):
        rng = np.random.default_rng(802)
        prices = 10*np.exp(np.cumsum(rng.normal(0, .02, (120, 8)), axis=0))
        monthly = np.arange(8.)
        before = F.peer_features(prices[20:81], monthly, F.SI.midrank(monthly), block=3)
        prices[81:] *= 1e6
        after = F.peer_features(prices[20:81], monthly, F.SI.midrank(monthly), block=5)
        np.testing.assert_allclose(before, after, equal_nan=True)

    def test_insufficient_history_and_constant_prices_have_no_fabricated_peers(self):
        monthly = np.array([1., 2.])
        for closes in (np.ones((60, 2)), np.ones((61, 2))):
            actual = F.peer_features(closes, monthly, F.SI.midrank(monthly))
            np.testing.assert_array_equal(actual[0], [0, 0])
            self.assertTrue(np.isnan(actual[1:]).all())
        prices = np.column_stack((np.arange(1., 62), np.arange(1., 62)))
        prices[0, 1] = np.nan
        self.assertTrue(np.isnan(F.peer_features(prices, monthly, F.SI.midrank(monthly))[1:]).all())

    def test_rank_units_ties_and_market_reference(self):
        pool = np.array([1., 2., 2., 4., np.nan])
        np.testing.assert_allclose(F.rank_against(pool, pool), F.SI.midrank(pool), equal_nan=True)
        np.testing.assert_allclose(F.rank_against(np.array([0., 5., np.nan]), pool), [0, 100, np.nan], equal_nan=True)
        with self.assertRaises(ValueError):
            F.peer_features(np.ones((61, 2)), np.ones(2), np.ones(2), block=400)

    def test_remembered_pullback_rewards_close_risk_without_absolute_adr_floor(self):
        value = F.remembered_pullback(np.array([1., 1., 0., 1.]), np.array([90., 90., 100., 90.]),
                                     np.array([.1, 2., .1, np.nan]), np.array([.2, 3., .2, np.nan]))
        self.assertGreater(value[0], value[1])
        self.assertGreater(value[1], value[2])
        self.assertTrue(np.isnan(value[3]))


class FittingTests(unittest.TestCase):
    def test_fitter_context_restores_f1_even_after_failure(self):
        before = F1.FEATURES, F1.START, F1.TRAIN_END, F1.WORK
        with self.assertRaises(RuntimeError):
            with F.fitter(('one',), '2024-01-01', '2024-12-31'):
                self.assertEqual(F1.FEATURES, ('one',))
                self.assertEqual(F1.TRAIN_END, '2024-12-31')
                raise RuntimeError('exercise restoration')
        self.assertEqual((F1.FEATURES, F1.START, F1.TRAIN_END, F1.WORK), before)

    def test_agreement_cannot_use_future_year_market_rows_or_labels(self):
        class Sample:
            meta = dict(days=['2024-01-02', '2024-07-02', '2025-01-02'])
            day = np.repeat(np.arange(3), 10)
            x = np.tile(np.arange(10.), 3)[None, :]
            leg_rows = [np.array([8, 9]), np.array([18, 19]), np.array([20])]
            labels = [dict(year='2024'), dict(year='2024'), dict(year='2025')]

        sample = Sample()
        periods = (('2024-01-01', '2024-06-30'), ('2024-07-01', '2024-12-31'))
        before = F.agreement(sample, ('strength',), periods)
        sample.x[0, 20:] = 1e20
        # Future-year anchors can have prior-December nights; reject their votes too.
        sample.leg_rows[-1] = np.arange(30)
        after = F.agreement(sample, ('strength',), periods)
        self.assertGreater(before[0]['correlation'], .99)
        np.testing.assert_array_equal(before[0]['edges'], after[0]['edges'])
        np.testing.assert_array_equal(before[0]['profiles'], after[0]['profiles'])

    def test_relative_strength_rank_is_redundant_with_same_night_returns(self):
        values = np.array([12., -2., 1., 12., np.nan])
        np.testing.assert_allclose(F.SI.midrank(values), F.SI.midrank(values-3), equal_nan=True)


if __name__ == '__main__':
    unittest.main()
