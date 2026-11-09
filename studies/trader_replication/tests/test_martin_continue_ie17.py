import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from studies.trader_replication import martin_continue_ie17 as m
from studies.trader_replication.tests import test_martin_continue_ie16 as prior_tests


class IE17Tests(unittest.TestCase):
    def synthetic(self, cut=320, change=None):
        d = prior_tests.IE16Tests().synthetic(cut=cut, change=change)
        d.codes = ['SYNTHETIC_' + str(j) for j in range(len(d.codes))]
        for offset in (1, 2):
            d.extra['peers'][:, :, offset - 1] = (np.arange(len(d.codes)) + offset) % len(d.codes)
        raw = m.security_fields(*(d.px[n] for n in ('close', 'high', 'low')), d.f['e21'], d.f['adr'])
        raw['strength'] = np.array([(m.percentile(a) + m.percentile(b)) / 2
                                   for a, b in zip(raw['g20'], raw['g60'])])
        raw['peer'] = np.array([m.peer_lead(a, b) for a, b in zip(raw['g20'], d.extra['peers'])])
        d.strength = raw
        return d

    def test_average_ties_missing_and_constant_are_neutral(self):
        np.testing.assert_array_equal(m.percentile([1, 1, 2, np.nan]), [.25, .25, 1, .5])
        np.testing.assert_array_equal(m.percentile([4, 4, 4]), [.5] * 3)
        np.testing.assert_array_equal(m.percentile([np.nan, 4]), [.5, .5])
        self.assertEqual(m.percentile([]).size, 0)

    def test_peer_rank_is_within_the_cached_group_including_self(self):
        growth = np.array([.3, .2, .3, np.nan])
        peers = np.array([[1, 2, -1], [0, 2, -1], [0, 1, -1], [-1, -1, -1]])
        np.testing.assert_array_equal(m.peer_lead(growth, peers), [.75, 0, .75, np.nan])
        peers[0] = [0, 0, -1]
        self.assertTrue(np.isnan(m.peer_lead(growth, peers)[0]))

    def test_launch_has_a_plateau_and_penalizes_both_sides(self):
        x = np.array([-.5, .5, 1, 2, 4])
        d = SimpleNamespace(px=dict(close=np.ones((1, 5))), f=dict(money=np.ones((1, 5))),
            strength={n: np.ones((1, 5)) for n in ('strength', 'peer', 'tight', 'high')})
        d.strength['extension'] = x[None, :]
        cfg = dict(m.BASE, priority='continuous', components=['launch'])
        scores = m.strength_scores(0, d, cfg, np.ones(5, bool))
        self.assertEqual(scores[1], scores[2])
        self.assertEqual(scores[2], scores[3])
        self.assertGreater(scores[1], scores[0])
        self.assertGreater(scores[0], scores[4])

    def test_components_are_equal_weight_and_use_all_signal_names(self):
        d = self.synthetic()
        cfg = dict(m.BASE, priority='continuous', components=list(m.COMPONENTS))
        mask = np.array([True, True, False, True, False, True])
        full = m.strength_scores(280, d, cfg, mask)
        singles = [m.strength_scores(280, d, dict(cfg, components=[n]), mask) for n in m.COMPONENTS]
        np.testing.assert_allclose(full, np.mean(singles, axis=0), atol=1e-14)
        # Changing a non-signal cannot change signal-scope percentiles.
        before = full.copy()
        for field in d.strength.values():
            field[280, 2] = 1e6
        d.f['money'][280, 2] = 1e15
        np.testing.assert_array_equal(before, m.strength_scores(280, d, cfg, mask))
        # The full-panel alternative explicitly includes the non-signal.
        panel = m.strength_scores(280, d, dict(cfg, scope='panel'), mask)
        self.assertFalse(np.array_equal(panel, before))

    def test_all_scores_and_orders_are_unchanged_by_future_prices(self):
        cfgs = [m.BASE, dict(m.BASE, priority='continuous', components=list(m.COMPONENTS)),
                dict(m.BASE, priority='continuous', components=['strength', 'launch', 'money'],
                     scope='panel', interval=[0, 1])]
        for cfg in cfgs:
            full_data = self.synthetic()
            full = m.build(full_data, cfg)
            for other in (self.synthetic(cut=280), self.synthetic(change=280)):
                result = m.build(other, cfg)
                for field in ('strength', 'peer', 'extension', 'tight', 'high'):
                    np.testing.assert_array_equal(full_data.strength[field][:280], other.strength[field][:280])
                for name in ('pool', 'market'):
                    np.testing.assert_array_equal(full[name][:280], result[name][:280])
                np.testing.assert_array_equal(full['signals']['long'][:280], result['signals']['long'][:280])
                self.assertEqual(full['book'][:560], result['book'][:560])

    def test_next_day_trigger_subset_does_not_recompute_percentiles(self):
        d = self.synthetic()
        cfg = dict(m.BASE, priority='continuous', components=list(m.COMPONENTS))
        fixed = m.previous.selection_arrays(d, cfg)
        s = 280
        fixed['signals']['long'][s] = True
        fixed['market'][s] = True
        d.px['high'][s + 1] = d.px['high'][s] * 2
        with patch.object(m.previous, 'selection_arrays', return_value=fixed):
            before = m.build(d, cfg)['book'][2 * (s + 1)]
            d.px['high'][s + 1, 0] = d.px['high'][s, 0] - 1
            d.latest = None
            after = m.build(d, cfg)['book'][2 * (s + 1)]
        self.assertEqual(len(before), len(after) + 1)
        self.assertEqual([(e[0], e[1]) for e in before if e[1] != 0], [(e[0], e[1]) for e in after])

    def test_new_scores_cannot_rotate_a_holding_or_change_exit_timing(self):
        # A higher-priority next-day offer must not close the existing holding.
        px = dict(open=np.array([[100., 100.]] * 4), high=np.array([[102., 102.]] * 4),
                  low=np.array([[99., 99.]] * 4), close=np.array([[100., 100.]] * 4),
                  dates=np.busday_offset('2030-01-01', np.arange(4)).astype(str),
                  codes=np.array(['SYNTHETIC_A', 'SYNTHETIC_B']))
        rules = m.old.system.Rules(max_open=1, risk=.005, max_position=.25, max_gross=1,
            trail='', trims=(), buy_cost=0, sell_cost=0, margin_rate=0, intraday_kinds=('long',))
        first = ((-.1, 'SYNTHETIC_A'), 0, 1, 100., 95., 'long', None, None, .25)
        strong = ((-1., 'SYNTHETIC_B'), 1, 1, 100., 95., 'long', None, None, .25)
        _, _, trades = m.old.system.simulate(px, {}, rules, [[first], [strong], [], []],
            str(px['dates'][0]), str(px['dates'][-1]), audit=True)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]['code'], 'SYNTHETIC_A')
        self.assertEqual(trades[0]['exit'], px['dates'][-1])
        self.assertEqual(trades[0]['why'], 'end')

    def test_same_day_stop_precedes_profit_with_strength_order(self):
        d = prior_tests.IE16Tests().order_data()
        d.px.update(dates=np.busday_offset('2030-01-01', np.arange(3)).astype(str), codes=np.array(['SYNTHETIC']))
        d.px['high'][1, 0], d.px['low'][1, 0] = 130, 90
        event = m.previous.order(1, 0, d, m.BASE)
        event = ((-.9, 'SYNTHETIC'), *event[1:])
        rules = m.old.system.Rules(trail='', trims=(3, 5), buy_cost=0, sell_cost=0,
                                  margin_rate=0, intraday_kinds=('long',))
        _, _, trades = m.old.system.simulate(d.px, {}, rules, [[], [event], []],
            str(d.px['dates'][0]), str(d.px['dates'][-1]), audit=True)
        self.assertEqual([e['action'] for e in trades[0]['executions']], ['entry', 'stop_day0'])

    def test_round_budget_and_single_change_after_initial_recipes(self):
        branch, seen = dict(m.BASE), {m.old.key(m.BASE)}
        for number in range(1, 6):
            layer, choices = m.proposals(branch, seen, number)
            self.assertTrue(choices)
            self.assertLessEqual(len(choices), 5)
            for cfg in choices:
                if number > 1:
                    self.assertEqual([k for k in cfg if cfg[k] != branch[k]], [layer])
                    if layer == 'components':
                        self.assertEqual(len(set(cfg[layer]) ^ set(branch[layer])), 1)
                self.assertEqual({k: v for k, v in cfg.items() if k in m.REFERENCE['config'] and k != 'priority'},
                                 {k: v for k, v in m.REFERENCE['config'].items() if k != 'priority'})
                seen.add(m.old.key(cfg))
            branch = choices[0]
        self.assertEqual(m.previous.WORK.name, 'ie16_work')
        self.assertIsNot(m.previous.build, m.build)

    def test_source_contains_no_human_stocks_or_entry_dates(self):
        labels = m.old.ledger.load(m.old.LEDGER)
        forbidden = {r.ticker for r in labels} | {'US.' + r.ticker for r in labels}
        forbidden |= {r.entry_date for r in labels if r.entry_date}
        for path in (Path(m.__file__), Path(__file__), *m.WORK.glob('*.py')):
            literals = {n.value for n in ast.walk(ast.parse(path.read_text()))
                        if isinstance(n, ast.Constant) and isinstance(n.value, str)}
            self.assertFalse(literals & forbidden, path.name)


if __name__ == '__main__':
    unittest.main()
