import ast
import csv
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

from studies.trader_replication import martin_continue_ie11 as m


def sample():
    t = np.arange(100.)[:, None]
    j = np.arange(12.)[None, :]
    close = 20 + (t + 1) * (j + 1) / 50 + np.cos(t / 7 + j)
    pot = (t + j) % 3 == 0
    history = (t + j) % 5 <= 1
    groups = [list(range(6)), list(range(5, 12)), [1, 2, 6, 7, 10]]
    return close, pot, history, groups


class IE11Tests(unittest.TestCase):
    def test_all_plate_factors_are_prefix_causal(self):
        close, pot, history, groups = sample()
        full = m.member_factors(close, pot, history, groups)
        for cut in (40, 75):
            short = m.member_factors(close[:cut], pot[:cut], history[:cut], groups)
            for name in m.METRICS:
                np.testing.assert_array_equal(full[name][:cut], short[name], err_msg=name)
        close[75:] *= 100
        pot[75:] = ~pot[75:]
        history[75:] = ~history[75:]
        changed = m.member_factors(close, pot, history, groups)
        for name in m.METRICS:
            np.testing.assert_array_equal(full[name][:75], changed[name][:75], err_msg=name)

    def test_five_available_members_required_for_each_window(self):
        close, pot, history, _ = sample()
        values = m.member_factors(close, pot, history, [[0, 1, 2, 3]])
        for name in m.METRICS:
            self.assertTrue(np.isnan(values[name]).all(), name)
        close[30, 4] = np.nan
        values = m.member_factors(close, pot, history, [[0, 1, 2, 3, 4]])
        self.assertTrue(np.isnan(values['heat20'][30]).all())
        self.assertTrue(np.isnan(values['heat20'][50]).all())
        self.assertTrue(np.isnan(values['diffusion_pot'][30]).all())
        self.assertTrue(np.isfinite(values['heat20'][31, :5]).all())

    def test_missing_membership_and_empty_concepts_stay_missing(self):
        close, pot, history, _ = sample()
        values = m.member_factors(close, pot, history, [])
        for name in m.METRICS:
            self.assertTrue(np.isnan(values[name]).all(), name)
        values = m.member_factors(close, pot, history, [list(range(6))])
        self.assertTrue(np.isnan(values['heat20'][:, 6:]).all())
        self.assertTrue((values['hot_count'][65:, :6] == 0).all())

    def test_equal_weight_plate_heat_and_member_leadership(self):
        t = np.arange(90.)[:, None]
        close = np.concatenate([np.exp(t * .001) * np.ones((1, 5)),
                                np.exp(t * .01) * np.ones((1, 5))], axis=1)
        strong = np.zeros(close.shape, bool)
        values = m.member_factors(close, strong, strong, [list(range(5)), list(range(5, 10))])
        np.testing.assert_array_equal(values['heat20'][65:, :5], 0)
        np.testing.assert_array_equal(values['heat20'][65:, 5:], 1)
        np.testing.assert_array_equal(values['leader20'][65:], .5)
        np.testing.assert_array_equal(values['hot_count'][65:, :5], 0)
        np.testing.assert_array_equal(values['hot_count'][65:, 5:], 1)

    def test_multiple_plates_use_best_heat_and_count_each_hot_plate(self):
        close, pot, history, groups = sample()
        values = m.member_factors(close, pot, history, groups)
        separate = [m.member_factors(close, pot, history, [g]) for g in groups]
        # Leadership is independent of how many other plates are in the inventory.
        expected = np.fmax.reduce([s['leader20'] for s in separate])
        np.testing.assert_array_equal(values['leader20'], expected)
        self.assertTrue(np.nanmax(values['hot_count']) <= len(groups))

    def test_diffusion_is_fraction_of_members_and_zero_is_valid(self):
        close, pot, history, _ = sample()
        pot[:] = False
        pot[:, :2] = True
        history[:] = False
        values = m.member_factors(close, pot, history, [list(range(5))])
        np.testing.assert_allclose(values['diffusion_pot'][:, :5], .4)
        np.testing.assert_array_equal(values['diffusion_history'][:, :5], 0)

    def test_rank_equal_weights_events_and_recomputed_percentiles(self):
        values = np.full((4, len(m.NAMES)), np.nan)
        values[:, m.NAMES.index('after_inside')] = [0, 1, 1, 0]
        values[:, m.NAMES.index('near_ema9')] = [.1, .2, .8, 1.]
        factors = [dict(name=n, direction=1) for n in m.ie10.FACTORS]
        order, ranks = m.rank_night(values, np.array([True, True, True, False]), factors)
        self.assertEqual(order.tolist(), [2, 1, 0])
        self.assertEqual(ranks[-1], m.old.prior.SENTINEL)
        order, _ = m.rank_night(values, np.zeros(4, bool), factors)
        self.assertEqual(order.tolist(), [])

    def test_condition_thresholds_keep_missing_out(self):
        values = np.array([0, .3, .5, .7, 1, np.nan])
        c = dict(kind='percentile', cutoff=.7, direction=1)
        self.assertEqual(m.ie10.filter_mask(values, c).tolist(), [False, False, False, True, True, False])
        c['direction'] = -1
        self.assertEqual(m.ie10.filter_mask(values, c).tolist(), [True, True, False, False, False, False])

    def test_branch_and_budget_validation(self):
        condition = dict(name='industry.heat20', kind='percentile', direction=1, cutoff=.5)
        scheme = dict(kind='industry', filters=[condition], factors=[dict(name='industry.heat20', direction=1)])
        m.validate(scheme, [condition])
        for candidate in (dict(scheme, kind='concept'), dict(scheme, filters=[condition] * 4),
                          dict(scheme, factors=[dict(name='industry.heat20', direction=-1)])):
            with self.assertRaises(ValueError):
                m.validate(candidate, [condition])

    def test_halfyear_qualification_uses_four_night_union(self):
        coverage = dict(halfyear={h: dict(hits={'5': 2}) for h in m.HALVES})
        expected = dict(halfyear={h: dict(union=1.9, best_night=.3) for h in m.HALVES})
        accounts = {kind: dict(annual={y: dict(entries=52, win=.35) for y in m.YEARS}) for kind in ('cash6', 'lever')}
        self.assertTrue(m.ie10.qualify(coverage, expected, accounts)[0])
        expected['halfyear'][m.HALVES[0]]['union'] = 2
        self.assertFalse(m.ie10.qualify(coverage, expected, accounts)[0])

    def test_control_reuse_gets_new_seed(self):
        previous = m.ie9.RANDOM_SEED
        with patch.object(m.ie9, 'random_controls', side_effect=lambda d, r: m.ie9.RANDOM_SEED):
            self.assertEqual(m.random_controls(None, None), m.RANDOM_SEED)
        self.assertEqual(previous, m.ie9.RANDOM_SEED)

    def test_upstream_selection_requires_feasibility_then_minimum_width(self):
        def result(feasible, width, retention):
            return dict(feasible=feasible, minimum_retention=retention,
                        scheme=dict(filters=[{}, {}, {}]),
                        width={k: dict(median=width) for k in (*m.YEARS, 'combined')})
        narrow_failure = result(False, 5, .89)
        feasible = result(True, 70, 1.)
        narrower = result(True, 60, .91)
        self.assertIs(max([narrow_failure, feasible, narrower], key=m.upstream_key), narrower)

    def test_task_tie_rule_prefers_all_entry_coverage_before_rank_factor_count(self):
        def result(factors, all_hits):
            return dict(eligible=True, scheme=dict(filters=[], factors=[{}] * factors),
                        coverage=dict(halfyear={h: dict(n=4, hits={'5': 2}) for h in m.HALVES},
                                      all_entries=dict(n=10, hits={'5': all_hits})))
        fewer_factors = result(1, 4)
        more_coverage = result(4, 5)
        self.assertIs(m.winner([fewer_factors, more_coverage]), more_coverage)

    def test_ablation_restarts_and_preserves_a_necessary_rank_factor(self):
        class Fake:
            def evaluate(self, scheme):
                needed = any(f['name'] == 'needed' for f in scheme['factors'])
                return dict(scheme=scheme, eligible=True, score=[.4 if needed else .2])
        start = dict(id='synthetic', filters=[dict(name='extra')],
                     factors=[dict(name='needed', direction=1), dict(name='redundant', direction=1)])
        d = Fake()
        a = m.ablate(d, d.evaluate(start))
        self.assertEqual(a['final']['scheme']['filters'], [])
        self.assertEqual(a['final']['scheme']['factors'], [dict(name='needed', direction=1)])
        self.assertGreater(len(a['rounds']), 1)

    def test_source_has_no_human_security_or_entry_date_literals(self):
        source = Path(m.__file__).read_text()
        constants = {n.value for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        with (m.ROOT / 'studies/martin_luk/notes/trades.csv').open() as stream:
            records = list(csv.DictReader(stream))
        forbidden = {r['ticker'] for r in records} | {'US.' + r['ticker'] for r in records}
        forbidden |= {r['entry_date'] for r in records if r['entry_date']}
        self.assertFalse(constants & forbidden)
        self.assertNotIn('门禁', source)


if __name__ == '__main__':
    unittest.main()
