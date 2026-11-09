import ast
import csv
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

import numpy as np

from studies.trader_replication import martin_continue_ie22 as m


def bars(n=140):
    x = np.arange(n, dtype=float)
    c = 20 + x / 10 + np.sin(x / 6)
    return dict(o=c.copy(), h=c * 1.03, l=c * .97, c=c, v=np.full(n, 100.))


def base_values(n):
    a = np.full((n, len(m.ie9.NAMES)), np.nan)
    a[:, list(m.ie9.NAMES).index('after_inside')] = 0
    a[:, list(m.ie9.NAMES).index('near_ema9')] = np.linspace(0, 1, n)
    return a


class IE22Tests(unittest.TestCase):
    def test_all_features_are_causal_under_truncation_and_future_perturbation(self):
        data = bars()
        data['h'][60] = np.nan
        data['v'][75] = np.nan
        full = m.setup_values(data)
        self.assertEqual(set(full), set(m.NAMES))
        for stop in (55, 80, 120):
            short = m.setup_values({k: a[:stop] for k, a in data.items()})
            changed = {k: a.copy() for k, a in data.items()}
            for a in changed.values():
                a[stop:] *= 7
            altered = m.setup_values(changed)
            for name in m.NAMES:
                np.testing.assert_array_equal(short[name], full[name][:stop], err_msg=name)
                np.testing.assert_array_equal(altered[name][:stop], full[name][:stop], err_msg=name)

    def test_ep_requires_prior_twenty_volume_and_expires_after_three_sessions(self):
        data = {k: np.full(60, value) for k, value in dict(o=100., c=100., h=103., l=97., v=100.).items()}
        data['o'][-4] = 111
        data['h'][-4] = 112
        data['v'][-4] = 200
        values = m.setup_values(data)
        np.testing.assert_array_equal(values['ep'][-4:], [1, 1, 1, 0])
        self.assertAlmostEqual(values['ep_gap'][-3], .11)
        self.assertEqual(values['ep_recency'][-3], -1)
        data['v'][-4] = 199
        self.assertFalse(m.setup_values(data)['ep'].any())
        data['v'][-4] = np.nan
        self.assertFalse(m.setup_values(data)['ep'].any())

    def test_pullback_needs_bullish_emas_recent_high_and_one_adr_distance(self):
        data = bars()
        data['c'] = np.arange(140.) / 10 + 20
        data['h'], data['l'], data['o'] = data['c'] * 1.03, data['c'] * .97, data['c'].copy()
        self.assertEqual(m.setup_values(data)['pullback'][-1], 1)
        data['c'][-1] *= 2
        self.assertEqual(m.setup_values(data)['pullback'][-1], 0)
        falling = {k: a[::-1].copy() for k, a in bars().items()}
        self.assertEqual(m.setup_values(falling)['pullback'][-1], 0)

    def test_breakout_accepts_inside_or_nr7_today_or_yesterday_near_high(self):
        data = {k: np.full(60, value) for k, value in dict(o=100., c=100., h=104., l=96., v=100.).items()}
        data['h'][-2], data['l'][-2] = 101, 99
        data['h'][-1], data['l'][-1] = 103, 97
        values = m.setup_values(data)
        self.assertEqual(values['breakout'][-2], 1)
        self.assertEqual(values['breakout'][-1], 1)
        self.assertEqual(values['after_inside'][-1], 1)
        data['c'][-1] = 70
        self.assertEqual(m.setup_values(data)['breakout'][-1], 0)
        data['c'][-1] = np.nan
        self.assertEqual(m.setup_values(data)['breakout'][-1], 0)

    def test_class_membership_may_overlap_and_other_is_not_a_forecast_label(self):
        values = m.setup_values(bars())
        self.assertTrue(np.any((values['breakout'] == 1) & (values['pullback'] == 1)))
        self.assertNotIn('setup', m.setup_values.__code__.co_varnames)
        for fn in (m.setup_values, m.rank_night):
            self.assertFalse({'entries', 'entry_date', 'target', 'setup'} & set(fn.__code__.co_varnames))

    def test_queues_deduplicate_and_empty_slots_transfer(self):
        queues = [[], [0, 1, 2], [1, 3, 4], [5, 6]]
        fallback = np.arange(7)
        for mode in ('quota', 'round_robin', 'proportional'):
            order = m.merge_queues(queues, fallback, mode, [2, 2, 1, 0])
            self.assertEqual(set(order), set(fallback))
            self.assertEqual(len(order), 7)
            self.assertEqual(len(set(order[:5])), 5)
        order = m.merge_queues([[], [], [], [0, 1]], [0, 1], 'proportional', [1, 2, 2, 0])
        self.assertEqual(order.tolist(), [0, 1])

    def test_class_ranking_is_within_class_and_only_passing_members_can_rank(self):
        values = np.zeros((4, len(m.NAMES)))
        values[:, m.NAMES.index('ep')] = 1
        values[:, m.NAMES.index('ep_gap')] = [1, 2, 100, np.nan]
        scheme = dict(id='synthetic', classes={'ep': ['ep_gap']}, mode='quota', quota=[5, 0, 0, 0])
        order, ranks = m.rank_night(values, np.array([True, True, False, True]), base_values(4), scheme)
        self.assertEqual(order.tolist(), [1, 3, 0])
        self.assertEqual(ranks[2], m.SENTINEL)
        values[2, m.NAMES.index('ep_gap')] = -100
        self.assertEqual(m.rank_night(values, np.array([True, True, False, True]), base_values(4), scheme)[0].tolist(), order.tolist())

    def test_removing_all_classes_reproduces_ie9_exactly(self):
        values = np.zeros((8, len(m.NAMES)))
        passed = np.array([True, False, True, True, True, False, True, True])
        base = base_values(8)
        expected = m.ie9.rank_night(base, passed, list(m.ie9.NAMES), ['after_inside', 'near_ema9'])
        actual = m.rank_night(values, passed, base, m.baseline_scheme())
        for a, b in zip(actual, expected):
            np.testing.assert_array_equal(a, b)

    def test_nightly_rank_ignores_future_feature_rows(self):
        data = bars()
        full = m.setup_values(data)
        short = m.setup_values({k: a[:80] for k, a in data.items()})
        a = np.array([[full[k][i] for k in m.NAMES] for i in (77, 78, 79)])
        b = np.array([[short[k][i] for k in m.NAMES] for i in (77, 78, 79)])
        scheme = m.propose(1)[0]
        for x, y in zip(m.rank_night(a, np.ones(3, bool), base_values(3), scheme),
                        m.rank_night(b, np.ones(3, bool), base_values(3), scheme)):
            np.testing.assert_array_equal(x, y)

    def test_six_half_expectation_uses_union_and_preserves_outside_nights(self):
        e = dict(id='synthetic', entry_date=m.ie9.YEARS[0] + '-03-01', target=dict(tier='primary'))
        r = m.expectation([e], [[0, 1, -1, 2]], np.array([True, True, False]), np.array([10, 20, 10]))
        self.assertEqual(len(r['halfyear']), 6)
        self.assertAlmostEqual(r['halfyear'][m.HALVES[0]]['union'], 1 - .5 * .75)

    def test_qualification_enforces_each_baseline_half_even_when_min_unchanged(self):
        def result(hits):
            return dict(coverage=dict(halfyear={h: dict(n=10, hits={'5': n}) for h, n in zip(m.HALVES, hits)}),
                expected=dict(halfyear={h: dict(union=1.) for h in m.HALVES}))
        baseline = result([4, 5, 7, 8])
        self.assertFalse(m.coverage_failures(result([4, 5, 7, 8]), baseline, m.HALVES))
        self.assertIn(m.HALVES[-1] + ':below_IE9', m.coverage_failures(result([4, 5, 7, 7]), baseline, m.HALVES))
        same = result([4, 5, 7, 8])
        same['expected']['halfyear'][m.HALVES[0]]['union'] = 4
        self.assertIn(m.HALVES[0] + ':not_above_union', m.coverage_failures(same, baseline, m.HALVES))

    def test_candidate_budgets_and_directions_are_fixed(self):
        for number in range(1, 5):
            for target in m.GROUPS:
                schemes = m.propose(number, m.propose(1)[0], target)
                self.assertLessEqual(len(schemes), 5)
                for scheme in schemes:
                    m.validate(scheme)
        bad = deepcopy(m.propose(1)[0])
        bad['classes']['ep'] = list(m.NAMES[3:6])
        with self.assertRaises(ValueError):
            m.validate(bad)
        self.assertEqual(len(m.SHUFFLE_SEEDS), 5)
        self.assertEqual(len(set(m.SHUFFLE_SEEDS)), 5)
        self.assertEqual(len(m.RANDOM_SEEDS), 30)

    def test_leave_out_labels_are_excluded_before_any_coverage_is_computed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'ranks.npy'
            np.save(path, np.array([1, 9], np.int32))
            d = m.Data.__new__(m.Data)
            d.entries = [dict(id='a', code='synthetic_a', entry_date=m.ie9.YEARS[0] + '-03-01', target=dict(tier='primary')),
                         dict(id='b', code='synthetic_b', entry_date=m.ie9.YEARS[0] + '-09-01', target=dict(tier='primary'))]
            d.query, d.passed, d.row_width = [[0] * 4, [1] * 4], np.ones(2, bool), np.full(2, 10)
            d.predict = lambda scheme: dict(ranks=str(path), selection_hash='synthetic')
            result = d.result(m.baseline_scheme(), halves=[m.HALVES[0]])
            self.assertEqual([r['id'] for r in result['coverage']['rows']], ['a'])
            self.assertEqual([r['id'] for r in result['expected']['rows']], ['a'])
            self.assertEqual(result['coverage']['halfyear'][m.HALVES[1]]['n'], 0)

    def test_ablation_deletes_redundant_factors_and_preserves_required_ones(self):
        scheme = dict(id='synthetic', classes={'ep': ['ep_recency', 'near_high']}, mode='quota', quota=[5, 0, 0, 0])
        def result(scheme, query=None, halves=None):
            useful = 'ep_recency' in scheme['classes'].get('ep', [])
            rows = [dict(id=h, entry_date=h[:4] + ('-03-01' if h.endswith('1') else '-09-01'),
                         primary=True, best_rank=1 if useful else 9) for h in m.HALVES]
            return dict(scheme=scheme, coverage=dict(rows=rows, halfyear={h: dict(n=1, hits={'5': int(useful)}) for h in m.HALVES}),
                        expected=dict(halfyear={h: dict(union=.1) for h in m.HALVES}))
        accounts = {label: dict(annual={y: dict(entries=52, win=.2) for y in m.ie9.YEARS}) for label in ('cash6', 'lever')}
        d = SimpleNamespace(result=result, fixed_accounts=lambda scheme: accounts)
        base = result(scheme)
        start = m.qualify(d, result(scheme), base, m.HALVES)
        value = m.ablate(d, start, base, m.HALVES, [])
        self.assertEqual(value['final']['scheme']['classes'], {'ep': ['ep_recency']})
        self.assertTrue(value['final']['eligible'])

    def test_selection_key_ignores_returns_and_prefers_fewer_factors_before_all_entries(self):
        def result(scheme, count, profit):
            return dict(scheme=scheme, eligible=True, accounts={'return': profit},
                coverage=dict(halfyear={h: dict(n=10, hits={'5': 4}) for h in m.HALVES},
                    rows=[dict(entry_date=m.ie9.YEARS[0] + '-03-01', best_rank=1) for _ in range(count)]))
        simple = result(m.baseline_scheme(), 1, -100)
        complex_result = result(m.propose(1)[0], 10, 100)
        self.assertIs(m.winner([complex_result, simple], m.HALVES), simple)
        simple['eligible'] = False
        self.assertIs(m.winner([complex_result, simple], m.HALVES), complex_result)

    def test_source_has_no_human_security_or_entry_date_literals(self):
        constants = {n.value for n in ast.walk(ast.parse(Path(m.__file__).read_text()))
                     if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        with (m.ROOT / 'studies/martin_luk/notes/trades.csv').open() as stream:
            records = list(csv.DictReader(stream))
        forbidden = {r['ticker'] for r in records} | {'US.' + r['ticker'] for r in records}
        forbidden |= {r['entry_date'] for r in records if r['entry_date']}
        self.assertFalse(constants & forbidden)


if __name__ == '__main__':
    unittest.main()
