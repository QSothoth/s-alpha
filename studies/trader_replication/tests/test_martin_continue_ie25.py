import ast
from datetime import date, timedelta
from pathlib import Path
import re
import unittest
from unittest.mock import patch

import numpy as np

from studies.trader_replication import martin_continue_ie25 as m


def synthetic():
    d = m.Data.__new__(m.Data)
    d.slices, d.days, d.codes, entries, query = {}, [], [], [], []
    for half in m.HALVES:
        nights = []
        for t in range(7):
            day = half[:4] + ('-02-' if half.endswith('1') else '-08-') + str(t + 1).zfill(2)
            start = len(d.days)
            d.slices[day] = slice(start, start + 24)
            d.days.extend([day] * 24)
            d.codes.extend(['asset_' + str(k) for k in range(24)])
            nights.append((day, start))
        for k in range(3):
            entries.append(dict(id=half + '_' + str(k), code='asset_' + str(k + 8),
                                entry_date=nights[4][0], primary=True, nights=[day for day, _ in nights]))
            query.append([start + k + 8 for _, start in nights])
    d.n, d.entries, d.query = len(d.days), entries, np.asarray(query, np.int32)
    d.entry_half = np.asarray([m.e.ie7.half(r['entry_date']) for r in entries])
    d.row_half = np.asarray([m.e.ie7.half(day) for day in d.days])
    d.primary = np.ones(len(entries), bool)
    d.group = np.repeat(np.arange(42), 24)
    d.specs = [dict(name='factor_' + str(j), length=j + 1, formula='x' * (j + 1)) for j in range(6)]
    d.specs += [dict(name=name, length=30) for name in m.e.ANCHORS]
    d.name_index = {s['name']: j for j, s in enumerate(d.specs)}
    d.library_n = 6
    d.x = np.random.default_rng(25).random((len(d.specs), d.n), dtype=np.float32)
    d.x[0, d.query[:, -1]] = .999
    d.baseline_values = np.zeros((d.n, len(m.e.ie9.NAMES)), np.float32)
    d.baseline_score = d.x[-1].copy()
    d.baseline_ranks = d.rank(d.baseline_score)
    d.base = type('Base', (), dict(meta={'days': list(d.slices)}))()
    d.current_label, d.current_query = 'synthetic', d.query
    d._engine = None
    return d


