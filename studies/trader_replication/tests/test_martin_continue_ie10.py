import ast
import csv
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from studies.trader_replication import martin_continue_ie10 as m


def sample(n=340):
    x = np.arange(n, dtype=float)
    c = 30 + x / 20 + np.sin(x / 5)
    arrays = dict(c=c, o=c * .99, h=c * 1.03, l=c * .97,
                  v=1000 + 100 * np.cos(x / 3), raw_c=c, t=c * 1000)
    extras = {k: 100 + x + np.cos(x / 5) for k in
              ('iv', 'call_volume', 'put_volume', 'option_volume', 'option_open_interest')}
    extras['earn_days'] = x % 50
    extras['earn_index'] = (x - x % 50).astype(int)
    return arrays, extras


def result(hits=(2, 2, 2, 4), conditions=(), all_hits=10, eligible=True):
    halves = {h: dict(n=n, hits={'5': k}) for h, n, k in zip(m.HALVES, (5, 6, 4, 13), hits)}
    r = dict(scheme=dict(id='synthetic', base_filters=m.ie9.GATES, factors=list(m.FACTORS), filters=list(conditions)),
             coverage=dict(halfyear=halves, all_entries=dict(n=32, hits={'5': all_hits})),
             eligible=eligible, failures=[])
    r['score'] = list(m.score_key(r))
    return r


