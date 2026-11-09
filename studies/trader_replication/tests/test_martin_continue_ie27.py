import ast
from datetime import date, timedelta
from pathlib import Path
import re
import unittest
from unittest.mock import patch

import numpy as np

from studies.trader_replication import ie27_report as report
from studies.trader_replication import martin_continue_ie27 as m
from studies.trader_replication.tests.test_martin_continue_ie26 import synthetic as upstream_synthetic


def synthetic():
    old = upstream_synthetic()
    d = m.Data.__new__(m.Data)
    d.__dict__.update(old.__dict__)
    d.extend_queries()
    return d


class IE27Tests(unittest.TestCase):
    def test_fills_budget_below_excluded_names_and_repick_boundary(self):
        d = synthetic()
        ranks = np.tile(np.arange(1, 25), len(d.slices))
        nights = list(d.slices.values())
        for k in (2, 3):
            chosen = m.picks(d, ranks, k)
            for t in range(k + 1):
                self.assertEqual(np.flatnonzero(chosen[nights[t]]).tolist(), list(range(k * t, k * (t + 1))))
            self.assertEqual(np.flatnonzero(chosen[nights[k + 1]]).tolist(), list(range(k)))
            independent = report.reference_picks(d, ranks, k)
            for day, sl in d.slices.items():
                self.assertEqual(independent[day], {d.codes[q] for q in np.flatnonzero(chosen[sl]) + sl.start})
                self.assertLessEqual(int(chosen[sl].sum()), k)

    def test_both_widths_match_independent_queues_and_maximum_held(self):
        d = synthetic()
        rng = np.random.default_rng(27)
        ranks = np.empty(d.n, np.int32)
        for sl in d.slices.values():
            ranks[sl] = rng.permutation(sl.stop - sl.start) + 1
        days = d.base.meta['days']
        for k in (2, 3):
            expected = report.reference_picks(d, ranks, k)
            selected = m.picks(d, ranks, k)
            for t, (day, sl) in enumerate(d.slices.items()):
                self.assertEqual(expected[day], {d.codes[q] for q in np.flatnonzero(selected[sl]) + sl.start})
                held = set().union(*(expected[days[u]] for u in range(max(0, t - k + 1), t + 1)))
                self.assertLessEqual(len(held), k * k)
            actual = m.coverage(d, ranks, m.HALVES, k=k, selected=selected)
            self.assertEqual(actual['hit'], [report.replay_entry(d, e, expected, k) for e in d.entries])

    def test_empty_and_masked_nights_consume_calendar_time(self):
        d = synthetic()
        days = list(d.slices)
        d.slices = {days[t]: d.slices[days[t]] for t in (0, 4)}
        ranks = np.tile(np.arange(1, 25), 42)
        selected = m.picks(d, ranks)
        self.assertEqual(np.flatnonzero(selected[d.slices[days[4]]]).tolist(), [0, 1, 2])
        expected = report.reference_picks(d, ranks, 3)
        self.assertEqual(expected[days[0]], expected[days[4]])
        d = synthetic()
        permitted = np.r_[np.arange(24), np.arange(4 * 24, 5 * 24)]
        with patch.object(d, 'rows_for', return_value=permitted):
            selected = m.picks(d, ranks, permitted=['synthetic'])
        self.assertEqual(np.flatnonzero(selected[list(d.slices.values())[4]]).tolist(), [0, 1, 2])
        self.assertEqual(int(selected.sum()), 6)

    def test_holding_window_inclusive_ends_and_expiry(self):
        d = synthetic()
        i = 3
        entry = d.entries[i]
        days = d.base.meta['days']
        t = days.index(entry['entry_date'])
        for k in (2, 3):
            for offset, hit in ((-4 - (k - 1), True), (2, True), (-4 - k, False), (3, False)):
                chosen = np.zeros(d.n, bool)
                q = d.lookup[days[t + offset]][entry['code']]
                chosen[q] = True
                actual = m.coverage(d, d.baseline_ranks, m.HALVES, k=k, selected=chosen)
                self.assertEqual(actual['hit'][i], hit)
                self.assertEqual(report.replay_entry(d, entry, {days[t + offset]: {entry['code']}}, k), hit)
            self.assertEqual(actual['primary']['n'], len(d.entries))

    def test_held_stock_counts_after_leaving_pool(self):
        d = synthetic()
        i = 3
        chosen = np.zeros(d.n, bool)
        chosen[d.eval_query[i, 0]] = True
        query = d.eval_query.copy()
        query[i, 1:] = -1
        value = m.coverage(d, d.baseline_ranks, m.HALVES, query=query, selected=chosen)
        self.assertTrue(value['hit'][i])
        query[i, 0] = -1
        self.assertFalse(m.coverage(d, d.baseline_ranks, m.HALVES, query=query, selected=chosen)['hit'][i])

    def test_shuffle_shares_mapping_and_learning_stays_three_evenings(self):
        d = synthetic()
        d.set_label('synthetic_shuffle', 2701)
        np.testing.assert_array_equal(d.current_eval_query[:, 2:], d.current_query)
        labels = d.labels(list(m.HALVES))
        expected = d.current_query[:, 4:7].ravel()
        actual = np.concatenate([q for records in labels.values() for q in records])
        np.testing.assert_array_equal(np.sort(actual), np.sort(expected))

    def test_training_cannot_read_outer_labels_or_select_masked_rows(self):
        d = synthetic()
        train = list(m.HALVES[:-1])
        forbidden = set(np.flatnonzero(d.entry_half == m.HALVES[-1]))
        class Restricted:
            def __init__(self, values):
                self.values = values
            def __getitem__(self, i):
                if i in forbidden:
                    raise AssertionError('outer label read')
                return self.values[i]
        d.current_query, d.current_eval_query = Restricted(d.query), Restricted(d.eval_query)
        with patch.object(m.a, 'LOGIT_LEVELS', (1,)), patch.object(m.a, 'BOOST_LEVELS', (2,)):
            fitted = m.a.fit_a(d, train)
            desc = m.fixed.describe(d, train, d.current_query, null=False)
            model = m.e.candidates(d, desc, {'groups': [{'representative': j} for j in range(d.library_n)]})[0]
            result = m.ablate(d, 'E', model, train)
        self.assertEqual(len(fitted['candidates']), 2)
        self.assertTrue(set(desc['training_ids']).isdisjoint({d.entries[i]['id'] for i in forbidden}))
        selected = m.picks(d, d.baseline_ranks, permitted=train)
        self.assertFalse(selected[d.row_half == m.HALVES[-1]].any())
        self.assertIn('model', result)

    def test_embargo_keeps_ie26_training_boundary_without_target_dates(self):
        start = date(2000, 12, 20)
        days = [(start + timedelta(days=k)).isoformat() for k in range(410)
                if (start + timedelta(days=k)).weekday() < 5]
        halves = tuple(dict.fromkeys(m.e.ie7.half(day) for day in days))
        held = halves[1]
        row_half = np.asarray([m.e.ie7.half(day) for day in days])
        slices = {day: slice(i, i + 1) for i, day in enumerate(days)}
        with patch.object(m.p, 'HALVES', halves):
            allowed = set(m.p.permitted_rows(days, slices, row_half, [h for h in halves if h != held]))
        indices = np.flatnonzero(row_half == held)
        self.assertTrue(set(range(indices[0] - 4, indices[-1] + 3)).isdisjoint(allowed))

    def test_internal_level_selection_uses_primary_total_not_half_distribution(self):
        d = synthetic()
        train = list(m.HALVES[:3])
        def fake_fit(data, halves, searcher):
            return dict(candidates=[dict(family='logit', level=1, features=[0]),
                                    dict(family='logit', level=3, features=[0, 1, 2])])
        def fake_coverage(data, ranks, halves, **kwargs):
            self.assertEqual(kwargs['permitted'], train)
            hit = ([3, 3, 0] if ranks[0] == 1 else [1, 1, 1])[train.index(halves[0])]
            return dict(primary=dict(n=3, hit=hit))
        with (patch.object(m.a, 'cached_fit', side_effect=fake_fit), patch.object(m.fixed, 'path') as dest,
              patch.object(m.fixed, 'write'), patch.object(m.fixed, 'ranks_for', side_effect=lambda d, v, z: np.array([z['level']])),
              patch.object(m.fixed, 'coverage', side_effect=fake_coverage)):
            dest.return_value.exists.return_value = False
            value = m.pipeline_a(d, train)
        self.assertEqual(value['model']['level'], 1)
        self.assertEqual(value['selected']['hit'], 6)

    def test_equal_coverage_deletes_factor_and_restarts(self):
        d = synthetic()
        model = dict(terms=[dict(j=0), dict(j=1)])
        def same_score(data, method, candidate, halves):
            return dict(coverage=dict(primary=dict(n=3, hit=2)), fitted={})
        with (patch.object(m.fixed, 'diagnostic_loo', side_effect=same_score),
              patch.object(m.fixed, 'refit_equal', side_effect=lambda data, candidate, halves: candidate)):
            result = m.ablate(d, 'E', model, list(m.HALVES))
        self.assertEqual(result['model']['terms'], [])
        self.assertEqual(len(result['history']), 2)
        self.assertTrue(all(row['accepted'] for row in result['history']))

    def test_source_is_isolated_and_contains_no_his_codes_dates_or_accounts(self):
        self.assertIsNot(m.fixed, m.original)
        self.assertEqual(m.original.PREFIX, 'strong_continue_ie26_')
        self.assertEqual(m.original.p.PREFIX, 'strong_continue_ie26_')
        self.assertEqual(m.p.PREFIX, m.PREFIX)
        for source in (Path(m.__file__), Path(report.__file__)):
            for node in ast.walk(ast.parse(source.read_text())):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    self.assertIsNone(re.search(r'\b(?:US\.[A-Z]+|\d{4}-\d{2}-\d{2})\b', node.value))
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    self.assertNotEqual(node.func.attr, 'accounts')


if __name__ == '__main__':
    unittest.main()
