import ast
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import unittest

import numpy as np

from studies.trader_replication import martin_continue_ie19 as m
from studies.trader_replication.tests import test_martin_continue_ie17 as prior_tests


class IE19Tests(unittest.TestCase):
    def engine(self, daily=1):
        days = np.busday_offset('2030-01-01', np.arange(4)).astype(str)
        a = np.full((8, 5), 100.)
        px = dict(open=a.copy(), high=a + 2, low=a - 1, close=a.copy(), dates=np.repeat(days, 2),
            codes=np.array(['SYNTHETIC_' + str(j) for j in range(5)]),
            session=np.repeat(np.arange(4), 2), daily_close=np.tile([False, True], 4))
        rules = m.old.system.Rules(max_new_long=daily, max_open=11, max_gross=2.8, trail='', trims=(),
            buy_cost=0, sell_cost=0, margin_rate=0, intraday_kinds=('long',))
        return px, rules, [[] for _ in range(8)]

    def event(self, j, rank, stopped=False, kind='long'):
        return ((rank, 'SYNTHETIC_' + str(j)), j, 1, 100., 95., kind, 95. if stopped else None)

    def simulate(self, px, rules, book):
        return m.old.system.simulate(px, {}, rules, book, str(px['dates'][0]), str(px['dates'][-1]), audit=True)[2]

    def test_daily_limit_takes_successful_entries_in_queue_order(self):
        for daily in (1, 2, 3, 4):
            px, rules, book = self.engine(daily)
            book[0] = [self.event(j, 4 - j) for j in range(5)]
            trades = self.simulate(px, rules, book)
            self.assertEqual({tr['code'] for tr in trades}, {'SYNTHETIC_' + str(4 - j) for j in range(daily)})

    def test_rejected_same_name_does_not_consume_another_entry(self):
        px, rules, book = self.engine(2)
        book[0] = [self.event(0, 0), self.event(0, 1), self.event(1, 2), self.event(2, 3)]
        self.assertEqual({tr['code'] for tr in self.simulate(px, rules, book)}, {'SYNTHETIC_0', 'SYNTHETIC_1'})

    def test_same_day_stop_keeps_the_entry_count_and_next_day_resets(self):
        px, rules, book = self.engine()
        px['low'][0, 0] = 94
        book[0] = [self.event(0, 0, stopped=True)]
        book[1] = [self.event(1, 0, kind='close')]
        book[2] = [self.event(2, 0)]
        trades = self.simulate(px, rules, book)
        self.assertEqual({tr['code'] for tr in trades}, {'SYNTHETIC_0', 'SYNTHETIC_2'})
        self.assertEqual(next(tr for tr in trades if tr['code'] == 'SYNTHETIC_0')['why'], 'stop_day0')

    def test_intraday_and_close_share_one_trading_session_limit(self):
        px, rules, book = self.engine()
        book[0] = [self.event(0, 0)]
        book[1] = [self.event(1, 0, kind='close')]
        self.assertEqual([tr['code'] for tr in self.simulate(px, rules, book)], ['SYNTHETIC_0'])

    def test_adds_do_not_consume_new_entry_allowance(self):
        px, rules, book = self.engine()
        rules = replace(rules, add_r=1, add_frac=.5)
        book[0] = [self.event(0, 0)]
        px['close'][2:, 0], px['open'][2:, 0], px['high'][2:, 0], px['low'][2:, 0] = 106, 106, 107, 105
        book[2] = [self.event(1, 0)]
        trades = self.simulate(px, rules, book)
        self.assertEqual({tr['code'] for tr in trades}, {'SYNTHETIC_0', 'SYNTHETIC_1'})
        self.assertIn('add', [e['action'] for tr in trades if tr['code'] == 'SYNTHETIC_0' for e in tr['executions']])

    def scores_data(self):
        return SimpleNamespace(strength=dict(extension=np.array([[-1., 0., 1., 2., 3., 4.]])),
            f=dict(money=np.array([[8., 1., 3., 2., 5., 9.]])),
            wave={n: np.array([[0., 1., 5., 3., 2., 4.]]) for n in ('count', 'higher', 'peer_money', 'peer_return')})

    def test_flat_is_exactly_ie17_and_triangle_prefers_one_adr(self):
        d = self.scores_data()
        signals = np.ones(6, bool)
        indices, primary, _ = m.queue_scores(0, d, m.BASE, signals)
        expected = m.previous.scores(0, d, m.previous.BASE, signals)
        np.testing.assert_array_equal(primary, expected[indices])
        d.f['money'][:] = 1
        _, flat, _ = m.queue_scores(0, d, m.BASE, signals)
        _, triangle, _ = m.queue_scores(0, d, dict(m.BASE, shape='triangle'), signals)
        self.assertEqual(flat[1], flat[2])
        self.assertEqual(flat[2], flat[3])
        self.assertGreater(triangle[2], triangle[1])
        self.assertEqual(triangle[1], triangle[3])

    def test_lexicographic_secondary_never_overrides_a_higher_primary_band(self):
        primary = np.array([.51, .59, .60, .599, .59])
        secondary = np.array([1., 0., 0., 1., 0.])
        keys = m.queue_keys(primary, secondary, list('EDCBA'), 'lex')
        order = sorted(range(5), key=lambda j: keys[j])
        self.assertEqual(order, [2, 3, 0, 4, 1])

    def test_multiplicative_secondary_has_the_registered_bounds(self):
        primary = np.array([.8, .6, .4])
        secondary = np.array([0., .5, 1.])
        keys = m.queue_keys(primary, secondary, list('ABC'), 'multiply')
        np.testing.assert_allclose([-v[0] for v in keys], [.4, .45, .4])

    def test_nonsignals_never_change_score_denominators(self):
        d = self.scores_data()
        signals = np.array([True, False, True, True, False, True])
        cfg = dict(m.BASE, shape='triangle', combine='multiply', secondary='stage')
        before = m.queue_scores(0, d, cfg, signals)
        for a in (d.strength['extension'], d.f['money'], *d.wave.values()):
            a[:, ~signals] = 1e12
        for a, b in zip(before, m.queue_scores(0, d, cfg, signals)):
            np.testing.assert_array_equal(a, b)

    def synthetic(self, cut=320, change=None):
        d = prior_tests.IE17Tests().synthetic(cut, change)
        d.template = None
        d.wave = m.previous.wave_fields(*(d.px[n] for n in ('close', 'high', 'low')),
                                       *(d.f[n] for n in ('e9', 'e21', 'adr')))
        d.wave.update(m.previous.flow_fields(d.px['close'], d.f['money'], d.f['adr']))
        for field, raw in (('peer_money', 'own_money'), ('peer_return', 'acceleration')):
            d.wave[field] = np.array([m.previous.peer_mean(d.wave[raw][s], d.extra['peers'][s]) for s in range(cut)])
        return d

    def test_all_queue_shapes_and_orders_ignore_future_data(self):
        cfgs = [*m.proposals(2, None, []), *m.proposals(3, None, [])]
        for cfg in cfgs:
            full = m.build(self.synthetic(), cfg)
            for d in (self.synthetic(cut=280), self.synthetic(change=280)):
                prefix = m.build(d, cfg)
                self.assertEqual(full['book'][:560], prefix['book'][:560])
                np.testing.assert_array_equal(full['signals']['long'][:279], prefix['signals']['long'][:279])

    def test_round_budget_and_only_effective_pace_shape_combinations(self):
        for number in range(1, 6):
            self.assertLessEqual(len(m.proposals(number, None, [])), 5)
        self.assertEqual(m.proposals(4, None, []), [])
        shapes = [dict(config=cfg, metrics=dict(weighted_coverage=.6 + k / 100, bought=40))
                  for k, cfg in enumerate(m.proposals(2, None, [])[:4] + m.proposals(3, None, []))]
        pace = dict(config=dict(m.BASE, daily=2))
        choices = m.proposals(4, pace, shapes) + m.proposals(5, pace, shapes)
        self.assertEqual(len(choices), 9)
        self.assertEqual(len({m.old.key(cfg) for cfg in choices}), 9)
        self.assertTrue(all(cfg['daily'] == 2 for cfg in choices))

    def test_import_does_not_patch_previous_research(self):
        self.assertEqual(m.previous.WORK.name, 'ie18_work')
        self.assertIsNot(m.shared, m.previous)
        self.assertIs(m.previous.shared.build, m.previous.build)

    def test_source_has_no_human_security_or_entry_date_literals(self):
        labels = m.old.ledger.load(m.old.LEDGER)
        forbidden = {r.ticker for r in labels} | {'US.' + r.ticker for r in labels}
        forbidden |= {r.entry_date for r in labels if r.entry_date}
        for path in (Path(m.__file__), Path(__file__), *m.WORK.glob('*.py')):
            literals = {n.value for n in ast.walk(ast.parse(path.read_text()))
                        if isinstance(n, ast.Constant) and isinstance(n.value, str)}
            self.assertFalse(literals & forbidden, path.name)


if __name__ == '__main__':
    unittest.main()
