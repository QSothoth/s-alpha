import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

import numpy as np

from studies.trader_replication import martin_continue_ie20 as m
from studies.trader_replication.tests import test_martin_continue_ie19 as prior


class PastOnly:
    def __init__(self, array, last):
        self.array, self.last = array, last

    def __getitem__(self, item):
        first = item[0] if isinstance(item, tuple) else item
        if not isinstance(first, (int, np.integer)) or first < 0 or first > self.last:
            raise AssertionError('unfinished session read')
        return self.array[item]


class IE20Tests(unittest.TestCase):
    def synthetic(self, cut=320, change=None):
        return prior.IE19Tests().synthetic(cut=cut, change=change)

    def tiny(self):
        n = 6
        close = np.full((30, n), 100.)
        f = {k: np.ones((30, n)) for k in ('e9', 'e21', 'adr', 'money', 'ep', 'pullback', 'inside', 'narrow')}
        f.update(e9=close.copy(), e21=close - 1, adr=np.full_like(close, 6),
                 money=np.array([[1e8, 2e8, 5e8, 3e8, 8e8, 9e8]] * 30),
                 ep=np.zeros_like(close), inside=np.zeros_like(close), narrow=np.zeros_like(close))
        d = SimpleNamespace(codes=['SYNTHETIC_' + str(j) for j in range(n)],
            px=dict(close=close), f=f, strength=dict(extension=np.ones_like(close)),
            wave=dict(own_money=np.array([[0, 1, 2, 3, 4, 5]] * 30)))
        template = {k: np.ones_like(close, bool) for k in ('pool', 'trend', 'setup')}
        return d, template

    def test_baseline_order_matches_previous_without_priority_lane(self):
        d, _ = self.tiny()
        signals = np.ones(6, bool)
        keys = m.queue_keys(25, d, m.BASE, signals)
        indices, primary, secondary = m.previous.queue_scores(25, d, m.BASE, signals)
        oldkeys = m.previous.queue_keys(primary, secondary, d.codes, 'primary')
        self.assertEqual(sorted(keys, key=keys.get), sorted(indices, key=lambda j: oldkeys[j]))

    def test_ep_gets_only_one_priority_position_from_completed_night(self):
        d, _ = self.tiny()
        d.f['ep'][25, :3] = 1
        d.px['close'][25, :3] = [101, 104, 110]
        keys = m.queue_keys(25, d, dict(m.BASE, queue20='ep_one'), np.ones(6, bool))
        self.assertEqual([j for j, key in keys.items() if key[0] == 0], [2])
        d.f['ep'][26, :] = 1
        self.assertEqual(keys, m.queue_keys(25, d, dict(m.BASE, queue20='ep_one'), np.ones(6, bool)))

    def test_non_signals_do_not_change_any_queue(self):
        for cfg in m.proposals(1, {}):
            d, _ = self.tiny()
            signals = np.array([True, False, True, True, False, True])
            d.f['ep'][25, 0] = 1
            before = m.queue_keys(25, d, cfg, signals)
            for group in (d.f, d.strength, d.wave, d.px):
                for a in group.values():
                    a[:, ~signals] = 1e15
            self.assertEqual(before, m.queue_keys(25, d, cfg, signals))

    def test_narrow_distance_keeps_ep_and_has_closed_boundaries(self):
        d, b = self.tiny()
        d.strength['extension'][25] = [-.01, 0, 1, 2, 2.01, 9]
        d.f['ep'][25, 5] = 1
        _, signal = m.selection_row(25, d, dict(m.BASE, signal20='near'), b)
        np.testing.assert_array_equal(signal, [False, True, True, True, False, True])

    def test_structure_requires_a_decline_or_a_real_breakout_setup(self):
        d, b = self.tiny()
        d.px['close'][24, 0] = 101
        d.f['inside'][25, 1] = 1
        d.f['narrow'][25, 2] = 1
        d.f['pullback'][25, 3] = 0
        d.f['ep'][25, 4] = 1
        _, signal = m.selection_row(25, d, dict(m.BASE, signal20='structure'), b)
        np.testing.assert_array_equal(signal, [True, True, True, True, True, False])

    def test_pool_exception_requires_liquidity_strict_adr_and_original_shape(self):
        d, b = self.tiny()
        b['pool'][:] = False
        d.f['adr'][25] = [3, 3.01, 4, 5, 4, 4]
        d.f['money'][25, 4] = 1e8 - 1
        b['setup'][25, 5] = False
        pool, signal = m.selection_row(25, d, dict(m.BASE, pool20='premier3'), b)
        np.testing.assert_array_equal(pool, [False, True, True, True, False, True])
        np.testing.assert_array_equal(signal, [False, True, True, True, False, False])
        for name in ('premier4', 'premier3', 'premier3_near'):
            b['pool'][25, 4] = True
            pool, _ = m.selection_row(25, d, dict(m.BASE, pool20=name), b)
            self.assertTrue(pool[4])

    def test_selection_and_queue_read_only_completed_sessions(self):
        d, b = self.tiny()
        guarded = SimpleNamespace(codes=d.codes, **{name: {k: PastOnly(v, 25)
            for k, v in getattr(d, name).items()} for name in ('px', 'f', 'strength', 'wave')})
        safe_b = {k: PastOnly(v, 25) for k, v in b.items()}
        for number in (1, 2, 3):
            for cfg in m.proposals(number, {}):
                actual = m.selection_row(25, d, cfg, b)
                safe = m.selection_row(25, guarded, cfg, safe_b)
                for a, c in zip(actual, safe):
                    np.testing.assert_array_equal(a, c)
                self.assertEqual(m.queue_keys(25, d, cfg, actual[1]),
                                 m.queue_keys(25, guarded, cfg, actual[1]))

    def test_orders_and_signals_ignore_revised_future_and_truncated_suffix(self):
        cfgs = [m.BASE, dict(m.BASE, queue20='typed', signal20='near', pool20='premier3'),
                dict(m.BASE, signal20='structure'), dict(m.BASE, queue20='cap_money', signal20='trend')]
        for cfg in cfgs:
            full = m.build(self.synthetic(), cfg)
            for d in (self.synthetic(cut=280), self.synthetic(change=280)):
                part = m.build(d, cfg)
                self.assertEqual(full['book'][:560], part['book'][:560])
                np.testing.assert_array_equal(full['signals']['long'][:279], part['signals']['long'][:279])

    def test_candidates_are_at_most_four_rounds_with_training_only_combinations(self):
        self.assertEqual(m.proposals(4, {}), [])
        self.assertEqual(m.proposals(4, dict(A=dict(config=dict(m.BASE, queue20='typed')))), [])
        effective = {n: dict(config=m.proposals(i, {})[0]) for i, n in enumerate('ABC', 1)}
        self.assertEqual(len(m.proposals(4, effective)), 4)
        for number in range(1, 5):
            self.assertLessEqual(len(m.proposals(number, effective)), 5)

    def test_prior_namespaces_and_sources_have_no_ledger_constants(self):
        self.assertIs(m.previous.shared.build, m.previous.build)
        self.assertEqual(m.previous.WORK.name, 'ie19_work')
        labels = m.old.ledger.load(m.old.LEDGER)
        forbidden = {r.ticker for r in labels} | {'US.' + r.ticker for r in labels}
        forbidden |= {r.entry_date for r in labels if r.entry_date}
        for path in (Path(m.__file__), Path(__file__), *m.WORK.glob('*.py')):
            literals = {n.value for n in ast.walk(ast.parse(path.read_text()))
                        if isinstance(n, ast.Constant) and isinstance(n.value, str)}
            self.assertFalse(literals & forbidden, path.name)


if __name__ == '__main__':
    unittest.main()