class IE10Tests(unittest.TestCase):
    def test_new_option_and_event_columns_are_prefix_causal(self):
        _, extras = sample()
        extras['iv'][100] = np.nan
        full = m.derived_values(extras)
        for cut in (85, 120, 285):
            short = m.derived_values({k: v[:cut] for k, v in extras.items()})
            for name in full:
                np.testing.assert_array_equal(full[name][:cut], short[name], err_msg=name)
        changed = {k: v.copy() for k, v in extras.items()}
        for v in changed.values():
            v[285:] *= 100
        after = m.derived_values(changed)
        for name in full:
            np.testing.assert_array_equal(full[name][:285], after[name][:285], err_msg=name)

    def test_call_surge_excludes_current_observation_and_missing_does_not_fill(self):
        _, extras = sample(40)
        extras['call_volume'][:] = 100
        extras['call_volume'][-1] = 300
        self.assertEqual(m.derived_values(extras)['call_surge5'][-1], 3.)
        extras['call_volume'][-3] = np.nan
        self.assertTrue(np.isnan(m.derived_values(extras)['call_surge5'][-1]))
        extras['earn_days'][-1] = np.nan
        self.assertTrue(np.isnan(m.derived_values(extras)['post_earn5'][-1]))

    def test_context_branches_are_causal_including_avwap_and_cost(self):
        arrays, extras = sample()
        specs = [s for s in m.CONTEXT if s[0] != 'group']
        full = m.context_values(arrays, extras, list(range(340)), arrays['c'] * 2, specs)
        for cut in (120, 285):
            short = m.context_values({k: v[:cut] for k, v in arrays.items()},
                {k: v[:cut] for k, v in extras.items()}, list(range(cut)), arrays['c'][:cut] * 2, specs)
            for name in full:
                np.testing.assert_array_equal(full[name][:cut], short[name], err_msg=name)

    def test_other_cached_delta_source_families_are_causal(self):
        arrays, extras = sample()
        specs = [('hilbert', 4, 'quadrature'), ('overlap', 3, 'bb_width'),
                 ('momentum', 14, 'aroon_down'), ('price_transform', 3, 'add'),
                 ('eom', 50, 'change'), ('statistics', 20, 'beta')]
        full = m.context_values(arrays, extras, list(range(340)), arrays['c'] * 2, specs)
        cut = 285
        short = m.context_values({k: v[:cut] for k, v in arrays.items()},
            {k: v[:cut] for k, v in extras.items()}, list(range(cut)), arrays['c'][:cut] * 2, specs)
        for name in full:
            np.testing.assert_array_equal(full[name][:cut], short[name], err_msg=name)

    def test_external_series_use_previous_session_and_ignore_future_rows(self):
        arrays, _ = sample(4)
        days = [f'{m.YEARS[0]}-03-{i:02d}' for i in range(1, 5)]
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / 'short_volume'
            directory.mkdir()
            source = directory / 'synthetic.csv'
            source.write_text('timestamp_str,short_percent\n' + '\n'.join(f'{d},{v}' for d, v in zip(days, (10, 20, 30, 99))))
            full, _, _ = m.external_values('synthetic', days, arrays, [source])
            short, _, _ = m.external_values('synthetic', days[:3], {k: v[:3] for k, v in arrays.items()}, [source])
            np.testing.assert_array_equal(full['short_fraction'][:3], short['short_fraction'])
            self.assertTrue(np.isnan(full['short_fraction'][0]))
            np.testing.assert_allclose(full['short_fraction'][1:], [.1, .2, .3])

    def test_filters_preserve_missing_and_common_percentile_boundaries(self):
        a = np.array([0., .3, .5, .7, 1., np.nan])
        c = dict(kind='percentile', direction=1, cutoff=.7)
        self.assertEqual(m.filter_mask(a, c).tolist(), [False, False, False, True, True, False])
        c['direction'] = -1
        self.assertEqual(m.filter_mask(a, c).tolist(), [True, True, False, False, False, False])
        self.assertEqual(m.filter_mask(a, dict(kind='event', value=0)).tolist(), [True, False, False, False, False, False])

    def test_rank_recomputes_frozen_ema_percentile_after_filtering(self):
        values = np.array([[0., .1], [1., .2], [1., .8], [0., 1.]])
        order, ranks = m.rank_night(values, np.array([True, True, True, False]), list(m.FACTORS))
        self.assertEqual(order.tolist(), [2, 1, 0])
        self.assertEqual(ranks[-1], m.old.prior.SENTINEL)
        order, ranks = m.rank_night(values, np.zeros(4, bool), list(m.FACTORS))
        self.assertEqual(len(order), 0)
        self.assertTrue((ranks == m.old.prior.SENTINEL).all())

    def test_ties_use_stable_input_order(self):
        values = np.ones((4, 2))
        order, _ = m.rank_night(values, np.ones(4, bool), list(m.FACTORS))
        self.assertEqual(order.tolist(), [0, 1, 2, 3])

    def test_selection_uses_min_then_condition_count_then_all_entries_then_order(self):
        base = result(conditions=[dict(name='x')])
        worse = result(hits=(5, 6, 4, 1), conditions=[])
        fewer = result(conditions=[], all_hits=9)
        more_all = result(conditions=[], all_hits=11)
        self.assertIs(m.winner([worse, base, fewer, more_all]), more_all)
        self.assertIs(m.winner([fewer, dict(fewer)]), fewer)
        more_all['eligible'] = False
        self.assertIs(m.winner([fewer, more_all]), fewer)

    def test_qualification_uses_union_instead_of_best_single_night(self):
        coverage = result()['coverage']
        expected = dict(halfyear={h: dict(best_night=.1, union=1.9) for h in m.HALVES})
        accounts = {label: dict(annual={y: dict(entries=52, win=.35) for y in m.YEARS}) for label in ('cash6', 'lever')}
        self.assertTrue(m.qualify(coverage, expected, accounts)[0])
        expected['halfyear'][m.HALVES[0]]['union'] = 2.
        self.assertFalse(m.qualify(coverage, expected, accounts)[0])
        expected['halfyear'][m.HALVES[0]]['union'] = 1.9
        accounts['cash6']['annual'][m.YEARS[1]]['entries'] = 51
        self.assertFalse(m.qualify(coverage, expected, accounts)[0])

    def test_random_control_reuse_receives_this_segments_registered_seed(self):
        previous = m.ie9.RANDOM_SEED
        with patch.object(m.ie9, 'random_controls', side_effect=lambda data, actual: m.ie9.RANDOM_SEED):
            self.assertEqual(m.random_controls(None, None), m.RANDOM_SEED)
        self.assertEqual(m.ie9.RANDOM_SEED, previous)

    def test_validation_keeps_four_base_filters_and_two_rank_factors(self):
        condition = dict(name='synthetic', kind='event', value=1)
        scheme = result(conditions=[condition])['scheme']
        m.validate(scheme, [condition])
        for edit in (dict(base_filters=m.ie9.GATES[:-1]), dict(factors=['after_inside']),
                     dict(filters=[condition] * 5), dict(filters=[dict(condition, value=0)])):
            with self.assertRaises(ValueError):
                m.validate(dict(scheme, **edit), [condition])

    def test_ablation_deletes_only_new_filters_and_restarts(self):
        class Fake:
            def evaluate(self, scheme):
                names = [c['name'] for c in scheme['filters']]
                r = result(hits=(2, 2, 2, 4) if 'needed' in names else (1, 1, 1, 1), conditions=scheme['filters'])
                r['scheme'] = scheme
                return r
        d = Fake()
        start = d.evaluate(result(conditions=[dict(name='extra'), dict(name='needed')])['scheme'])
        after = m.ablate(d, start)
        self.assertEqual(after['final']['scheme']['filters'], [dict(name='needed')])
        self.assertEqual(after['final']['scheme']['base_filters'], m.ie9.GATES)
        self.assertEqual(after['final']['scheme']['factors'], list(m.FACTORS))

    def test_candidate_thresholds_are_fixed_and_events_are_not_percentiled(self):
        records = m.candidates(['inside', 'synthetic'])
        self.assertEqual(len(records), 12)
        self.assertEqual([c['value'] for c in records[:2]], [1, 0])
        self.assertEqual({c['cutoff'] for c in records[2:]}, set(m.CUTOFFS))

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
