import ast
from datetime import date, timedelta
from pathlib import Path
import re
import unittest
from unittest.mock import patch

import numpy as np

from studies.trader_replication import martin_continue_ie26 as m
from studies.trader_replication.tests.test_martin_continue_ie25 import synthetic as upstream_synthetic


def synthetic():
    old = upstream_synthetic()
    d = m.Data.__new__(m.Data)
    d.__dict__.update(old.__dict__)
    d.code_index = {c: k for k, c in enumerate(dict.fromkeys(d.codes))}
    d.code_ids = np.asarray([d.code_index[c] for c in d.codes], np.int32)
    d.lookup = {day: dict(zip(d.codes[sl], range(sl.start, sl.stop))) for day, sl in d.slices.items()}
    d.baseline_selected = m.picks(d, d.baseline_ranks)
    return d


class IE26Tests(unittest.TestCase):
    def test_budget_fills_below_held_names_and_expires_after_ten_nights(self):
        d = synthetic()
        ranks = np.tile(np.arange(1, 25), len(d.slices))
        selected = m.picks(d, ranks, 3)
        nights = list(d.slices.values())
        self.assertEqual(np.flatnonzero(selected[nights[0]]).tolist(), [0, 1, 2])
        self.assertEqual(np.flatnonzero(selected[nights[1]]).tolist(), [3, 4, 5])
        self.assertEqual(int(selected[nights[8]].sum()), 0)
        self.assertEqual(np.flatnonzero(selected[nights[11]]).tolist(), [0, 1, 2])
        for k in (2, 3, 4):
            chosen = m.picks(d, ranks, k)
            recent = []
            for sl in nights:
                codes = {d.codes[q] for q in np.flatnonzero(chosen[sl]) + sl.start}
                held = set().union(*recent[-10:]) if recent else set()
                self.assertLessEqual(len(codes), k)
                self.assertFalse(codes & held)
                recent.append(codes)

    def test_budget_matches_reference_set_implementation(self):
        d = synthetic()
        rng = np.random.default_rng(26)
        ranks = np.empty(d.n, np.int32)
        for sl in d.slices.values():
            ranks[sl] = rng.permutation(sl.stop - sl.start) + 1
        expected, recent = np.zeros(d.n, bool), []
        for sl in d.slices.values():
            held = set().union(*recent[-10:]) if recent else set()
            order = np.argsort(ranks[sl], kind='stable') + sl.start
            picked = [q for q in order if d.codes[q] not in held][:3]
            expected[picked] = True
            recent.append({d.codes[q] for q in picked})
        np.testing.assert_array_equal(m.picks(d, ranks), expected)

    def test_full_window_counts_both_boundaries_and_preserves_missing_denominator(self):
        d = synthetic()
        ranks = np.zeros(d.n)
        for w in (0, 6):
            chosen = np.zeros(d.n, bool)
            chosen[d.query[:, w]] = True
            query = d.query.copy()
            query[0] = -1
            c = m.coverage(d, ranks, m.HALVES, query=query, selected=chosen)
            self.assertEqual(c['primary']['hit'], len(d.entries) - 1)
            self.assertEqual(c['primary']['n'], len(d.entries))
        days = [(date(2001, 1, 1) + timedelta(days=k)).isoformat() for k in range(20)
                if (date(2001, 1, 1) + timedelta(days=k)).weekday() < 5]
        self.assertEqual(m.p.window(days, days[6]), days[2:9])

    def test_training_labels_use_only_evenings_zero_one_two(self):
        d = synthetic()
        labels = d.labels(list(m.HALVES))
        flattened = np.concatenate([q for records in labels.values() for q in records])
        np.testing.assert_array_equal(np.sort(flattened), np.sort(d.query[:, 4:7].ravel()))
        self.assertFalse(set(flattened) & set(d.query[:, :4].ravel()))

    def test_precision_excludes_unknown_open_instead_of_counting_a_loss(self):
        flags = np.asarray([1, 0, -1, 1], np.int8)
        self.assertEqual(m.precision(flags, np.asarray([True, False, True, False])),
                         dict(rate=1., n=1, winners=1))
        self.assertEqual(m.precision(flags, np.asarray([False, False, True, False])),
                         dict(rate=None, n=0, winners=0))

    def test_description_reports_each_offset_and_arithmetic_mean(self):
        values = np.asarray([[.2, .8, np.nan, .1, .3, .5]])
        query = np.asarray([[0, 1, 2], [3, 4, 5]])
        sampled, available = m.samples(values, query)
        np.testing.assert_allclose(sampled, [[[.2, .8, .5], [.1, .3, .5]]])
        means, counts = m.sample_summary(sampled, available, query, np.asarray(['half', 'half']), ['half'])
        np.testing.assert_allclose(means[:2, 0, 0], [.15, .55])
        self.assertTrue(np.isnan(means[2, 0, 0]))
        self.assertAlmostEqual(means[3, 0, 0], .4)
        self.assertEqual(counts[2, 0, 0], 1)

    def test_random_control_tracks_same_stock_and_neutralizes_absent_night(self):
        d = synthetic()
        ids = np.flatnonzero(d.entry_half == m.HALVES[0])
        q = m.episode_queries(d, ids, 2660, list(m.HALVES))
        for row in q:
            self.assertEqual(len({d.codes[r] for r in row}), 1)
        i = int(ids[0])
        code = d.codes[q[0, 1]]
        missing_day = d.entries[i]['nights'][5]
        del d.lookup[missing_day][code]
        after = m.episode_queries(d, ids, 2660, list(m.HALVES))
        self.assertEqual(after[0, 1], -1)
        sampled, _ = m.samples(d.x[:1], after)
        self.assertEqual(sampled[0, 0, 1], .5)
        self.assertEqual(d.codes[after[0, 0]], d.codes[after[0, 2]])

    def test_training_cannot_read_held_labels(self):
        d = synthetic()
        train = list(m.HALVES[:-1])
        forbidden = set(np.flatnonzero(d.entry_half == m.HALVES[-1]))
        query = d.query
        class Restricted:
            def __getitem__(self, i):
                if i in forbidden:
                    raise AssertionError('held label was read')
                return query[i]
        d.current_query = Restricted()
        with patch.object(m.a, 'LOGIT_LEVELS', (1,)), patch.object(m.a, 'BOOST_LEVELS', (2,)):
            fit = m.a.fit_a(d, train)
            description = m.describe(d, train, d.current_query, null=False)
            model = m.e.candidates(d, description, {'groups': [{'representative': j} for j in range(d.library_n)]})[0]
            result = m.ablate(d, 'E', model, train)
        self.assertEqual(len(fit['candidates']), 2)
        self.assertTrue(set(description['training_ids']).isdisjoint({d.entries[i]['id'] for i in forbidden}))
        self.assertIn('model', result)

    def test_inner_model_selection_uses_budgeted_total_hits(self):
        d = synthetic()
        train = list(m.HALVES[:-1])
        forbidden = set(np.flatnonzero(d.entry_half == m.HALVES[-1]))
        query = d.query
        class Restricted:
            def __getitem__(self, i):
                if i in forbidden:
                    raise AssertionError('outer label was read')
                return query[i]
        d.current_query = Restricted()
        def fake_fit(data, halves, searcher):
            self.assertEqual(searcher, 'A')
            self.assertTrue(set(halves) <= set(train))
            data.labels(halves)
            return dict(candidates=[dict(family='logit', level=1, features=[0], weights=[1.]),
                                    dict(family='logit', level=3, features=[0, 1, 2], weights=[1., 0., 0.])])
        with patch.object(m.a, 'cached_fit', side_effect=fake_fit), patch.object(m, 'path') as dest, patch.object(m, 'write'):
            dest.return_value.exists.return_value = False
            value = m.pipeline_a(d, train)
        self.assertEqual(value['model']['level'], 1)
        self.assertEqual(value['selected']['hit'], sum(v['coverage']['hit'] for v in value['inner'] if v['key'][1] == 1))

    def test_inner_total_beats_more_even_half_distribution(self):
        d = synthetic()
        train = list(m.HALVES[:3])
        def fake_fit(data, halves, searcher):
            return dict(candidates=[dict(family='logit', level=1, features=[0], weights=[1.]),
                                    dict(family='logit', level=3, features=[0, 1, 2], weights=[1., 0., 0.])])
        def fake_coverage(data, ranks, halves, **kwargs):
            half = halves[0]
            hit = ([3, 3, 0] if ranks[0] == 1 else [1, 1, 1])[train.index(half)]
            return dict(primary=dict(n=3, hit=hit))
        def fake_ranks(data, method, model):
            return np.array([model['level']])
        with (patch.object(m.a, 'cached_fit', side_effect=fake_fit), patch.object(m, 'path') as dest,
              patch.object(m, 'write'), patch.object(m, 'ranks_for', side_effect=fake_ranks),
              patch.object(m, 'coverage', side_effect=fake_coverage)):
            dest.return_value.exists.return_value = False
            value = m.pipeline_a(d, train)
        self.assertEqual(value['model']['level'], 1)
        self.assertEqual(value['selected']['hit'], 6)

    def test_training_rows_embargo_both_sides_without_target_dates(self):
        start = date(2000, 12, 20)
        days = [(start + timedelta(days=k)).isoformat() for k in range(410)
                if (start + timedelta(days=k)).weekday() < 5]
        halves = tuple(dict.fromkeys(m.e.ie7.half(day) for day in days))
        held = halves[1]
        row_half = np.asarray([m.e.ie7.half(day) for day in days])
        slices = {day: slice(i, i + 1) for i, day in enumerate(days)}
        with patch.object(m.p, 'HALVES', halves):
            allowed = set(m.p.permitted_rows(days, slices, row_half, [h for h in halves if h != held]))
        positions = np.flatnonzero(row_half == held)
        first, last = positions[0], positions[-1]
        self.assertTrue(set(range(first - 4, last + 3)).isdisjoint(allowed))
        self.assertIn(first - 5, allowed)
        self.assertIn(last + 3, allowed)

    def test_fixed_empty_model_and_deletion_have_observable_predictions(self):
        d = synthetic()
        for family in ('logit', 'boost'):
            model = dict(family=family, features=[], level=1)
            fitted = m.a.fit_a(d, list(m.HALVES), fixed=model)
            ranks = m.ranks_for(d, 'A', fitted)
            self.assertEqual(ranks.shape, (d.n,))
            for sl in d.slices.values():
                np.testing.assert_array_equal(ranks[sl], np.arange(1, sl.stop - sl.start + 1))

    def test_private_reuse_keeps_old_modules_and_new_source_clean(self):
        self.assertIsNot(m.p, m.original)
        self.assertEqual(m.original.PREFIX, 'strong_continue_ie25_')
        self.assertEqual(m.original.e.PREFIX, 'strong_continue_ie25_')
        self.assertEqual(m.e.PREFIX, m.PREFIX)
        self.assertEqual(m.a.PREFIX, m.PREFIX)
        for source in (Path(m.__file__), Path(m.__file__).with_name('ie26_report.py')):
            tree = ast.parse(source.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    self.assertIsNone(re.search(r'\b(?:US\.[A-Z]+|\d{4}-\d{2}-\d{2})\b', node.value))
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    self.assertNotEqual(node.func.attr, 'accounts')


if __name__ == '__main__':
    unittest.main()