class IE25Tests(unittest.TestCase):
    def test_window_uses_trading_sessions_and_last_signal_buys_three_days_late(self):
        start = date(2001, 1, 1)
        days = [(start + timedelta(days=k)).isoformat() for k in range(20)
                if (start + timedelta(days=k)).weekday() < 5]
        entry = days[6]
        nights = m.window(days, entry)
        self.assertEqual(nights, days[2:9])
        self.assertEqual(days.index(nights[-1]) + 1 - days.index(entry), 3)
        self.assertEqual(m.window(days, days[-1])[-2:], [None, None])

    def test_coverage_is_union_and_unavailable_targets_stay_in_denominator(self):
        d = synthetic()
        scores = np.zeros(d.n)
        scores[d.query[:, -1]] = 10
        d.current_query = d.query.copy()
        d.current_query[0] = -1
        value = m.coverage(d, scores, list(m.HALVES))
        self.assertEqual(value['primary']['n'], len(d.entries))
        self.assertEqual(value['primary']['hits']['5'], len(d.entries) - 1)
        self.assertGreater(value['best'][0], 5)

    def test_target_description_and_null_both_take_maximum(self):
        values = np.array([[.1, .2, .8, .4], [.9, np.nan, .2, .3]])
        query = np.array([[0, 1, 2], [1, 3, -1], [-1, -1, -1]])
        sampled, maximum, median = m.target_values(values, query)
        np.testing.assert_allclose(maximum[:, :2], [[.8, .4], [.9, .3]])
        np.testing.assert_allclose(median[:, :2], [[.2, .3], [.55, .3]])
        self.assertTrue(np.isnan(maximum[:, 2]).all())

    def test_both_sides_of_held_half_are_embargoed_without_target_dates(self):
        start = date(2000, 12, 20)
        days = [(start + timedelta(days=k)).isoformat() for k in range(410)
                if (start + timedelta(days=k)).weekday() < 5]
        halves = tuple(dict.fromkeys(m.e.ie7.half(day) for day in days))
        held = halves[1]
        slices = {day: slice(i, i + 1) for i, day in enumerate(days)}
        row_halves = np.array([m.e.ie7.half(day) for day in days])
        with patch.object(m, 'HALVES', halves):
            allowed = set(m.permitted_rows(days, slices, row_halves, [h for h in halves if h != held]))
        positions = np.flatnonzero(row_halves == held)
        first, last = positions[0], positions[-1]
        self.assertTrue(set(range(first - 4, last + 3)).isdisjoint(allowed))
        self.assertIn(first - 5, allowed)
        self.assertIn(last + 3, allowed)

    def test_equal_and_model_training_cannot_even_read_held_labels(self):
        d = synthetic()
        train = list(m.HALVES[:-1])
        forbidden = set(np.flatnonzero(d.entry_half == m.HALVES[-1]))
        original = d.query
        class Restricted:
            def __getitem__(self, i):
                if i in forbidden:
                    raise AssertionError('held label was read')
                return original[i]
        d.current_query = Restricted()
        with patch.object(m.a, 'LOGIT_LEVELS', (1,)), patch.object(m.a, 'BOOST_LEVELS', (2,)):
            fit = m.a.fit_a(d, train)
            desc = m.describe(d, train, d.current_query)
            groups = dict(groups=[dict(representative=j) for j in range(d.library_n)])
            equal = m.e.select(d, train, d.scoped_query(train), groups)
        self.assertEqual(len(fit['candidates']), 2)
        self.assertEqual(len(desc['training_ids']), len(d.entries) - len(forbidden))
        self.assertLessEqual(len(equal['model']['terms']), 5)
        self.assertFalse(set(equal['description']['training_ids']) & {d.entries[i]['id'] for i in forbidden})
        scoped = d.scoped_query(train, original)
        expected = []
        for half in train:
            values = []
            for i in np.flatnonzero(d.entry_half == half):
                q = scoped[i]
                values.append(d.x[0, q[q >= 0]].max())
            expected.append(np.mean(values))
        np.testing.assert_allclose(desc['means'][0], expected)

    def test_inner_pipeline_does_not_access_outer_labels(self):
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
        calls = []
        def fake_fit(data, halves, searcher):
            self.assertTrue(set(halves) <= set(train))
            data.labels(halves)
            calls.append((halves, searcher))
            if searcher == 'A':
                return dict(candidates=[dict(family='logit', level=1, features=[0], weights=[1])])
            return dict(formulas=[('field', 'c')] * 5)
        with (patch.object(m.a, 'cached_fit', side_effect=fake_fit), patch.object(m.a, 'path') as p,
              patch.object(m.a, 'write'), patch.object(m.a, 'predict_b', return_value=d.x[0])):
            p.return_value.exists.return_value = False
            value = m.a.pipeline(d, train)
        self.assertEqual(set(value['models']), {'A', 'B', 'AB'})
        self.assertEqual(len(calls), 2 * (len(train) + 1))

    def test_module_reuse_cannot_redirect_ie23_or_ie24_outputs(self):
        self.assertIsNot(m.e, m.original_e)
        self.assertIsNot(m.a, m.original_a)
        self.assertEqual(m.original_e.PREFIX, 'strong_continue_ie23_')
        self.assertEqual(m.original_a.PREFIX, 'strong_continue_ie24_')
        self.assertEqual(m.e.WORK, m.WORK)
        self.assertEqual(m.a.WORK, m.WORK)
        self.assertEqual(m.SOURCE_WORK.name, 'ie24_work')

    def test_new_source_has_no_literal_stock_or_entry_date(self):
        for source in (Path(m.__file__),):
            for node in ast.walk(ast.parse(source.read_text())):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    self.assertIsNone(re.search(r'\b(?:US\.[A-Z]+|\d{4}-\d{2}-\d{2})\b', node.value))


if __name__ == '__main__':
    unittest.main()
