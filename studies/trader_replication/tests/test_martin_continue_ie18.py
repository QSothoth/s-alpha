import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

import numpy as np

from studies.trader_replication import martin_continue_ie18 as m
from studies.trader_replication.tests import test_martin_continue_ie17 as prior_tests


class IE18Tests(unittest.TestCase):
    def wave(self):
        c = np.full((110, 1), 10.)
        h, l = c + .2, c - .2
        h[:40], l[:40] = 12, 8
        c[70:], h[70:], l[70:] = 11.2, 11.4, 11.
        c[70], h[70], l[70] = 11, 11.2, 10.8
        l[72:74], c[72:74] = [[10.4], [10.3]], 10.8
        l[75:77] = [[10.5], [10.4]]
        l[78] = 10.5
        return [c, h, l, np.full_like(c, 10.5), np.full_like(c, 10.), np.full_like(c, 5.)]

    def test_wave_retains_its_origin_and_counts_separate_pullbacks(self):
        fields = m.wave_fields(*self.wave())
        self.assertEqual(fields['origin'][70, 0], 70)
        self.assertTrue((fields['origin'][70:80, 0] == 70).all())
        self.assertEqual(fields['count'][72, 0], 0)
        self.assertEqual(fields['count'][73, 0], 0)
        self.assertEqual(fields['count'][75, 0], -1)
        self.assertEqual(fields['count'][76, 0], -1)
        self.assertEqual(fields['count'][78, 0], -2)
        self.assertTrue(np.isnan(fields['higher'][72, 0]))
        self.assertGreater(fields['higher'][75, 0], 0)
        self.assertEqual(fields['age'][78, 0], -8)
        self.assertLess(fields['advance'][71, 0], 0)

    def test_wave_ends_after_a_known_base_failure(self):
        args = self.wave()
        args[0][80], args[2][80] = 9, 8.8
        result = m.wave_fields(*args)
        self.assertTrue(np.isnan(result['origin'][80, 0]))

    def test_wave_prefixes_ignore_future_prices_and_ema_values(self):
        args = self.wave()
        full = m.wave_fields(*args)
        for cut in (70, 74, 79, 95):
            prefix = m.wave_fields(*(a[:cut] for a in args))
            changed = [a.copy() for a in args]
            for a in changed:
                a[cut:] *= 50
            future = m.wave_fields(*changed)
            for key in full:
                np.testing.assert_array_equal(full[key][:cut], prefix[key])
                np.testing.assert_array_equal(full[key][:cut], future[key][:cut])

    def flow(self):
        x = np.arange(100.)[:, None]
        c = 30 + x * .1 + np.sin(x / 5)
        turnover = np.full_like(c, 100.)
        turnover[40:60] = 200
        return c, turnover, np.full_like(c, 5.)

    def test_flow_windows_do_not_overlap(self):
        c, turnover, adr = self.flow()
        fields = m.flow_fields(c, turnover, adr)
        self.assertAlmostEqual(fields['own_money'][44, 0], np.log(2))
        self.assertEqual(fields['flow_age'][44, 0], 4)
        turnover[20:40] = 50
        self.assertAlmostEqual(m.flow_fields(c, turnover, adr)['own_money'][44, 0], np.log(4))
        expected = (np.log(c[44, 0] / c[39, 0]) / 5 - np.log(c[39, 0] / c[19, 0]) / 20) / .05
        self.assertAlmostEqual(fields['acceleration'][44, 0], expected)

    def test_flow_and_lead_ignore_future_activity(self):
        args = self.flow()
        full = m.flow_fields(*args)
        for cut in (40, 45, 63):
            prefix = m.flow_fields(*(a[:cut] for a in args))
            changed = [a.copy() for a in args]
            for a in changed:
                a[cut:] *= 100
            future = m.flow_fields(*changed)
            for name in full:
                np.testing.assert_array_equal(full[name][:cut], prefix[name])
                np.testing.assert_array_equal(full[name][:cut], future[name][:cut])

    def test_peer_flows_exclude_self_and_missing_neighbors(self):
        values = np.array([100., 3, 5, np.nan])
        peers = np.array([[0, 1, 2], [-1, 2, 3], [2, -1, -1], [-1, -1, -1]])
        np.testing.assert_array_equal(m.peer_mean(values, peers), [4, 5, np.nan, np.nan])
        before = m.peer_mean(values, peers)[0]
        values[0] = -1000
        self.assertEqual(m.peer_mean(values, peers)[0], before)
        lead = m.previous.peer_lead(np.array([3., 1, 2, np.nan]), peers)
        self.assertEqual(lead[0], 1)

    def test_reference_ranks_keep_signal_denominator_and_ties(self):
        values = np.array([1., 1, 3, 2, np.nan])
        indices = np.array([0, 1, 2])
        ranks = m.rank_against(values, indices)
        np.testing.assert_array_equal(ranks[indices], m.previous.percentile(values[indices]))
        self.assertEqual(ranks[4], .5)
        values[3] = 1e8
        np.testing.assert_array_equal(ranks[indices], m.rank_against(values, indices)[indices])
        np.testing.assert_array_equal(m.rank_against(values, [0]), [.5] * 5)

    def test_new_groups_are_equal_weight_and_baseline_is_exact(self):
        n = 6
        d = SimpleNamespace(strength=dict(extension=np.array([[-1., 0, 1, 2, 3, 4]])),
            f=dict(money=np.array([[9., 1, 3, 2, 5, 8]])),
            wave={name: (np.arange(n)[None, :] * (-1 if k % 2 else 1)).astype(float)
                  for k, name in enumerate(m.FIELDS)})
        d.strength.update({name: np.zeros((1, n)) for name in ('strength', 'peer', 'tight', 'high')})
        signals = np.array([True, False, True, True, True, False])
        base = m.scores(0, d, m.BASE, signals)
        expected = m.previous.strength_scores(0, SimpleNamespace(**vars(d), px=dict(close=np.ones((1, n)))),
                                               m.BASE, signals)
        np.testing.assert_array_equal(base[signals], expected)
        phase = m.scores(0, d, dict(m.BASE, stage='full'), signals)
        flow = m.scores(0, d, dict(m.BASE, flow='full'), signals)
        both = m.scores(0, d, dict(m.BASE, stage='full', flow='full'), signals)
        np.testing.assert_allclose(both, (2 * phase + 2 * flow - base) / 3)
        changed = {k: v.copy() for k, v in d.wave.items()}
        for a in changed.values():
            a[:, ~signals] = 1e9
        d.wave = changed
        np.testing.assert_array_equal(both[signals], m.scores(0, d, dict(m.BASE, stage='full', flow='full'), signals)[signals])

    def test_full_orders_keep_the_same_prefix_when_future_data_changes(self):
        def data(cut=320, change=None):
            d = prior_tests.IE17Tests().synthetic(cut, change)
            d.template = None
            d.wave = m.wave_fields(*(d.px[n] for n in ('close', 'high', 'low')),
                                   *(d.f[n] for n in ('e9', 'e21', 'adr')))
            d.wave.update(m.flow_fields(d.px['close'], d.f['money'], d.f['adr']))
            d.wave.update({name: np.array([m.peer_mean(d.wave[raw][s], d.extra['peers'][s])
                for s in range(cut)]) for name, raw in (('peer_money', 'own_money'), ('peer_return', 'acceleration'))})
            d.wave['lead'] = np.array([m.previous.peer_lead(d.wave['flow_age'][s], d.extra['peers'][s])
                                       for s in range(cut)])
            return d
        cfg = dict(m.BASE, stage='full', flow='full')
        full = m.build(data(), cfg)
        for other in (data(cut=280), data(change=280)):
            result = m.build(other, cfg)
            np.testing.assert_array_equal(full['scores'][:279], result['scores'][:279])
            self.assertEqual(full['book'][:560], result['book'][:560])

    def rotation(self):
        days = np.busday_offset('2030-01-01', np.arange(7)).astype(str)
        d = SimpleNamespace(days=days, codes=['SYNTHETIC_A', 'SYNTHETIC_B'],
            px=dict(high=np.full((7, 2), 100.2), close=np.full((7, 2), 100.)))
        positions = {0: SimpleNamespace(j=0, side=1, d0=0, fill=100., stop0=95.)}
        signals = np.tile([False, True], (7, 1))
        ranks = np.tile([.1, .9], (7, 1))
        return d, positions, signals, ranks

    def test_rotation_reads_only_prior_completed_prices_and_current_open(self):
        d, held, signals, ranks = self.rotation()
        cfg = dict(m.BASE, rotation='gap25')
        before = m.rotation_choice(3, d, cfg, signals, ranks, held, np.array([101., 102.]), 1., 2.8)
        self.assertEqual(before['sold'], 0)
        self.assertEqual(before['target'], 1)
        d.px['high'][4:], d.px['close'][4:] = 10000, 1
        signals[4:], ranks[4:] = False, 0
        self.assertEqual(before, m.rotation_choice(3, d, cfg, signals, ranks, held, np.array([101., 102.]), 1., 2.8))
        self.assertIsNone(m.rotation_choice(3, d, cfg, signals, ranks, held, np.array([101., 102.]), 1., 0.))

    def test_rotation_protects_ever_proven_positions_and_same_day_entries(self):
        d, held, signals, ranks = self.rotation()
        cfg = dict(m.BASE, rotation='gap25')
        d.px['high'][1, 0] = 105
        self.assertIsNone(m.rotation_choice(3, d, cfg, signals, ranks, held, np.ones(2) * 100, 1., 2.8))
        d.px['high'][1, 0] = 100
        held[0].d0 = 8
        self.assertIsNone(m.rotation_choice(3, d, cfg, signals, ranks, held, np.ones(2) * 100, 1., 2.8))
        held[0].d0 = 0
        cfg['rotation'] = 'stall3'
        self.assertIsNone(m.rotation_choice(1, d, cfg, signals, ranks, held, np.ones(2) * 100, 1., 2.8))
        self.assertIsNotNone(m.rotation_choice(2, d, cfg, signals, ranks, held, np.ones(2) * 100, 1., 2.8))
        d.px['high'][1, 0] = 102.5
        self.assertIsNone(m.rotation_choice(2, d, cfg, signals, ranks, held, np.ones(2) * 100, 1., 2.8))

    def run_engine(self, gap=False, trigger=True, callback_enabled=True):
        days = np.busday_offset('2030-01-01', np.arange(4)).astype(str)
        o = np.full((8, 2), 100.)
        o[4:6, 0] = 90 if gap else 101
        px = dict(open=o, high=np.maximum(o + 2, 102), low=o - 1, close=o.copy(),
            dates=np.repeat(days, 2), codes=np.array(['SYNTHETIC_A', 'SYNTHETIC_B']),
            session=np.repeat(np.arange(4), 2), daily_close=np.tile([False, True], 4))
        rules = m.old.system.Rules(max_open=1, trail='', trims=(), buy_cost=0, sell_cost=0,
                                   margin_rate=0, intraday_kinds=('long',))
        first = ((-.1, 'SYNTHETIC_A'), 0, 1, 100., 95., 'long', None)
        second = ((-.9, 'SYNTHETIC_B'), 1, 1, 101., 96., 'long', None)
        book = [[first], [], [], [], [second] if trigger else [], [], [], []]
        called = []
        def callback(t, positions, openings, equity, gross):
            called.append((t, list(positions)))
            if t == 4 and 0 in positions:
                return dict(sold=0, target=1, signal_day=str(days[1]))
        simulate = m.rotation_simulator(callback if callback_enabled else None)
        track = {}
        result = simulate(px, {}, rules, book, str(days[0]), str(days[-1]), audit=True, track=track)
        return result, track, called, (px, rules, book)

    def test_rotation_executes_at_next_open_and_replacement_keeps_original_fill(self):
        (_, _, trades), track, called, _ = self.run_engine()
        old_trade = next(tr for tr in trades if tr['code'] == 'SYNTHETIC_A')
        self.assertEqual(old_trade['why'], 'rotate_open')
        self.assertEqual(old_trade['executions'][-1]['price'], 101)
        self.assertEqual(old_trade['days'], 2)
        self.assertEqual(len(trades), 2)
        self.assertEqual(len(track['rotations']), 1)
        self.assertTrue(all(t % 2 == 0 for t, _ in called))

    def test_fixed_gap_stop_precedes_rotation(self):
        (_, _, trades), track, _, _ = self.run_engine(gap=True)
        self.assertEqual(trades[0]['why'], 'gap_stop')
        self.assertNotIn('rotations', track)

    def test_open_sale_is_not_retroactively_cancelled_when_target_does_not_trigger(self):
        (_, _, trades), track, _, _ = self.run_engine(trigger=False)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]['why'], 'rotate_open')
        self.assertEqual(len(track['rotations']), 1)

    def test_disabled_hook_preserves_every_fixed_engine_fill_and_equity(self):
        (curve, days, trades), _, _, (px, rules, book) = self.run_engine(callback_enabled=False)
        actual = m.old.system.simulate(px, {}, rules, book, str(days[0]), str(days[-1]), audit=True)
        np.testing.assert_array_equal(curve, actual[0])
        self.assertEqual(trades, actual[2])

    def test_same_day_stop_still_precedes_partial_profit(self):
        px = dict(open=np.array([[100.]]), high=np.array([[130.]]), low=np.array([[90.]]), close=np.array([[110.]]),
                  dates=np.array(['2030-01-01']), codes=np.array(['SYNTHETIC']))
        event = (0., 0, 1, 100., 95., 'long', 95.)
        rules = m.old.system.Rules(trail='', trims=(3, 5), buy_cost=0, sell_cost=0,
                                   margin_rate=0, intraday_kinds=('long',))
        _, _, trades = m.rotation_simulator(None)(px, {}, rules, [[event]], '2030-01-01', '2030-01-01', audit=True)
        self.assertEqual([e['action'] for e in trades[0]['executions']], ['entry', 'stop_day0'])

    def test_rounds_keep_independent_groups_and_combine_only_effective_groups(self):
        for number in range(1, 6):
            choices = m.proposals(number, {})
            self.assertLessEqual(len(choices), 5)
            if number > 3:
                self.assertFalse(choices)
        groups = dict(A=dict(config=dict(m.BASE, stage='full')), B=dict(config=dict(m.BASE, flow='own')),
                      C=dict(config=dict(m.BASE, rotation='gap25')))
        self.assertEqual(len(m.proposals(4, groups)), 4)
        self.assertEqual(len(m.proposals(5, groups)), 2)
        for number, field in ((1, 'stage'), (2, 'flow'), (3, 'rotation')):
            for cfg in m.proposals(number, groups):
                self.assertTrue(all(v == m.BASE[k] for k, v in cfg.items() if k != field))

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
