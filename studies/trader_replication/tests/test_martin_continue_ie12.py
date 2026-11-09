import ast
import csv
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from studies.trader_replication import martin_continue_ie12 as m


class IE12Tests(unittest.TestCase):
    def test_membership_history_uses_only_current_and_previous_nights(self):
        passed = np.array([False, True, True, False, True, True, True, False] * 8)
        full = m.sequence_values(passed)
        for cut in (2, 5, 21, 45):
            short = m.sequence_values(passed[:cut])
            changed = passed.copy()
            changed[cut:] = ~changed[cut:]
            future = m.sequence_values(changed)
            for name in full:
                np.testing.assert_array_equal(full[name][:cut], short[name])
                np.testing.assert_array_equal(full[name][:cut], future[name][:cut])
        np.testing.assert_array_equal(full['pool_streak'][:7], [0, 1, 2, 0, 1, 2, 3])
        np.testing.assert_array_equal(full['pool_gap'][1:5], [63, 1, 1, 2])
        self.assertEqual(full['pool_visits20'][20], passed[1:21].sum())

    def test_path_and_observable_state_are_prefix_causal(self):
        t = np.arange(260)
        c = 20 + t / 50 + np.sin(t / 7)
        arrays = dict(c=c, o=c * 1.001, h=c * 1.02, l=c * .98, v=1000 + t)
        arrays['o'][160] = arrays['c'][159] * 1.05
        arrays['v'][160] *= 3
        full = m.path_values(arrays)
        for cut in (100, 161, 220):
            short = m.path_values({k: a[:cut] for k, a in arrays.items()})
            changed = {k: a.copy() for k, a in arrays.items()}
            for a in changed.values():
                a[cut:] *= 50
            future = m.path_values(changed)
            for name in full:
                np.testing.assert_array_equal(full[name][:cut], short[name][:cut], err_msg=name)
                np.testing.assert_array_equal(full[name][:cut], future[name][:cut], err_msg=name)
        self.assertEqual(full['state_ep'][160], 1.)
        valid = np.isfinite(full['state_ep'])
        np.testing.assert_array_equal(sum(full[k][valid] for k in m.NEW[4:7]), np.ones(valid.sum()))

    def test_market_is_the_current_cross_section_not_a_full_history_quantile(self):
        self.assertEqual(m.market_value(np.array([-.1, 0., .2, np.nan])), 0.)
        self.assertEqual([m.regime(x) for x in (.1, .5, .9)], ['weak', 'flat', 'strong'])
        self.assertEqual(m.regime(np.nan), 'unknown')
        values = np.sin(np.arange(320) / 17)
        full = m.market_history_percentile(values)
        for cut in (30, 150, 270):
            short = m.market_history_percentile(values[:cut])
            changed = values.copy()
            changed[cut:] += 100
            future = m.market_history_percentile(changed)
            np.testing.assert_array_equal(full[:cut], short)
            np.testing.assert_array_equal(full[:cut], future[:cut])
        self.assertTrue(np.isnan(full[:19]).all())

    def test_selected_regression_families_and_five_night_delta_are_prefix_causal(self):
        t = np.arange(180)
        c = 30 + t / 60 + np.sin(t / 4)
        arrays = dict(c=c, o=c, h=c * 1.02, l=c * .98, v=1000 + t, raw_c=c, t=c * 1000)
        specs = [('statistics', n, key) for n in (3, 5, 10)
                 for key in ('linearreg', 'linearreg_intercept', 'tsf')]
        full = m.prior.context_values(arrays, {}, list(range(len(c))), c * 2, specs)
        cut = 130
        short = m.prior.context_values({k: a[:cut] for k, a in arrays.items()}, {},
            list(range(cut)), c[:cut] * 2, specs)
        for name in full:
            np.testing.assert_array_equal(full[name][:cut], short[name], err_msg=name)
        days = [str(i) for i in range(30)]
        scope = {day: ['synthetic_a', 'synthetic_b', 'synthetic_c'] for day in days}
        slices = {day: slice(3 * i, 3 * i + 3) for i, day in enumerate(days)}
        raw = np.sin(np.arange(180).reshape(90, 2) / 7)
        values, missing = m.prior.prior.corrected_delta(raw, dict(days=days, scope=scope), slices)
        stop = 20
        limited = {day: slices[day] for day in days[:stop]}
        before, _ = m.prior.prior.corrected_delta(raw[:stop * 3],
            dict(days=days[:stop], scope=scope), limited)
        np.testing.assert_array_equal(values[:stop * 3], before)
        changed = raw.copy()
        changed[stop * 3:] *= -100
        after, _ = m.prior.prior.corrected_delta(changed, dict(days=days, scope=scope), slices)
        np.testing.assert_array_equal(values[:stop * 3], after[:stop * 3])
        self.assertTrue(missing[:15].all())

    def test_saved_model_never_reads_other_nights_or_ledger_fields(self):
        names = ['a', 'b']
        x = np.array([[.1, .8], [.4, .4], [.9, .2], [np.nan, .3]])
        model = dict(terms=[dict(weight=2., rule={'and': [dict(name='a', shape='middle'),
            dict(name='b', shape='band', low=.3, high=1.)]}),
            dict(weight=.5, rule=dict(name='b', shape='down'))])
        full = m.predict(x, names, model)
        changed = x.copy()
        changed[2:] = 100
        np.testing.assert_array_equal(full[:2], m.predict(x[:2], names, model))
        np.testing.assert_array_equal(full[:2], m.predict(changed, names, model)[:2])
        self.assertAlmostEqual(full[-1], .35)

    def test_training_bundle_excludes_held_out_features_and_target_labels(self):
        years = m.prior.YEARS
        d = SimpleNamespace(entries=[dict(id='synthetic_a', entry_date=years[0] + '-01-02',
            target=dict(tier='primary'), systems=dict(h4=[dict(date='night_a')])),
            dict(id='synthetic_b', entry_date=years[1] + '-01-02', target=dict(tier='primary'),
                 systems=dict(h4=[dict(date='night_b')]))],
            query=[[0], [2]], slices=dict(night_a=slice(0, 2), night_b=slice(2, 4)),
            x=np.array([[.1], [.2], [.8], [.9]]))
        before = m.training_bundle(d, {years[0]})
        d.entries[1]['target']['tier'] = 'secondary'
        d.x[2:] = 1000
        after = m.training_bundle(d, {years[0]})
        np.testing.assert_array_equal(before['x'], after['x'])
        self.assertEqual(before['ids'], ['synthetic_a'])
        self.assertEqual(before['ids'], after['ids'])

    def test_entire_fit_ignores_held_out_values_and_labels(self):
        years = m.prior.YEARS
        entries = [dict(id='synthetic_' + str(i), entry_date=y + '-01-02',
            target=dict(tier='primary'), systems=dict(h4=[dict(date=day)]))
            for i, (y, day) in enumerate(zip(years, ('night_a', 'night_b')))]
        d = SimpleNamespace(entries=entries, query=[[1], [4]], names=['signal', 'other'],
            slices=dict(night_a=slice(0, 3), night_b=slice(3, 6)),
            x=np.array([[.1, .8], [.5, .5], [.9, .2], [.2, .3], [.5, .7], [.9, .2]]))
        spec = dict(id='synthetic', universe='all', bands=True, terms=2)
        reg = dict(core_features=d.names, cutoffs=[.4, .6], middle_bands=[[.4, .6]],
            weights=[1., 2.], refinement_passes=1)
        before = m.fit_model(d, {years[0]}, spec, reg)
        d.x[3:] = np.nan
        d.entries[1]['target']['tier'] = 'secondary'
        d.query[1] = [-1]
        after = m.fit_model(d, {years[0]}, spec, reg)
        self.assertEqual(before, after)

    def test_shuffle_is_one_shared_permutation_per_night_and_preserves_absence(self):
        meta = dict(names=['signal'], entries=[{}, {}, {}],
            query=[[0, 3, -1], [0, 3, -1], [1, 4, -1]],
            slices=dict(night_a=[0, 3], night_b=[3, 6]))
        with patch.object(m.prior.ie7, 'read', return_value=meta), \
                patch.object(m.np, 'load', return_value=np.zeros((6, 1))):
            d = m.Data(shuffled=True)
        self.assertEqual(d.query[0], d.query[1])
        for a, b in zip(d.query[0][:2], d.query[2][:2]):
            self.assertNotEqual(a, b)
        self.assertTrue(all(q[-1] == -1 for q in d.query))

    def test_selected_coil_source_is_prefix_causal(self):
        t = np.arange(180)[:, None]
        j = np.arange(1, 7)[None, :]
        c = 25 + t / 40 + j * np.sin(t / (5 + j)) / 10

        def calculate(close):
            e9 = np.column_stack([m.prior.lib.smooth(a, 9) for a in close.T])
            d = SimpleNamespace(c=close, h=close * 1.03, l=close * .97,
                e9=e9, adr=np.full(close.shape, .06))
            return m.prior.old.hj.coil_fields_chunked(d, width=3)

        full = calculate(c)
        cut = 130
        short = calculate(c[:cut])
        changed = c.copy()
        changed[cut:] *= 100
        future = calculate(changed)
        for name in full:
            np.testing.assert_array_equal(full[name][:cut], short[name], err_msg=name)
            np.testing.assert_array_equal(full[name][:cut], future[name][:cut], err_msg=name)

    def test_bag_ranks_match_four_night_union_and_stable_ties(self):
        bundle = dict(bags=[[(np.arange(3), 1), (np.arange(3, 6), 4)], []])
        score = np.array([0., 0., .2, .8, 0., .1])
        values = np.array([[1., 0.], [0., 1.], [1., 0.], [0., 1.], [1., 0.], [0., 1.]])
        ranks = m.candidate_ranks(bundle, score, values, .5)
        for j in range(2):
            trial = score + values[:, j] * .5
            observed = []
            for rows, q in bundle['bags'][0]:
                order = rows[np.argsort(-trial[rows], kind='stable')]
                observed.append(1 + int(np.flatnonzero(order == q)[0]))
            self.assertEqual(ranks[0, j], min(observed))
        self.assertTrue((ranks[1] == m.prior.old.prior.SENTINEL).all())

    def test_state_interactions_have_two_leaves_and_disjoint_market_boundaries(self):
        names = ['signal'] + list(m.NEW[4:7]) + ['market_percentile']
        x = np.array([[.4, 1., 0., 0., 0.], [.4, 0., 1., 0., 2 / 3]])
        rules = m.make_candidates(dict(x=x), names, dict(universe='core', bands=False, interactions='state'),
            dict(core_features=['signal']))
        self.assertEqual(len(rules), 21)
        for r in rules:
            if 'and' in r:
                self.assertEqual(len(r['and']), 2)
                self.assertTrue(all('name' in leaf for leaf in r['and']))
        market = [r['and'][0] for r in rules if 'and' in r and r['and'][0]['name'] == 'market_percentile']
        np.testing.assert_array_equal(m.basis_value(x, names, market[0]), [1., 0.])
        np.testing.assert_array_equal(m.basis_value(x, names, market[3]), [0., 0.])
        np.testing.assert_array_equal(m.basis_value(x, names, market[6]), [0., 1.])

    def test_source_has_no_human_security_or_entry_date_literals(self):
        sources = [Path(m.__file__), Path(__file__)]
        with (m.ROOT / 'studies/martin_luk/notes/trades.csv').open() as stream:
            records = list(csv.DictReader(stream))
        forbidden = {r['ticker'] for r in records} | {'US.' + r['ticker'] for r in records}
        forbidden |= {r['entry_date'] for r in records if r['entry_date']}
        for source in sources:
            constants = {n.value for n in ast.walk(ast.parse(source.read_text()))
                         if isinstance(n, ast.Constant) and isinstance(n.value, str)}
            self.assertFalse(constants & forbidden, source.name)
        self.assertNotIn('\u95e8\u7981', Path(m.__file__).read_text())


if __name__ == '__main__':
    unittest.main()
