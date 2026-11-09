import ast
from copy import deepcopy
from pathlib import Path
import re
import unittest
from unittest.mock import patch

import numpy as np

from studies.trader_replication import martin_continue_ie24 as m
from studies.trader_replication import ie24_formulas as gp


def synthetic():
    d = m.Data.__new__(m.Data)
    d.n = 6 * 4 * 24
    d.slices, d.days, d.codes, entries, query = {}, [], [], [], []
    rng = np.random.default_rng(812)
    for h in m.HALVES:
        start = len(d.days)
        for t in range(4):
            day = h + '_night_' + str(t)
            a = len(d.days)
            d.slices[day] = slice(a, a + 24)
            d.days.extend([day] * 24)
            d.codes.extend(['asset_' + str(k) for k in range(24)])
        for k in range(2):
            entries.append(dict(primary=True, half=h))
            query.append([start + 24 * t + 3 + k for t in range(4)])
    d.entries, d.query = entries, np.asarray(query)
    d.current_query = d.query
    d.primary = np.ones(len(entries), bool)
    d.entry_half = np.array([e['half'] for e in entries])
    d.row_half = np.array([day.split('_')[0] for day in d.days])
    d.group = np.repeat(np.arange(24), 24)
    d.specs = [dict(name='factor_' + str(j)) for j in range(12)]
    d.x = rng.random((12, d.n), dtype=np.float32)
    d.x[0, d.query.ravel()] = .98
    d.current_label = 'synthetic'
    d.base = type('Base', (), dict(meta={'days': []}))()
    return d


