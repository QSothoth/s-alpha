"""Synthetic behavior checks for the IE41 training/evaluation boundaries."""
from pathlib import Path
from datetime import date, timedelta
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from studies.trader_replication import martin_profile_ie41 as s


def tiny_data(nights=15, width=8):
    d = s.Data.__new__(s.Data)
    d.n = nights*width
    d.slices = [slice(t*width, (t+1)*width) for t in range(nights)]
    d.nights = list(range(nights))
    d.cal = [str(t) for t in range(nights)]
    d.codes = np.tile(np.array(list('abcdefgh')[:width]), nights)
    d.row_day = np.repeat(d.nights, width)
    d.row_half = np.array(['2024H1']*d.n)
    d.night_half = np.array(['2024H1']*nights)
    d.code_ids = {c: j for j, c in enumerate(dict.fromkeys(d.codes))}
    d.row_code = np.tile(np.arange(width), nights)
    d.lookup = {(c, int(t)): j for j, (c, t) in enumerate(zip(d.codes, d.row_day))}
    d.pad = np.arange(d.n).reshape(nights, width)
    d.windows = {}
    return d


class IE41Tests(unittest.TestCase):
    def test_write_boundary_includes_formal_atomic_temporary_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(s, 'WORK', root/'work'), patch.object(s, 'OUTPUT', root/'formal.json'):
                self.assertTrue(s.allowed_write(root/'work/model.json'))
                self.assertTrue(s.allowed_write(root/'formal.json'))
                self.assertTrue(s.allowed_write(root/'formal.json.tmp'))
                self.assertFalse(s.allowed_write(root/'unrelated.json'))

    def test_shrinkage_matches_formula_and_missing_is_zero(self):
        bins = np.array([0, 1, 2, 3, 0, 1, 2, 3])
        y = np.array([2., 0, 0, 99, 0, 0, 0, 99])
        mask = np.ones(8, bool)
        table = s.shrink_table(bins, y, mask)
        expected = np.log((np.array([2., 0, 0])+(2/3)/3)/(2+2/3)/(1/3))
        np.testing.assert_allclose(table[:3], expected)
        self.assertEqual(table[3], 0.)
        self.assertEqual(table[bins][3], 0.)

    def test_nightly_average_rank_and_binary_values(self):
        x = np.array([[10., 10., 30., np.nan, 9., 1., 5., 5.], [0., 1., 0., np.nan, 1., 1., 0., 0.]])
        out = s.nightly_percentiles(x, [slice(0, 4), slice(4, 8)], [False, True])
        np.testing.assert_allclose(out[0], [.5, .5, 1., np.nan, 1., .25, .625, .625], equal_nan=True)
        np.testing.assert_array_equal(out[1], x[1])

    def test_cooldown_effective_rank_and_soft_window(self):
        d = tiny_data()
        score = np.tile(np.arange(8, 0, -1.), 15)
        chosen, rank = d.replay(score)
        self.assertTrue(chosen[0])
        self.assertTrue(np.isinf(rank[8]))
        self.assertEqual(rank[8+3], 1)
        self.assertFalse(chosen[10*8])
        self.assertTrue(chosen[11*8])
        target = dict(code='a', day=6, half='2024H1', primary=True, setup='breakout')
        value = d.metric(dict(score=score), [target])
        self.assertEqual(value['hit'], 1)
        self.assertAlmostEqual(value['soft'], 1/(1+np.exp((1-3.5)/2)))
        target['day'] = 9
        self.assertEqual(d.metric(dict(score=score), [target])['details'][0]['best_effective_rank'], 1.)

    def test_slots_have_distinct_names_and_observe_same_cooldown(self):
        d = tiny_data()
        score = np.tile(np.arange(8, 0, -1.), 15)
        chosen, _ = d.replay(score, slots=[score, score, score])
        self.assertEqual(np.flatnonzero(chosen[:8]).tolist(), [0, 1, 2])
        self.assertEqual(np.flatnonzero(chosen[8:16]).tolist(), [3, 4, 5])
        for sl in d.slices:
            self.assertLessEqual(int(chosen[sl].sum()), 3)
            self.assertEqual(len(set(d.codes[sl][chosen[sl]])), int(chosen[sl].sum()))

    def test_slot_effective_rank_matches_actual_three_pick_budget(self):
        d = tiny_data(1, 8)
        score = np.arange(8, 0, -1.)
        chosen, effective = d.replay(score, slots=[score, score, score])
        np.testing.assert_array_equal(chosen, effective <= 3)
        np.testing.assert_array_equal(effective, np.arange(1., 9.))

    def test_conditional_logit_only_compares_same_night(self):
        x = np.array([[0., 1.], [1., 0.], [2., 1.], [3., 0.]])
        y = np.array([1., 0., 0., 1.])
        slices = [slice(0, 2), slice(2, 4)]
        mask = np.ones(4, bool)
        groups = s.logit_groups(x, y, slices, mask)
        altered = x.copy()
        altered[:2] += [100., -30.]
        altered[2:] += [-22., 80.]
        beta = np.array([.2, -.3])
        for a, b in zip(s.conditional_loss(beta, groups, .1),
                        s.conditional_loss(beta, s.logit_groups(altered, y, slices, mask), .1)):
            np.testing.assert_allclose(a, b, atol=1e-10)

    def test_null_information_sets_four_effective_degrees(self):
        ridge, df = s.fixed_ridge(np.diag(np.arange(1., 25.)))
        self.assertGreater(ridge, 0)
        self.assertAlmostEqual(df, 4.)

    def test_each_fold_ignores_validation_values_and_learning_rows(self):
        rng = np.random.default_rng(41)
        raw = rng.normal(size=(5, 30))
        mask = np.arange(30) < 20
        before = s.spearman_groups(raw, mask, count=2)
        raw[:, ~mask] = rng.normal(1000, 1000, (5, 10))
        self.assertEqual(before, s.spearman_groups(raw, mask, count=2))
        z = rng.normal(size=(30, 6))
        y = np.tile([1., 0, 0, 0, 0], 6)
        slices = [slice(i, i+5) for i in range(0, 30, 5)]
        a = s.fit_logit(z, y, slices, mask)
        z[~mask] *= 10000
        y[~mask] = 1000
        b = s.fit_logit(z, y, slices, mask)
        np.testing.assert_allclose(a['beta'], b['beta'])
        d = tiny_data(3, 4)
        t = dict(code='a', day=0, half='2024H1', primary=True, setup='ep')
        train_mask = np.arange(d.n) < 4
        weights, used = s.positive_weights(d, [t], train_mask)
        self.assertEqual(weights.sum(), 1.)
        self.assertEqual(weights[4:].sum(), 0.)
        self.assertEqual(used, 1)

    def test_missing_members_have_neutral_factor_contribution(self):
        pct = np.array([[.9, np.nan, np.nan], [.7, .7, np.nan]])
        groups = [dict(members=[0, 1], signs=[1, -1])]
        factor = s.factors(pct, groups)
        np.testing.assert_allclose(factor[:, 0], [.6, .4, .5])
        np.testing.assert_array_equal(s.basis(factor)[2], [0., 0.])

    def test_regime_permutation_preserves_training_multiset_and_test_rows(self):
        r = np.arange(12.)
        mask = np.arange(12) < 8
        shuffled = s.permute_regime(r, mask, np.random.default_rng(42))
        np.testing.assert_array_equal(np.sort(shuffled[mask]), r[mask])
        np.testing.assert_array_equal(shuffled[~mask], r[~mask])
        self.assertFalse(np.array_equal(shuffled[mask], r[mask]))

    def test_g4_nonsignificant_slope_is_replaced_by_constant(self):
        d = tiny_data(3, 4)
        d.r = np.arange(3.)
        z = np.zeros((d.n, 2))
        model = dict(beta=[1., 1.])
        groups = [dict(kind='M')]
        def optimize(*args, constant=False):
            return dict(a0=.5, a1=0. if constant else 1., soft=2., hit=1)
        with tempfile.TemporaryDirectory() as directory, patch.object(s, 'optimize_tilt', side_effect=optimize), \
                patch.object(s, 'capacity'), patch.object(s, 'log'):
            prediction, result, _ = s.fit_g4(d, z, groups, model, [], {'2024H1'}, 42, Path(directory)/'permutation.json')
        self.assertEqual(result['permutation_count'], 200)
        self.assertEqual(result['permutation_p'], 1.)
        self.assertEqual(result['a1'], 0.)
        self.assertEqual(prediction['score'].shape, (d.n,))

    def test_pool_future_labels_cannot_cross_the_training_half(self):
        days = [(date(2024, 1, 1)+timedelta(days=k)).isoformat() for k in range(250)]
        d = SimpleNamespace(n=4, codes=np.array(['a']*4), row_day=np.array([0, 100, 123, 181]),
                            row_half=np.array(['2024H1']*4), cal=days)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'stocks').mkdir()
            np.savez(root/'stocks/a.npz', o=np.full(250, 100.), h=np.full(250, 135.))
            with patch.object(s, 'WORK', root), patch.object(s, 'SOURCE', root), patch.object(s, 'capacity'):
                label, end = s.pool_labels(d)
        np.testing.assert_allclose(label[:2], [1., 1.])
        self.assertTrue(np.isnan(label[2:]).all())
        np.testing.assert_array_equal(end, [60, 160, -1, -1])


if __name__ == '__main__':
    unittest.main()
