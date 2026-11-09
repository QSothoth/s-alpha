import ast
import csv
from pathlib import Path
import unittest

import numpy as np

from studies.trader_replication import martin_continue_ie9 as m


def arrays(n=340):
    x = np.arange(n, dtype=float)
    c = 30 + x / 25 + 2 * np.sin(x / 6)
    return dict(c=c, h=c * (1.02 + .005 * np.sin(x / 3)),
                l=c * (.98 - .005 * np.sin(x / 3)), v=1000 + 200 * np.cos(x / 5))


def result(hits=(2, 2, 2, 3), factors=('first', 'second'), eligible=True):
    halves = {h: dict(n=n, hits={'5': k}) for h, n, k in zip(m.HALVES, (5, 6, 4, 13), hits)}
    r = dict(scheme=dict(id='synthetic', gates=m.GATES, rank_scope='small', factors=list(factors)),
             coverage=dict(halfyear=halves), eligible=eligible, failures=[])
    r['score'] = list(m.score_key(r))
    return r


class IE9Tests(unittest.TestCase):
    def test_all_new_trigger_prefixes_are_causal_including_missing_data(self):
        data = arrays()
        data['c'][120:122] = np.nan
        data['h'][120:122] = np.nan
        data['v'][175] = np.nan
        full = m.trigger_values(data)
        self.assertEqual(set(full), set(m.TRIGGERS) - set(m.CACHED))
        for cut in (80, 185, 285):
            short = m.trigger_values({k: v[:cut] for k, v in data.items()})
            for name in full:
                np.testing.assert_array_equal(full[name][:cut], short[name], err_msg=name)
        changed = {k: v.copy() for k, v in data.items()}
        for v in changed.values():
            v[285:] *= 20
        after = m.trigger_values(changed)
        for name in full:
            np.testing.assert_array_equal(full[name][:285], after[name][:285], err_msg=name)

    def test_reclaims_and_touches_use_current_close_and_previous_ema(self):
        data = dict(c=np.array([100., 90., 110., 108.]), h=np.array([102., 92., 112., 111.]),
                    l=np.array([99., 89., 98., 106.]), v=np.ones(4))
        values = m.trigger_values(data)
        for n in (9, 21):
            self.assertEqual(values['reclaim' + str(n)][2], 1.)
            self.assertEqual(values['touch' + str(n)][2], 1.)
            self.assertEqual(values['reclaim' + str(n)][3], 0.)
            self.assertTrue(np.isnan(values['reclaim' + str(n)][0]))

    def test_first_touch_requires_complete_prior_window(self):
        c = np.arange(40.) + 100
        data = dict(c=c, h=c + 1, l=c - .01, v=np.ones(40))
        ema9 = m.lib.smooth(c, 9)
        data['l'][-1] = ema9[-1] - 1
        values = m.trigger_values(data)
        self.assertEqual(values['first_touch9'][-1], 1.)
        self.assertTrue(np.isnan(values['first_touch21'][5]))
        data['l'][-3] = ema9[-3] - 1
        self.assertEqual(m.trigger_values(data)['first_touch9'][-1], 0.)

    def test_narrow_inside_and_next_day_breakout_have_correct_clock(self):
        c = np.full(12, 100.)
        h = np.array([110., 109., 108., 107., 106., 105., 104., 103., 102., 101., 104., 108.])
        l = 200 - h
        c[10] = 103.
        values = m.trigger_values(dict(c=c, h=h, l=l, v=np.ones(12)))
        self.assertEqual(values['nr7'][9], 1.)
        self.assertEqual(values['inside'][9], 1.)
        self.assertEqual(values['after_nr7'][10], 1.)
        self.assertEqual(values['nr7_breakout'][10], 1.)
        self.assertEqual(values['inside_breakout'][10], 1.)
        self.assertTrue(np.isnan(values['nr7'][5]))

    def test_volume_rebound_excludes_current_volume_from_denominator(self):
        data = arrays(30)
        data['v'][:] = 100
        data['v'][-4:-1] = 20
        data['v'][-1] = 60
        data['c'][-1] = data['c'][-2] * 1.01
        self.assertEqual(m.trigger_values(data)['volume_rebound'][-1], 3.)
        self.assertEqual(m.trigger_values(data)['dry_volume_rebound'][-1], 1.)

    def test_pullback_uses_latest_tied_high_and_trading_day_age(self):
        data = arrays(30)
        data['h'][:] = 100
        data['h'][-4] = 120
        self.assertEqual(m.trigger_values(data)['pullback_2_10'][-1], 1.)
        data['h'][-1] = 120
        self.assertEqual(m.trigger_values(data)['pullback_2_10'][-1], 0.)

    def test_missing_inputs_remain_missing_instead_of_false_events(self):
        data = arrays(35)
        data['h'][-2] = np.nan
        data['v'][-1] = np.nan
        values = m.trigger_values(data)
        for name in ('nr4', 'nr7', 'inside', 'break_high_close', 'pullback_2_10',
                     'close_break_strength', 'volume_rebound', 'dry_volume_rebound'):
            self.assertTrue(np.isnan(values[name][-1]), name)

    def test_small_pool_rank_preserves_event_strength_and_neutral_missing(self):
        values = np.array([[1., 0.], [0., 1.], [1., np.nan], [1., 1.]])
        order, ranks = m.rank_night(values, np.array([True, True, True, False]), ['event', 'continuous'],
                                     ['event', 'continuous'])
        self.assertEqual(order.tolist(), [2, 0, 1])
        self.assertEqual(ranks[3], m.old.prior.SENTINEL)
        empty, ranks = m.rank_night(values, np.zeros(4, bool), ['event', 'continuous'], [])
        self.assertEqual(len(empty), 0)
        self.assertTrue((ranks == m.old.prior.SENTINEL).all())

    def test_random_expectation_is_best_passing_night_and_union_is_distinct(self):
        entries = [dict(id='synthetic', entry_date=m.YEARS[0] + '-03-01', target=dict(tier='primary')),
                   dict(id='outside', entry_date=m.YEARS[0] + '-03-01', target=dict(tier='primary'))]
        expected = m.random_expectation(entries, [[0, 1, 2, 3], [-1] * 4],
            np.array([True, True, False, True]), np.array([10, 20, 0, 20]))
        self.assertEqual(expected['primary']['best_night'], .5)
        self.assertAlmostEqual(expected['primary']['union'], 1 - .5 * .75 * .75)
        self.assertEqual(expected['rows'][1]['best_night'], 0.)
        self.assertEqual(expected['rows'][1]['union'], 0.)

    def test_selection_uses_worst_half_and_fewer_factors(self):
        uneven = result((5, 6, 4, 1))
        robust = result((2, 2, 2, 3))
        fewer = result((2, 2, 2, 3), ('first',))
        self.assertIs(m.winner([uneven, robust, fewer]), fewer)
        fewer['eligible'] = False
        self.assertIs(m.winner([uneven, robust, fewer]), robust)
        self.assertIs(m.winner([fewer]), fewer)

    def test_qualification_requires_strictly_above_random_each_half_and_account_veto(self):
        coverage = result()['coverage']
        expected = dict(halfyear={h: dict(best_night=1.) for h in m.HALVES})
        accounts = {label: dict(annual={y: dict(entries=52, win=.35) for y in m.YEARS})
                    for label in ('cash6', 'lever')}
        self.assertTrue(m.qualify(coverage, expected, accounts)[0])
        expected['halfyear'][m.HALVES[0]]['best_night'] = 2.
        self.assertFalse(m.qualify(coverage, expected, accounts)[0])
        expected['halfyear'][m.HALVES[0]]['best_night'] = 1.
        accounts['lever']['annual'][m.YEARS[1]]['entries'] = 51
        self.assertFalse(m.qualify(coverage, expected, accounts)[0])

    def test_validation_requires_fixed_gates_and_a_stable_trigger(self):
        scheme = dict(gates=m.GATES, rank_scope='small', factors=['nr4', 'offlow252'])
        m.validate(scheme, ['nr4'])
        for change in (dict(gates=m.GATES[:-1]), dict(rank_scope='full'),
                       dict(factors=['offlow252']), dict(factors=['nr7']), dict(factors=['nr4'] * 5)):
            with self.assertRaises(ValueError):
                m.validate(dict(scheme, **change), ['nr4'])
        self.assertEqual(len(m.NAMES), 30)

    def test_ablation_only_drops_rank_factors_and_restarts(self):
        class Fake:
            def evaluate(self, scheme):
                r = result(factors=scheme['factors'])
                r['scheme'] = scheme
                r['score'][0] = .4 if 'needed' in scheme['factors'] else .2
                return r
        d = Fake()
        initial = d.evaluate(dict(id='synthetic', gates=m.GATES, factors=['extra', 'needed'], rank_scope='small'))
        after = m.ablate(d, initial)
        self.assertEqual(after['final']['scheme']['factors'], ['needed'])
        self.assertEqual(after['final']['scheme']['gates'], m.GATES)
        self.assertEqual(len(after['rounds']), 2)

    def test_source_has_no_human_security_or_entry_date_literals(self):
        source = Path(m.__file__).read_text()
        constants = {node.value for node in ast.walk(ast.parse(source))
                     if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        with (m.ROOT / 'studies/martin_luk/notes/trades.csv').open() as stream:
            records = list(csv.DictReader(stream))
        forbidden = {r['ticker'] for r in records} | {'US.' + r['ticker'] for r in records}
        forbidden |= {r['entry_date'] for r in records if r['entry_date']}
        self.assertFalse(constants & forbidden)


if __name__ == '__main__':
    unittest.main()