class IE24Tests(unittest.TestCase):
    def test_formula_count_breaks_coverage_ties_before_node_count(self):
        larger = ('add', ('div', ('field', 'c'), ('field', 'v')),
                  ('mul', ('field', 'iv'), ('field', 'hv')))
        single = dict(model=dict(b=[larger]), rates=[.5, .5], order=0)
        triple = dict(model=dict(b=[('field', 'o'), ('field', 'h'), ('field', 'l')]),
                      rates=[.5, .5], order=1)
        self.assertIs(m.choose_rows([single, triple]), single)

    def test_segmented_average_ranks_and_missing(self):
        values = np.array([4, 2, 2, np.nan, 8, 3, 9, 1])
        groups = np.array([0, 0, 0, 0, 1, 1, 2, 3])
        expected = [1, .25, .25, np.nan, 1, 0, .5, .5]
        np.testing.assert_allclose(gp.percentile(values, groups), expected, equal_nan=True)

    def test_every_operator_is_causal_under_truncation_and_future_changes(self):
        rng = np.random.default_rng(29)
        fields = {k: rng.random((6, 280), dtype=np.float32) + 2 for k in gp.FIELDS}
        fields['c'][0, :25] = np.nan
        fields['c'][1, ::7] = np.nan
        si = np.tile(np.arange(6), 280)
        ti = np.repeat(np.arange(280), 6)
        engine = gp.Engine(fields, si, ti, ti)
        cut = 263
        changed = {k: v.copy() for k, v in fields.items()}
        for value in changed.values():
            value[:, cut:] = rng.random(value[:, cut:].shape) * 100
        future = gp.Engine(changed, si, ti, ti)
        shortened = gp.Engine({k: v[:, :cut] for k, v in fields.items()}, si[:cut * 6], ti[:cut * 6], ti[:cut * 6])
        leaf = ('field', 'c')
        trees = [(op, ('field', 'o'), leaf) for op in gp.BINARY]
        trees += [(op, leaf) for op in ('neg', 'adr', 'history250', 'pool')]
        trees += [(op, w, leaf) for op in gp.WINDOWED for w in gp.WINDOWS]
        trees += [('mean', 10, ('pool', leaf)), ('pool', ('history250', leaf))]
        for tree in trees:
            with self.subTest(formula=gp.expression(tree)):
                expected = engine.panel(tree)[:, :cut]
                np.testing.assert_allclose(expected, future.panel(tree)[:, :cut], atol=1e-6, rtol=1e-5, equal_nan=True)
                np.testing.assert_allclose(expected, shortened.panel(tree), atol=1e-6, rtol=1e-5, equal_nan=True)

    def test_formula_limits_correlation_and_resume(self):
        rng = np.random.default_rng(98)
        fields = {k: rng.random((12, 20), dtype=np.float32) + 1 for k in gp.FIELDS}
        si, ti = np.tile(np.arange(12), 20), np.repeat(np.arange(20), 12)
        engine = gp.Engine(fields, si, ti, ti)
        targets = {'first': [np.array([4, 16])], 'second': [np.array([31, 43])]}
        checkpoints = []
        result = gp.evolve(engine, targets, np.arange(len(si)), 29, save=checkpoints.append)
        self.assertTrue(all(gp.valid(gp.freeze(t)) for t in result['formulas']))
        self.assertEqual(len(result['history']), 20)
        resumed = gp.evolve(engine, targets, np.arange(len(si)), 29, checkpoint=checkpoints[9])
        self.assertEqual(result, resumed)
        column = engine.column(('field', 'c'))
        duplicate = ('add', ('field', 'c'), ('field', 'c'))
        selected = gp.diverse(engine, [('field', 'c'), duplicate], targets, np.arange(len(si)))
        self.assertEqual(len(selected), 1)
        self.assertTrue(np.all(np.isfinite(column)))

    def test_equal_half_entry_and_night_weights(self):
        d = synthetic()
        targets = {'a': [np.array([3, 27]), np.array([51])], 'b': [np.array([99])], 'c': [np.array([], int)]}
        groups = d.groups(targets)
        weights = {q: w for sl, positive in groups for q, w in positive.items()}
        self.assertAlmostEqual(weights[3], .125)
        self.assertAlmostEqual(weights[27], .125)
        self.assertAlmostEqual(weights[51], .25)
        self.assertAlmostEqual(weights[99], .5)
        self.assertAlmostEqual(sum(weights.values()), 1)

    def test_actual_model_search_ignores_held_labels(self):
        d = synthetic()
        train = list(m.HALVES[:-1])
        with patch.object(m, 'LOGIT_LEVELS', (1, 3)), patch.object(m, 'BOOST_LEVELS', (2,)), patch.object(m.Data, 'release_pages'):
            first = m.fit_a(d, train)
            d.current_query = d.query.copy()
            d.current_query[d.entry_half == m.HALVES[-1]] = -999
            second = m.fit_a(d, train)
        self.assertEqual(first, second)
        for model in first['candidates']:
            score = m.predict_a(d, model)
            ranks = d.rank(score)
            self.assertLessEqual(int(ranks[d.query[0]].min()), 5)

    def test_nested_orchestration_never_reads_outer_labels(self):
        d = synthetic()
        train = list(m.HALVES[:-1])
        calls = []
        original_coverage = m.coverage
        def fake_fit(data, halves, searcher):
            self.assertTrue(set(halves) <= set(train))
            calls.append((tuple(halves), searcher))
            data.labels(halves)
            if searcher == 'A':
                return dict(candidates=[dict(family='logit', level=1, features=[0], weights=[1])])
            return dict(formulas=[('field', 'c')] * 5)
        def checked_coverage(data, score, halves, permitted=None):
            self.assertTrue(set(halves) <= set(train))
            return original_coverage(data, score, halves, permitted)
        with (patch.object(m, 'cached_fit', side_effect=fake_fit), patch.object(m, 'path') as p,
              patch.object(m, 'write'), patch.object(m, 'predict_b', return_value=d.x[0]),
              patch.object(m, 'coverage', side_effect=checked_coverage), patch.object(m.Data, 'release_pages')):
            p.return_value.exists.return_value = False
            result = m.pipeline(d, train)
        self.assertEqual(len(calls), 2 * (len(train) + 1))
        self.assertEqual(set(result['models']), {'A', 'B', 'AB'})

    def test_formula_fitness_reads_only_supplied_training_targets(self):
        d = synthetic()
        train = list(m.HALVES[:-1])
        a = d.labels(train)
        d.current_query = d.query.copy()
        d.current_query[d.entry_half == m.HALVES[-1]] = -999
        b = d.labels(train)
        leaf = ('field', 'c')
        self.assertEqual(gp.fitness(d.x[0], a, leaf), gp.fitness(d.x[0], b, leaf))

    def test_training_label_boundary_rejects_even_reading_a_held_entry(self):
        d = synthetic()
        train = list(m.HALVES[:-1])
        forbidden = set(np.flatnonzero(d.entry_half == m.HALVES[-1]))
        original = d.current_query
        class Restricted:
            def __getitem__(self, index):
                if index in forbidden:
                    raise AssertionError('held label was read')
                return original[index]
        d.current_query = Restricted()
        with (patch.object(m, 'LOGIT_LEVELS', (1,)), patch.object(m, 'BOOST_LEVELS', (2,)),
              patch.object(m.Data, 'release_pages')):
            model = m.fit_a(d, train)
            targets = d.labels(train)
        self.assertEqual(len(model['candidates']), 2)
        self.assertEqual(set(targets), set(train))

    def test_no_literal_identity_or_entry_date_in_search_code(self):
        for source in (Path(m.__file__), Path(gp.__file__)):
            tree = ast.parse(source.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    self.assertIsNone(re.search(r'\b(?:US\.[A-Z]+|\d{4}-\d{2}-\d{2})\b', node.value))
            self.assertNotIn('trades.csv\').read', source.read_text())


if __name__ == '__main__':
    unittest.main()
