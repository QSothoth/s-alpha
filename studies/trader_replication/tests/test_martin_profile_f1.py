"""F1 timing, resource-bounded features, and opportunity-aware selection behavior."""
import datetime as dt
import unittest

import numpy as np

from studies.trader_replication import martin_profile_f1 as F


def fixture(n=300):
    rng = np.random.default_rng(81)
    c = 10*np.exp(np.cumsum(rng.normal(.002, .018, n)))
    days = []
    day = dt.date(2023, 1, 2)
    while len(days) < n:
        if day.weekday() < 5:
            days.append(day.isoformat())
        day += dt.timedelta(days=1)
    arrays = dict(o=c*.998, h=c*1.035, l=c*.965, c=c, raw_c=c.copy(),
                  v=np.full(n, 1e7), t=np.full(n, 1e8))
    return arrays, days


def sample(labels=(), k=1, cooldown=0):
    meta = dict(days=[f'2024-01-{i+1:02d}' for i in range(12)], codes=['S0', 'S1'],
                first_night=0)
    arrays = dict(row_day=np.repeat(np.arange(12), 2), row_code=np.tile([0, 1], 12),
                  new=np.ones(24, bool), ie47=np.ones(24, bool), entry=np.zeros(24, np.uint8),
                  regime=np.zeros(24, np.int8), action=np.repeat(np.arange(12), 2))
    spec = dict(pool='new', paired=False, k=k, cooldown=cooldown)
    return F.Sample(meta, arrays, np.zeros((len(F.FEATURES), 24)), spec, list(labels))


def leg(peak=10):
    return dict(key='S0:leg', code='S0', first=3, first_date='2024-01-04',
                peak=peak, top=20., gain=1., entries=[dict(index=3, gain=1.)])


class FeatureTimingTests(unittest.TestCase):
    def test_stock_features_and_weekly_trend_are_prefix_invariant(self):
        a, days = fixture()
        q = np.linspace(90, 110, len(days))
        full = F.stock_features(a, q)
        core = F.stock_core(a, days)
        for cut in (160, 213):
            short = {k: v[:cut] for k, v in a.items()}
            features = F.stock_features(short, q[:cut])
            for name in features:
                np.testing.assert_allclose(features[name], full[name][:cut], atol=1e-10, rtol=0, equal_nan=True)
            prefix = F.stock_core(short, days[:cut])
            np.testing.assert_array_equal(prefix['new'], core['new'][:cut])

    def test_raw_close_floor_cannot_be_replaced_by_adjusted_close(self):
        a, days = fixture()
        a['raw_c'][:] = 1.5
        self.assertFalse(F.stock_core(a, days)['new'].any())
        a['raw_c'][:] = np.nan
        self.assertFalse(F.stock_core(a, days)['new'].any())

    def test_adjustment_scaling_preserves_ratios_liquidity_and_triggers(self):
        a, days = fixture()
        q = np.linspace(90, 110, len(days))
        changed = {k: v.copy() for k, v in a.items()}
        for k in ('o', 'h', 'l', 'c'):
            changed[k] *= .1
        changed['v'] *= 10
        before, after = F.stock_features(a, q), F.stock_features(changed, q)
        for name in before:
            np.testing.assert_allclose(before[name], after[name], atol=1e-9, rtol=0, equal_nan=True)
        c1, c2 = F.stock_core(a, days), F.stock_core(changed, days)
        np.testing.assert_array_equal(c1['new'], c2['new'])
        np.testing.assert_array_equal(F.daily_routes(a, c1['e9'], c1['e21']),
                                      F.daily_routes(changed, c2['e9'], c2['e21']))

    def test_rank_units_and_memory_expire_without_future_top_membership(self):
        top = F.SI.midrank(np.arange(11.)) >= 80
        self.assertEqual(np.flatnonzero(top).tolist(), [8, 9, 10])
        history = np.zeros(125, bool)
        history[0] = True
        memory = F.trailing_memory(history)
        self.assertTrue(memory[119])
        self.assertFalse(memory[120])
        history[124] = True
        np.testing.assert_array_equal(F.trailing_memory(history)[:124], memory[:124])


