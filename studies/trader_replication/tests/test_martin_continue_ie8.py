import ast
import csv
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

from studies.trader_replication import martin_continue_ie8 as ie8


class IE8Tests(unittest.TestCase):
    def test_small_pool_recomputes_percentiles_and_changes_equal_rank_order(self):
        raw = np.array([[0., 100., 1.], [3., 50., 1.], [2., 0., 1.], [1., 1., 1.],
                        [4., 60., 0.], [5., 70., 0.], [6., 80., 0.], [7., 90., 0.]])
        pct = ie8.ie7.night_percentiles(raw)
        names = ['first', 'second', 'gate']
        scheme = dict(gates=[dict(name='gate', direction=1, cutoff=.5)],
                      factors=[dict(name='first', direction=1), dict(name='second', direction=1)])
        small, _, passed = ie8.rank_night(raw, pct, names, scheme)
        full, _, _ = ie8.rank_night(raw, pct, names, dict(scheme, rank_scope='full'))
        self.assertEqual(small[:2].tolist(), [1, 0])
        self.assertEqual(full[:2].tolist(), [0, 1])
        self.assertFalse(passed[-1])

    def test_gate_intersection_direction_boundaries_and_missing(self):
        pct = np.array([[.8, .2], [.8, .4], [np.nan, .1], [.9, np.nan]])
        gates = [dict(name='first', direction=1, cutoff=.8),
                 dict(name='second', direction=-1, cutoff=.8)]
        self.assertEqual(ie8.gate_mask(pct, ['first', 'second'], gates).tolist(), [True, False, False, False])

    def test_missing_rank_is_neutral_and_empty_pool_is_valid(self):
        raw = np.array([[1., 2.], [2., np.nan], [3., 4.]])
        pct = ie8.ie7.night_percentiles(raw)
        scheme = dict(gates=[], factors=[dict(name='second', direction=1)])
        order, _, _ = ie8.rank_night(raw, pct, ['first', 'second'], scheme)
        self.assertEqual(order.tolist(), [2, 1, 0])
        scheme['gates'] = [dict(name='first', direction=1, cutoff=.9),
                           dict(name='second', direction=-1, cutoff=.9)]
        order, ranks, passed = ie8.rank_night(raw, pct, ['first', 'second'], scheme)
        self.assertEqual(len(order), 0)
        self.assertFalse(passed.any())
        self.assertTrue((ranks == ie8.old.prior.SENTINEL).all())

    def test_future_nights_cannot_change_prior_selected_codes(self):
        d = object.__new__(ie8.Data)
        days = ['2030-01-02', '2030-01-03']
        codes = ['SYN_' + str(i) for i in range(8)]
        d.meta = dict(first_signal=days[0], scope={day: codes for day in days})
        d.slices = {day: slice(k * 8, (k + 1) * 8) for k, day in enumerate(days)}
        d.n, d.entries, d.query, d.names = 16, [], [], ['value']
        d.raw = np.arange(16.)[:, None]
        d.percentiles = lambda: np.concatenate([ie8.ie7.night_percentiles(d.raw[sl]) for sl in d.slices.values()])
        scheme = dict(gates=[dict(name='value', direction=1, cutoff=.5)],
                      factors=[dict(name='value', direction=1)], rank_scope='small')
        before, widths, _ = d.select(scheme)
        d.raw[8:] *= -100
        after, _, _ = d.select(scheme)
        self.assertEqual(before[days[0]], after[days[0]])
        self.assertNotEqual(before[days[1]], after[days[1]])
        self.assertEqual(widths, {day: 4 for day in days})

    def test_retention_preserves_scope_losses_and_requires_one_common_passing_night(self):
        entries = [dict(id=str(k), entry_date=y + '-02-01', target=dict(tier='primary'))
                   for k, y in enumerate((ie8.YEARS[0], ie8.YEARS[1], ie8.YEARS[1]))]
        r = ie8.retention(entries, [[0, 1], [1, 2], [-1, -1]], np.array([True, False, True]),
                          {year + '-02-01': 10 for year in ie8.YEARS})
        self.assertTrue(r['feasible'])
        self.assertEqual(r['annual'][ie8.YEARS[1]]['full_rate'], .5)
        self.assertEqual(r['annual'][ie8.YEARS[1]]['in_scope_rate'], 1.)

    def test_gate_selection_prioritizes_retention_constraint_then_width(self):
        def result(rate, width, count=1):
            return dict(scheme=dict(gates=[{}] * count), retention=dict(
                feasible=rate >= .9, minimum_retention=rate,
                width={y: dict(median=width) for y in (*ie8.YEARS, 'combined')}))
        narrow = result(.89, 5)
        valid = result(.91, 50)
        wider = result(1., 60)
        self.assertIs(max([narrow, valid, wider], key=ie8.gate_key), valid)

    def test_year_minimum_ties_and_account_veto(self):
        def result(hits, factors=2):
            summary = lambda count: dict(n=10, hits={'5': count})
            return dict(eligible=True, scheme=dict(factors=[{}] * factors), coverage=dict(
                annual={y: dict(primary=summary(n)) for y, n in zip(ie8.YEARS, hits)},
                halfyear={h: summary(5) for h in ie8.HALVES}))
        average, robust = result((10, 2)), result((5, 5))
        fewer = result((5, 5), 1)
        self.assertIs(ie8.ranking_winner([average, robust, fewer]), fewer)
        fewer['eligible'] = False
        self.assertIs(ie8.ranking_winner([average, robust, fewer]), robust)
        with self.assertRaises(ValueError):
            ie8.ranking_winner([fewer])
        accounts = {label: dict(annual={y: dict(entries=52, win=.35, **{'return': -1.})
                                        for y in ie8.YEARS}) for label in ('cash6', 'lever')}
        self.assertTrue(ie8.ie7.eligible(accounts)[0])
        accounts['lever']['annual'][ie8.YEARS[0]]['entries'] = 51
        self.assertFalse(ie8.ie7.eligible(accounts)[0])

    def test_validation_rejects_new_direction_threshold_or_excess_gates(self):
        with patch.object(ie8, 'stable_features', return_value=[dict(name='value', direction=1)]):
            scheme = dict(gates=[dict(name='value', direction=1, cutoff=.5)], factors=[])
            ie8.validate(scheme)
            for change in (dict(direction=-1), dict(cutoff=.51), dict(name='unregistered')):
                with self.assertRaises(ValueError):
                    ie8.validate(dict(scheme, gates=[dict(scheme['gates'][0], **change)]))
            with self.assertRaises(ValueError):
                ie8.validate(dict(scheme, gates=scheme['gates'] * 5))

    def test_ablation_restarts_and_respects_account_veto(self):
        class FakeData:
            def evaluate(self, scheme):
                gates = {g['name'] for g in scheme['gates']}
                factors = {f['name'] for f in scheme['factors']}
                return dict(scheme=scheme, eligible='needed_gate' in gates,
                            score=[.5 if 'needed_factor' in factors else .4])

        d = FakeData()
        start = d.evaluate(dict(id='synthetic', gates=[dict(name='extra_gate'), dict(name='needed_gate')],
                                factors=[dict(name='needed_factor'), dict(name='extra_factor')]))
        result = ie8.ablate(d, start)
        self.assertEqual(result['final']['scheme']['gates'], [dict(name='needed_gate')])
        self.assertEqual(result['final']['scheme']['factors'], [dict(name='needed_factor')])
        self.assertEqual(len(result['rounds']), 3)
        self.assertTrue(all(rd['trials'][0]['field'] == 'gates' for rd in result['rounds']))
        self.assertFalse(any(t['accepted'] for t in result['rounds'][-1]['trials']))

    def test_reused_raw_formulas_match_history_truncation(self):
        n, cut = 320, 285
        x = np.arange(n, dtype=float)
        close = 20 + x / 30 + np.sin(x / 4)
        arrays = dict(o=close * .99, h=close * 1.03, l=close * .97, c=close,
                      v=1000 + x, t=(1000 + x) * close, raw_c=close)
        extras = dict(earn_days=x % 30, pot=(x % 7 == 0).astype(float))
        for name in ('iv', 'hv', 'option_volume', 'call_volume', 'put_volume', 'option_open_interest',
                     'h4_activity', 'h4_momentum', 'h4_history', 'h4_stack', 'h4_peers', 'h4_coil'):
            extras[name] = 1 + (x % 17)
        days = list(map(str, range(n)))
        full = ie8.old.ie4.raw_factors(arrays, days, close, extras)
        short = ie8.old.ie4.raw_factors({k: v[:cut] for k, v in arrays.items()}, days[:cut], close[:cut],
                                      {k: v[:cut] for k, v in extras.items()})
        for name in full:
            np.testing.assert_array_equal(full[name][:cut], short[name], err_msg=name)

    def test_source_contains_no_human_security_or_entry_date_literals(self):
        source = Path(ie8.__file__).read_text()
        constants = {node.value for node in ast.walk(ast.parse(source))
                     if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        with (ie8.ROOT / 'studies/martin_luk/notes/trades.csv').open() as stream:
            records = list(csv.DictReader(stream))
        forbidden = {r['ticker'] for r in records} | {'US.' + r['ticker'] for r in records}
        forbidden |= {r['entry_date'] for r in records if r['entry_date']}
        self.assertFalse(constants & forbidden)


if __name__ == '__main__':
    unittest.main()
