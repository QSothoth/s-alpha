import ast
import csv
from pathlib import Path
import unittest

import numpy as np

from studies.trader_replication import martin_continue_ie7 as ie7


class IE7Tests(unittest.TestCase):
    def test_stability_requires_all_four_halves_same_direction(self):
        self.assertEqual(ie7.stability([.65, .8, .9, .7]), ('stable', 1))
        self.assertEqual(ie7.stability([.35, .2, .1, .3]), ('stable', -1))
        self.assertEqual(ie7.stability([.9, .8, .5, .5]), ('unstable', 0))
        self.assertNotEqual(ie7.stability([.9, .8, .7, None])[0], 'stable')
        self.assertNotEqual(ie7.stability([.9, .8, .2, .1])[0], 'stable')

    def test_percentiles_ignore_future_nights_and_preserve_missing(self):
        raw = np.array([[10., np.nan], [20., 2.], [20., 3.]])
        expected = np.array([[0., np.nan], [.75, 0.], [.75, 1.]])
        np.testing.assert_allclose(ie7.night_percentiles(raw), expected, equal_nan=True)
        history = [raw.copy(), raw * 2, raw * 3]
        first = [ie7.night_percentiles(x) for x in history]
        history[-1][:] = -100
        again = [ie7.night_percentiles(x) for x in history]
        np.testing.assert_array_equal(first[0], again[0])
        np.testing.assert_array_equal(first[1], again[1])

    def test_description_counts_missing_and_scope_absence(self):
        entries = [dict(entry_date=y + '-02-01') for y in ie7.YEARS]
        pct = np.array([[.8], [.9], [np.nan], [.7]])
        result = ie7.describe(pct, entries, [[0, 1, 2, -1], [0, 1, 2, 3]], ['numeric'])[0]
        row = result['halves'][ie7.YEARS[0] + 'H1']
        self.assertAlmostEqual(row['median'], .85)
        self.assertEqual((row['missing_nights'], row['outside_nights']), (1, 1))
        self.assertNotEqual(result['status'], 'stable')

    def test_source_contains_no_human_security_or_entry_date_literals(self):
        source = Path(ie7.__file__).read_text()
        constants = {node.value for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        with (ie7.ROOT / 'studies/martin_luk/notes/trades.csv').open() as f:
            records = list(csv.DictReader(f))
        forbidden = {r['ticker'] for r in records} | {'US.' + r['ticker'] for r in records}
        forbidden |= {r['entry_date'] for r in records if r['entry_date']}
        self.assertFalse(constants & forbidden)

    def test_equal_rank_weight_missing_and_direction(self):
        pct = np.array([[1., .2], [.5, .1], [np.nan, .5]])
        scheme = dict(factors=[dict(name='first', direction=1), dict(name='second', direction=-1)], gates=[])
        order, ranks, passed = ie7.rank_night(pct, pct, ['first', 'second'], scheme)
        self.assertEqual(order.tolist(), [0, 1, 2])
        self.assertEqual(ranks.tolist(), [1, 2, 3])
        self.assertTrue(passed.all())
        scheme['gates'] = [dict(name='first', form='pct', lower=.5, upper=None)]
        order, ranks, passed = ie7.rank_night(pct, pct, ['first', 'second'], scheme)
        self.assertEqual(order.tolist(), [0, 1])
        self.assertFalse(passed[2])

    def test_whole_calendar_selection_is_unchanged_by_future_rows(self):
        d = object.__new__(ie7.Data)
        days = ['2030-01-02', '2030-01-03']
        codes = ['SYN_' + str(i) for i in range(6)]
        d.meta = dict(first_signal=days[0], scope={day: codes for day in days})
        d.slices = {day: slice(k * 6, (k + 1) * 6) for k, day in enumerate(days)}
        d.n, d.entries, d.query = 12, [], []
        d.names = ['value']
        d.raw = np.arange(12.)[:, None]
        d.percentiles = lambda: np.concatenate([ie7.night_percentiles(d.raw[sl]) for sl in d.slices.values()])
        scheme = dict(factors=[dict(name='value', direction=1)], gates=[])
        before, widths, _ = d.select(scheme)
        d.raw[6:] *= -100
        after, _, _ = d.select(scheme)
        self.assertEqual(before[days[0]], after[days[0]])
        self.assertNotEqual(before[days[1]], after[days[1]])
        self.assertEqual(widths, {day: 6 for day in days})
        self.assertTrue(all(len(rows) == 5 for rows in before.values()))

    def test_reused_raw_feature_formulas_match_a_truncated_history(self):
        n, cut = 320, 285
        x = np.arange(n, dtype=float)
        close = 20 + x / 30 + np.sin(x / 4)
        arrays = dict(o=close * .99, h=close * 1.03, l=close * .97, c=close,
                      v=1000 + x, t=(1000 + x) * close, raw_c=close)
        extras = dict(earn_days=x % 30, pot=(x % 7 == 0).astype(float))
        for name in ('iv', 'hv', 'option_volume', 'call_volume', 'put_volume', 'option_open_interest',
                     'h4_activity', 'h4_momentum', 'h4_history', 'h4_stack', 'h4_peers', 'h4_coil'):
            extras[name] = 1 + (x % 17)
        days = [str(i) for i in range(n)]
        full = ie7.old.ie4.raw_factors(arrays, days, close, extras)
        short = ie7.old.ie4.raw_factors({k: v[:cut] for k, v in arrays.items()}, days[:cut], close[:cut],
                                      {k: v[:cut] for k, v in extras.items()})
        self.assertEqual(len(full), 64)
        for name in full:
            np.testing.assert_array_equal(full[name][:cut], short[name], err_msg=name)

    def test_year_score_uses_minimum_and_account_return_is_not_a_gate(self):
        def result(hits):
            summary = lambda n: dict(n=10, hits={'5': n})
            return dict(scheme=dict(factors=[{}]), eligible=True, coverage=dict(
                annual={y: dict(primary=summary(n)) for y, n in zip(ie7.YEARS, hits)},
                halfyear={h: summary(5) for h in ie7.HALVES}))
        average_favorite = result((10, 2))
        robust = result((5, 5))
        self.assertIs(ie7.winner([average_favorite, robust]), robust)
        accounts = {label: dict(annual={y: dict(entries=52, win=.35, **{'return': -1.}) for y in ie7.YEARS})
                    for label in ('cash6', 'lever')}
        self.assertTrue(ie7.eligible(accounts)[0])
        accounts['lever']['annual'][ie7.YEARS[0]]['entries'] = 51
        self.assertFalse(ie7.eligible(accounts)[0])

    def test_gates_and_ranks_must_be_attained_on_the_same_night(self):
        e = dict(id='synthetic', code='SYN_A', entry_date='2030-01-10', target=dict(tier='primary'))
        result = ie7.coverage([e], [[0, 1, -1, -1]],
                              np.array([ie7.old.prior.SENTINEL, 8]), np.array([False, True]))
        self.assertEqual(result['primary']['scope'], 1)
        self.assertEqual(result['primary']['gated'], 1)
        self.assertEqual(result['primary']['hits']['5'], 0)
        self.assertEqual(result['primary']['hits']['10'], 1)

    def test_scheme_rejects_unstable_features_and_excess_complexity(self):
        stable = [dict(name='numeric', direction=1)]
        scheme = dict(factors=[dict(name='numeric', direction=1)], gates=[])
        ie7.validate_scheme(scheme, stable)
        scheme['gates'] = [dict(name='unstable', form='pct')]
        with self.assertRaises(ValueError):
            ie7.validate_scheme(scheme, stable)
        scheme['gates'] = []
        scheme['factors'] *= 6
        with self.assertRaises(ValueError):
            ie7.validate_scheme(scheme, stable)


if __name__ == '__main__':
    unittest.main()