class TriggerTests(unittest.TestCase):
    def test_e10_touch_does_not_require_close_reclaim(self):
        a = dict(o=np.array([10., 10.]), h=np.array([10.3, 10.1]),
                 l=np.array([9.8, 9.4]), c=np.array([10., 9.5]))
        routes = F.daily_routes(a, np.array([10., 9.9]), np.array([9.8, 9.7]))
        self.assertFalse(routes[1] & 1)
        self.assertTrue(routes[1] & 2)

    def test_observation_starts_next_day_ends_fifth_and_excludes_peak(self):
        o, c = np.full(12, 10.), np.full(12, 11.)
        routes = np.zeros(12, np.uint8)
        routes[6] = 1
        _, labels = F.label_windows(leg(), o, c, routes, 11)
        nights = {r['night'] for r in labels}
        self.assertNotIn(0, nights)
        self.assertIn(1, nights)
        self.assertIn(5, nights)
        self.assertNotIn(6, nights)
        _, labels = F.label_windows(leg(peak=6), o, c, routes, 11)
        self.assertEqual(labels, [])

    def test_trigger_uses_actual_close_not_support_price(self):
        o, c = np.full(12, 10.), np.full(12, 15.)
        routes = np.zeros(12, np.uint8)
        routes[4] = 8
        _, labels = F.label_windows(leg(), o, c, routes, 11)
        self.assertEqual(labels, [])
        c[4] = 12.
        _, labels = F.label_windows(leg(), o, c, routes, 11)
        self.assertTrue(labels)
        self.assertEqual(labels[0]['price'], 12.)
        self.assertAlmostEqual(labels[0]['share'], 20/12-1)

    def test_cross_year_label_is_clipped_before_fitting(self):
        p = dict(c=np.full(12, 10.), h=np.arange(11., 23.))
        original = leg()
        clipped = F.clipped_leg(original, p, 7)
        self.assertEqual(clipped['peak'], 7)
        self.assertEqual(clipped['top'], 18)
        self.assertEqual(original['top'], 20)
        self.assertAlmostEqual(clipped['gain'], .8)


class ObjectiveTests(unittest.TestCase):
    def test_no_opportunity_nights_do_not_dilute_precision_or_duplicate_overlaps(self):
        row = dict(leg=leg(), year='2024', signal_rows=[0],
                   triggers=[dict(night=0, row=0, fill=1, share=.8, price=11.)])
        data = sample([row, row], k=2)
        result = data.evaluate(np.zeros(24))
        self.assertEqual(result['covered'], 2)
        self.assertEqual(result['opportunity_hits'], 1)
        self.assertEqual(result['opportunity_picks'], 2)
        self.assertEqual(result['P_opp'], .5)
        self.assertEqual(result['E'], .8)

    def test_cooldown_is_in_sessions_and_preserves_empty_nights(self):
        data = sample(k=1, cooldown=5)
        selected = data.nominate(np.tile([2., 1.], 12))
        code0_nights = [i for i, row in enumerate(selected) if row[0] < 24 and data.code[row[0]] == 0]
        self.assertEqual(code0_nights, [0, 6])
        self.assertTrue(np.all(selected[2:6] == 24))

    def test_missing_bin_learns_preference_and_shrinks(self):
        bins = np.array([0, 0, 0, 1, 2, 2], np.uint8)
        mask = np.ones(6, bool)
        scores, n, _, _ = F.preference(bins, 3, mask, [np.array([4, 5])])
        self.assertEqual(n, 1)
        self.assertGreater(scores[2], scores[0])
        self.assertTrue(np.isfinite(scores).all())

    def test_training_edges_ignore_future_extreme_values(self):
        data = np.arange(100.)
        edges = F.bin_edges(data[:60])
        data[60:] = 1e12
        np.testing.assert_array_equal(edges, F.bin_edges(data[:60]))

    def test_frozen_scoring_does_not_read_labels(self):
        data = sample()
        data.labels = None
        scores = F.score_model(dict(parts={}), data)
        self.assertEqual(scores.tolist(), [0.]*24)


if __name__ == '__main__':
    unittest.main()
