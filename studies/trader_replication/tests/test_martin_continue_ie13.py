import ast
import csv
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from studies.trader_replication import martin_continue_ie13 as m


class IE13Tests(unittest.TestCase):
    def test_process_inputs_are_prefix_causal_including_options_and_earnings(self):
        t = np.arange(260)
        c = 30 + t / 60 + np.sin(t / 7)
        arrays = dict(c=c, o=c * 1.001, h=c * 1.03, l=c * .97, v=1000. + t)
        arrays['o'][160] = c[159] * 1.07
        arrays['v'][160] *= 4
        arrays['c'][160] *= 1.1
        arrays['h'][160] = arrays['c'][160] * 1.03
        extras = dict(iv=.4 + t / 10000, call_volume=100. + t,
            put_volume=60. + t, option_volume=160. + 2 * t,
            option_open_interest=1000. + t, earn_days=t % 60)
        full = m.process_values(arrays, extras)
        for cut in (100, 161, 220):
            short = m.process_values({k: a[:cut] for k, a in arrays.items()},
                                     {k: a[:cut] for k, a in extras.items()})
            changed = {k: a.copy() for k, a in arrays.items()}
            extra_changed = {k: a.copy() for k, a in extras.items()}
            for a in changed.values():
                a[cut:] *= 50
            for a in extra_changed.values():
                a[cut:] += 1000
            future = m.process_values(changed, extra_changed)
            for name in full:
                np.testing.assert_array_equal(full[name][:cut], short[name], err_msg=name)
                np.testing.assert_array_equal(full[name][:cut], future[name][:cut], err_msg=name)
        self.assertEqual(full['ep_hold'][160], 0.)
        extras['earn_days'][160] = 0
        self.assertEqual(m.process_values(arrays, extras)['ep_hold'][160], 1.)

    def test_plate_prices_are_causal_but_current_membership_is_ineligible(self):
        t, j = np.arange(100)[:, None], np.arange(1, 9)[None, :]
        c = 20 + t * j / 400 + np.sin(t / (3 + j))
        pot = c > 22
        history = c > 23
        groups = [list(range(6)), list(range(2, 8))]
        full = m.ie11.member_factors(c, pot, history, groups)
        cut = 80
        short = m.ie11.member_factors(c[:cut], pot[:cut], history[:cut], groups)
        changed = c.copy()
        changed[cut:] *= 100
        future = m.ie11.member_factors(changed, pot, history, groups)
        for name in full:
            np.testing.assert_array_equal(full[name][:cut], short[name], err_msg=name)
            np.testing.assert_array_equal(full[name][:cut], future[name][:cut], err_msg=name)
        self.assertFalse(next(f for f in m.FAMILIES if f['id'] == 'plates')['eligible'])

    def synthetic_data(self):
        days = ['2030-02-04', '2030-08-05', '2031-02-03']
        entries = [dict(id='synthetic_' + str(i), entry_date=day,
            target=dict(tier='primary'), systems=dict(h4=[dict(date=day)])) for i, day in enumerate(days)]
        return SimpleNamespace(entries=entries, query=[[6], [14], [22]], names=['h4_history', 'near_ema9'],
            slices={day: slice(8 * i, 8 * i + 8) for i, day in enumerate(days)},
            x=np.array([[j / 8, ((j + 3) % 8) / 8] for _ in days for j in range(8)]))

    def test_entire_fit_excludes_heldout_values_queries_and_labels(self):
        d = self.synthetic_data()
        half = m.ie7.half(d.entries[-1]['entry_date'])
        reg = dict(weights=[.5, 1., 2.], coordinate_passes=2)
        before = m.fit_model(d, ['history', 'near9'], half, reg)
        bundle = m.training_bundle(d, half)
        self.assertEqual(len(bundle['rows']), 16)
        d.x[16:] = np.nan
        d.entries[-1]['target']['tier'] = 'secondary'
        d.query[-1] = [-1]
        after = m.fit_model(d, ['history', 'near9'], half, reg)
        self.assertEqual(before, after)
        self.assertTrue(set(before['weights']) <= {.5, 1., 2.})
        self.assertNotIn(d.entries[-1]['id'], before['training_ids'])

    def test_training_purges_shared_signal_nights_at_period_boundary(self):
        d = self.synthetic_data()
        half = m.ie7.half(d.entries[1]['entry_date'])
        d.entries[1]['systems']['h4'].append(d.entries[0]['systems']['h4'][0])
        bundle = m.training_bundle(d, half)
        self.assertIn(d.entries[0]['id'], bundle['purged'])
        self.assertNotIn(d.entries[0]['id'], bundle['ids'])

    def test_bag_ranks_use_four_night_union_and_stable_security_ties(self):
        bundle = dict(bags=[[(np.arange(8), 6), (np.arange(8, 16), 14)], []])
        scores = np.zeros((16, 2))
        scores[14, 0] = 1
        scores[6, 1] = 1
        result = m.ranks_for_scores(bundle, scores)
        np.testing.assert_array_equal(result[0], [1, 1])
        self.assertTrue((result[1] > 5).all())
        scores[:] = 0
        self.assertEqual(m.ranks_for_scores(bundle, scores)[0, 0], 7)

    def test_shuffle_is_shared_within_night_and_preserves_absence(self):
        slices = dict(a=slice(0, 8), b=slice(8, 16))
        query = [[0, 9, -1], [0, 9, -1], [1, 10, -1]]
        result = m.shuffled_queries(query, slices, 16, m.SEEDS[0])
        self.assertEqual(result[0], result[1])
        self.assertNotEqual(result[0][0], result[2][0])
        self.assertNotEqual(result[0][1], result[2][1])
        self.assertTrue(all(q[-1] == -1 for q in result))
        self.assertEqual(result, m.shuffled_queries(query, slices, 16, m.SEEDS[0]))

    def test_random_expectation_is_union_not_best_single_night(self):
        day = '2030-02-04'
        d = SimpleNamespace(x=np.zeros((40, 1)),
            slices={str(i): slice(10 * i, 10 * i + 10) for i in range(4)},
            entries=[dict(id='synthetic_a', entry_date=day, target=dict(tier='primary'))],
            query=[[0, 10, 20, 30]], halves=[m.ie7.half(day)])
        self.assertAlmostEqual(m.random_expectation(d)['primary']['union'], 1 - .5**4)
        d.query[0][1:] = [-1, -1, -1]
        self.assertAlmostEqual(m.random_expectation(d)['primary']['union'], .5)

    def test_prediction_reads_only_supplied_evening_and_missing_never_adds(self):
        names = ['h4_history', 'volume_rebound', 'state_pullback']
        x = np.array([[.8, .2, 1.], [.5, .4, 0.], [np.nan, np.nan, 1.]])
        terms = ['history', 'pullback_quiet']
        before = m.basis(x, names, terms)
        np.testing.assert_allclose(before, [[.8, .8], [.5, 0.], [0., 0.]])
        changed = x.copy()
        changed[1:] = 100
        np.testing.assert_array_equal(before[:1], m.basis(changed, names, terms)[:1])

    def test_unknown_codes_are_parsed_from_response_and_not_hardcoded(self):
        codes = ['US.SYNTHETIC_A', 'US.SYNTHETIC_B']
        self.assertEqual(m.unknown_code('未知股票 SYNTHETIC_B', codes), codes[1])
        self.assertIsNone(m.unknown_code('permission denied', codes))

    def test_source_excerpts_accept_bracketed_fractional_timestamps(self):
        source = 'synthetic_video@00:01:00'
        path = m.ROOT / 'synthetic_video.transcript.txt'
        with patch.object(Path, 'glob', side_effect=[[], [path]]), patch.object(Path, 'read_text',
            return_value='[00:01:00.123 --> 00:01:30.456]\nconfirmed timing\n'):
            result = m.source_excerpt(source)
        self.assertEqual(result[0]['lines'], [dict(seconds=60.123, text='confirmed timing')])

    def test_family_size_and_fixed_directions(self):
        self.assertEqual(len(m.FAMILIES), 5)
        for family in m.FAMILIES:
            self.assertLessEqual(len(family['terms']), 6)
            self.assertEqual(len(set(family['terms'])), len(family['terms']))
            for name in family['terms']:
                self.assertIn(m.TERMS[name]['direction'], (-1, 1))
        self.assertGreaterEqual(len(set(m.SEEDS)), 5)

    def test_new_source_and_tests_have_no_human_codes_or_entry_dates(self):
        with m.LEDGER.open() as stream:
            records = list(csv.DictReader(stream))
        forbidden = {r['ticker'] for r in records} | {'US.' + r['ticker'] for r in records}
        forbidden |= {r['entry_date'] for r in records if r['entry_date']}
        sources = [Path(m.__file__), Path(__file__), *m.WORK.glob('*.py')]
        tickers = {r['ticker'] for r in records}
        dates = {r['entry_date'] for r in records if r['entry_date']}
        for path in sources:
            text = path.read_text()
            tree = ast.parse(text)
            constants = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
            self.assertFalse(constants & forbidden)
            self.assertFalse(any(day in text for day in dates), path.name)
            self.assertFalse(any(re.search(r'(?<![A-Za-z0-9_])' + re.escape(ticker) + r'(?![A-Za-z0-9_])', text)
                                 for ticker in tickers), path.name)
            self.assertNotIn('\u95e8\u7981', path.read_text())


if __name__ == '__main__':
    unittest.main()
