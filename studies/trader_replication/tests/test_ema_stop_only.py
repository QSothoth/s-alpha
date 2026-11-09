import unittest
from dataclasses import replace
from types import SimpleNamespace

import numpy as np

from studies.trader_replication import runner, system
from studies.trader_replication.martin_continue_cj import list_ema_stop
from studies.trader_replication.tests.test_runner import Toy, panel
from studies.trader_replication.tests.test_system import NOCOST


def prices(last_open=98.):
    return {'open': np.array([[100., 100.], [100., 100.], [last_open, last_open]]),
            'high': np.array([[100., 100.], [101., 101.], [99., 99.]]),
            'low': np.array([[100., 100.], [97., 97.], [93., 93.]]),
            'close': np.array([[100., 100.], [98., 98.], [96., 96.]]),
            'dates': np.array(['2025-01-02', '2025-01-03', '2025-01-06']),
            'codes': np.array(['LIST', 'CORE'])}


class EmaStopOnlyTests(unittest.TestCase):
    def test_candidate_changes_only_list_management(self):
        base = system.Rules(trail='e21', management_by_kind={'list': {'add_levels': (1, 3)},
                                                             'core': {'max_position': .2}})
        changed = list_ema_stop(base)
        self.assertEqual(replace(changed, management_by_kind=base.management_by_kind), base)
        self.assertEqual(changed.management_by_kind['core'], base.management_by_kind['core'])
        self.assertEqual(changed.management_by_kind['list']['add_levels'], (1, 3))
        self.assertTrue(changed.management_by_kind['list']['stop_ema_only'])

    def test_entry_close_sets_next_session_stop_without_reading_that_sessions_ema(self):
        p = prices()
        p['low'][1, 0] = 95.
        e = [[(0, 0, 1, 100., 90., 'list')], [], []]
        rules = system.Rules(trail='e9', trims=(), arm_trail_on_entry=True, stop_ema_only=True,
                             stop_ema_buffer=.03, **NOCOST)
        for next_ema in (50., 150.):
            ema = {'e9': np.array([[99., 99.], [next_ema, 99.], [99., 99.]])}
            _, _, tr = system.simulate(p, ema, rules, e, p['dates'][0], p['dates'][-1], audit=True)
            self.assertEqual((tr[0]['why'], tr[0]['exit']), ('stop', p['dates'][1]))
            self.assertAlmostEqual(tr[0]['executions'][-1]['price'], 99 * .97)

    def test_entry_close_sets_stop_and_only_the_list_ignores_close_cross(self):
        p = prices()
        e = [[(0, 0, 1, 100., 90., 'list'), (1, 1, 1, 100., 90., 'core')], [], []]
        rules = system.Rules(trail='e9', trims=(), arm_trail_on_entry=True,
                             management_by_kind={'list': {'stop_ema_only': True, 'stop_ema_buffer': .03}}, **NOCOST)
        ema = {'e9': np.full((3, 2), 99.)}
        _, _, tr = system.simulate(p, ema, rules, e, p['dates'][0], p['dates'][-1], audit=True)
        by = {t['code']: t for t in tr}
        self.assertEqual((by['CORE']['why'], by['CORE']['exit']), ('trail', p['dates'][1]))
        self.assertEqual((by['LIST']['why'], by['LIST']['exit']), ('stop', p['dates'][2]))
        self.assertAlmostEqual(by['LIST']['executions'][-1]['price'], 99 * .97)
        ema['e9'][2, 0] = 500.
        _, _, changed = system.simulate(p, ema, rules, e, p['dates'][0], p['dates'][-1], audit=True)
        self.assertEqual(next(t for t in changed if t['code'] == 'LIST')['executions'][-1]['price'],
                         by['LIST']['executions'][-1]['price'])

    def test_gap_below_protection_exits_at_open(self):
        p = prices(last_open=94.)
        e = [[(0, 0, 1, 100., 90., 'list')], [], []]
        rules = system.Rules(trail='e9', trims=(), arm_trail_on_entry=True, stop_ema_only=True,
                             stop_ema_buffer=.03, **NOCOST)
        _, _, tr = system.simulate(p, {'e9': np.full((3, 2), 99.)}, rules, e, p['dates'][0], p['dates'][-1])
        self.assertEqual(tr[0]['why'], 'gap_stop')
        self.assertAlmostEqual(tr[0]['ret'], -.06)

    def test_requires_a_valid_available_trail_and_buffer(self):
        p = prices()
        for rules, ema in ((system.Rules(trail='e9', stop_ema_only=True), {'e9': np.ones((3, 2))}),
                           (system.Rules(trail='e9', stop_ema_only=True, stop_ema_buffer=.03), {})):
            with self.subTest(rules=rules, ema=bool(ema)), self.assertRaisesRegex(ValueError, 'EMA-stop-only'):
                system.simulate(p, ema, rules, [[], [], []], p['dates'][0], p['dates'][-1])

    def test_intraday_entry_cannot_arm_on_its_fill_days_close_ema(self):
        p = prices()
        e = [[(0, 0, 1, 100., 90., 'list')], [], []]
        rules = system.Rules(trail='e9', stop_ema_only=True, stop_ema_buffer=.03, arm_trail_on_entry=True,
                             intraday_kinds=('list',))
        with self.assertRaisesRegex(ValueError, 'requires a close entry'):
            system.simulate(p, {'e9': np.full((3, 2), 99.)}, rules, e, p['dates'][0], p['dates'][-1])

    def test_runner_shows_stop_but_no_close_exit_for_stop_only(self):
        p = panel()
        class StopToy(Toy):
            def build(self, A, cfg, trace=None):
                entries = [[] for _ in A['days']]
                d = len(entries) - 1
                fill = float(A['close'][d, 0])
                entries[d].append((0., 0, 1, fill, fill * .9, 'list'))
                rules = system.Rules(trail='e9', stop_ema_only=True, stop_ema_buffer=.03,
                                     arm_trail_on_entry=True, trims=())
                return entries, rules, np.zeros(A['close'].shape, bool), np.ones(A['close'].shape, bool)
            def ema_inputs(self, A, pool, rules):
                return {'e9': A['close'] * .99}
        toy = StopToy(p)
        s = SimpleNamespace(id='toy', study=toy, config={}, name='Toy', version='V1', status='research', label='V1',
                            freeze=p['days'][-1], strategy={})
        (holding,) = runner.run(s, 'us')['holdings']
        self.assertAlmostEqual(holding['stop'], float(p['close'][-1, 0]) * .99 * .97)
        self.assertIsNone(holding['trail'])
        self.assertEqual(holding['trail_name'], '')


if __name__ == '__main__':
    unittest.main()
