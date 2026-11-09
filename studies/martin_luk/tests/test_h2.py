"""Observable H2 close stops, concentration, proof adds and causal market inputs."""
from datetime import date, timedelta
import unittest

import numpy as np

from studies.martin_luk import h2_policy as H, h2_research as X, luk
from studies.trader_replication import system as Y


class H2Tests(unittest.TestCase):
    def account(self, close, book, changes=None, px_changes=None, e9=None, enabled=True):
        c = np.asarray(close, float)
        dates = np.array([str(date(2025, 1, 6)+timedelta(days=d)) for d in range(len(c))])
        px = dict(open=c.copy(), high=c+1, low=c-.1, close=c, dates=dates,
                  codes=np.array([f'TEST_{j}' for j in range(c.shape[1])]))
        px.update(px_changes or {})
        ema = dict(e9=np.full(c.shape, 90.) if e9 is None else e9)
        tol = dict(adr=np.full(c.shape, 10.), groups=[{} for _ in c], strength=np.zeros(c.shape),
            forms=np.ones(c.shape, np.uint8), e50=np.full(c.shape, 80.),
            distribution=np.zeros(c.shape, bool), stretch=np.zeros(c.shape, bool),
            breadth_ok=np.ones(len(c), bool), qqq_good=np.ones(len(c), bool), disaster=2.,
            max_long=4, weekly=4, probe=True, retry=True, feedback=True)
        tol.update(changes or {})
        rules = Y.Rules(risk=.0075, max_position=.3, max_gross=2.8, trail='', trims=(),
                        buy_cost=0., sell_cost=0., margin_rate=0.)
        track = {'entry_attempts': []}
        result = Y.simulate(px, ema, rules, book, dates[0], dates[-1], audit=True, track=track,
                            daily_tolerance=tol if enabled else None)
        return result, track

    @staticmethod
    def offer(j=0, price=100., stop=90.):
        return (j, j, 1, price, stop, 'h2_close', None, None, .3)

    def test_structure_is_close_only_and_disaster_has_a_fifteen_percent_floor(self):
        c = [[100.], [95.], [89.]]
        (_, _, trades), _ = self.account(c, [[self.offer()], [], []],
            px_changes={'low': np.array([[99.], [86.], [88.]])})
        self.assertEqual((trades[0]['exit'], trades[0]['why']), ('2025-01-08', 'close_stop'))
        self.assertEqual(trades[0]['disaster_stop'], 85.)
        (_, _, trades), _ = self.account([[100.], [90.]], [[self.offer()], []],
            px_changes={'open': np.array([[100.], [80.]]), 'low': np.array([[99.], [79.]])})
        self.assertEqual(trades[0]['executions'][-1]['price'], 80.)
        self.assertEqual(trades[0]['why'], 'gap_stop')

    def test_proof_add_targets_cap_and_raises_only_the_close_stop(self):
        high = np.array([[105.], [106.], [111.], [110.]])
        (_, _, trades), track = self.account([[100.], [102.], [110.], [99.]],
            [[self.offer()], [], [], []], px_changes={'high': high})
        t = trades[0]
        self.assertAlmostEqual(track['tolerance_entries'][0]['initial_fraction'], .075)
        adds = [e for e in t['executions'] if e['action'] == 'add']
        self.assertEqual([e['time'] for e in adds], ['2025-01-08'])
        held = track['tolerance_holdings'][2]
        self.assertAlmostEqual(held['holdings'][0]['value']/held['equity'], .3)
        self.assertEqual((t['confirmed_day'], t['why']), ('2025-01-08', 'close_stop'))
        self.assertEqual(t['disaster_stop'], 85.)

    def test_new_completed_high_can_confirm_before_one_R(self):
        (_, _, trades), _ = self.account([[100.], [102.]], [[self.offer()], []])
        self.assertTrue(trades[0]['confirmed'])
        self.assertEqual(trades[0]['executions'][1]['action'], 'add')

    def test_trim_is_fifteen_percent_of_added_size_then_close_ema_exit(self):
        c = [[100.], [110.], [130.], [119.]]
        e9 = np.array([[90.], [100.], [120.], [120.]])
        (_, _, trades), _ = self.account(c, [[self.offer()], [], [], []], e9=e9)
        es = trades[0]['executions']
        trim = next(e for e in es if e['action'] == 'signal_trim')
        shares = sum(e['shares'] for e in es if e['action'] in ('entry', 'add') and e['time'] <= trim['time'])
        self.assertAlmostEqual(trim['shares'], .15*shares)
        self.assertEqual(trades[0]['why'], 'trail')

    def test_weekly_and_theme_limits_count_real_long_entries_only(self):
        c = np.full((2, 6), 100.)
        offers = [self.offer(j) for j in range(5)]
        (_, _, trades), track = self.account(c, [offers, []])
        self.assertEqual(len(trades), 4)
        self.assertEqual(track['entry_attempts'][-1]['reason'], 'weekly_long')
        groups = [{0: 0, 1: 0, 2: 0}, {}]
        (_, _, trades), track = self.account(c, [[*offers[:3], (9, 5, -1, 100., 110., 'short')], []],
                                             {'groups': groups})
        self.assertEqual(sum(t['side'] > 0 for t in trades), 2)
        self.assertEqual(sum(t['side'] < 0 for t in trades), 1)
        self.assertIn('theme_slots', [r['reason'] for r in track['entry_attempts']])

    def test_only_active_theme_can_replace_an_old_unconfirmed_probe(self):
        c = np.full((3, 5), 100.)
        c[1:, 0] = 110.
        book = [[self.offer(j) for j in range(4)], [self.offer(4)], []]
        (_, _, trades), track = self.account(c, book, {'weekly': 0, 'groups': [{}, {4: 0}, {}]})
        victim = next(t for t in trades if t['why'] == 'make_room')
        self.assertEqual(victim['code'], 'TEST_1')
        self.assertTrue(next(t for t in trades if t['code'] == 'TEST_0')['confirmed'])
        self.assertEqual(max(len(r['holdings']) for r in track['tolerance_holdings']), 4)
        (_, _, _,), track = self.account(c, book, {'weekly': 0})
        self.assertEqual(track['entry_attempts'][-1]['reason'], 'long_slots')

    def test_retries_have_a_rolling_limit_and_a_new_stop_does_not_erase_it(self):
        c = np.full((13, 1), 100.)
        c[[1, 3, 5], 0] = 89.
        book = [[] for _ in c]
        for d in (0, 2, 4, 6, 12):
            book[d] = [self.offer()]
        (_, _, trades), track = self.account(c, book, {'weekly': 0})
        self.assertEqual([t['entry'] for t in trades], ['2025-01-06', '2025-01-08', '2025-01-10', '2025-01-18'])
        self.assertIn('retry_limit', [r['reason'] for r in track['entry_attempts']])
        (_, _, trades), track = self.account(c, book, {'weekly': 0, 'retry': False})
        self.assertEqual([t['entry'] for t in trades], ['2025-01-06', '2025-01-18'])
        self.assertIn('retry_disabled', [r['reason'] for r in track['entry_attempts']])

    def test_a_newly_merged_theme_keeps_two_and_preserves_proven_positions_first(self):
        c = np.full((2, 3), 100.)
        c[1, 0] = 110.
        (_, _, trades), track = self.account(c, [[self.offer(j) for j in range(3)], []],
            {'groups': [{}, {0: 0, 1: 0, 2: 0}]})
        self.assertEqual(len(track['tolerance_holdings'][-1]['holdings']), 2)
        victim = next(t for t in trades if t['why'] == 'theme_cap')
        self.assertEqual(victim['code'], 'TEST_1')
        self.assertTrue(next(t for t in trades if t['code'] == 'TEST_0')['confirmed'])

    def test_stop_feedback_halves_probes_until_a_real_proof_add(self):
        c = np.full((5, 7), 100.)
        c[1, :5] = 89.
        c[3:, 5] = 111.
        book = [[self.offer(j) for j in range(5)], [], [self.offer(5)], [], [self.offer(6)]]
        (_, _, _), track = self.account(c, book, {'weekly': 0, 'max_long': 0})
        entries = track['tolerance_entries']
        self.assertAlmostEqual(entries[-2]['risk_fraction'], .00375)
        self.assertAlmostEqual(entries[-1]['risk_fraction'], .0075)
        (_, _, _), track = self.account(c, book,
            {'weekly': 0, 'max_long': 0, 'qqq_good': np.zeros(5, bool)})
        self.assertAlmostEqual(track['tolerance_entries'][-2]['risk_fraction'], .001875)

    def test_distribution_exit_precedes_proof_add_and_disabled_mode_is_legacy(self):
        mask = np.array([[False], [True]])
        (_, _, trades), _ = self.account([[100.], [110.]], [[self.offer()], []], {'distribution': mask})
        self.assertEqual([e['action'] for e in trades[0]['executions']], ['entry', 'distribution'])
        (_, _, trades), _ = self.account([[100.], [89.]], [[self.offer()], []], enabled=False)
        self.assertEqual(trades[0]['why'], 'gap_stop')
        self.assertNotIn('disaster_stop', trades[0])

    def test_pool_uses_absolute_dollars_and_features_ignore_future_changes(self):
        n = 90
        path = 100*np.cumprod(1.008+.001*np.sin(np.arange(n)))
        c = np.broadcast_to(path[:, None], (n, 3)).copy()
        A = dict(close=c, high=c*1.04, low=c*.96, open=c*.995,
                 days=np.array([str(date(2024, 1, 1)+timedelta(days=i)) for i in range(n)]),
                 codes=np.array(['TEST_A', 'TEST_B', 'TEST_C']))
        for name, horizon in (('e9', 9), ('e21', 21), ('e50', 50)):
            A['native_'+name] = luk.ema(c, horizon)
        p = dict(turnover=np.broadcast_to([120e6, 20e6, 19e6], c.shape).copy())
        f = H.features(A, p, c[:, 0])
        self.assertEqual(f['pool'][-1].tolist(), [True, True, False])
        self.assertEqual(f['leaders'][-1].tolist(), [True, True, False])
        self.assertAlmostEqual(float(f['cap'][-1, 1]), .2, places=6)
        self.assertEqual(f['groups'][-1][0]['members'], [0, 1])
        prefix = 75
        cut = H.features({k: v[:prefix] if k != 'codes' else v for k, v in A.items()},
                         {'turnover': p['turnover'][:prefix]}, c[:prefix, 0])
        for name in ('pool', 'leaders', 'upgrades', 'forms', 'adr'):
            np.testing.assert_array_equal(f[name][:prefix], cut[name])
        self.assertEqual(f['groups'][:prefix], cut['groups'])
        # A volume reversal below EMA9 still exits; the task gives no EMA filter.
        A['close'][-1, 0] = A['native_e9'][-1, 0]*.95
        A['low'][-1, 0] = A['close'][-1, 0]*.99
        p['turnover'][-1, 0] = 1e9
        changed = H.features(A, p, c[:, 1])
        self.assertTrue(changed['distribution'][-1, 0])

    def test_selection_rejects_smaller_capital_even_with_more_early_legs(self):
        def result(capital, early=4):
            return dict(years={y: dict(hard=dict(nonnegative=True, win=True, trades=True), early=early,
                leg_count=9 if y == '2024' else 22, strict=dict(cap_equity=capital, purity_gross=.5),
                b_score=5, checks={'payoff': {'ours': 5.}}) for y in ('2024', '2025')})
        chosen = X.select({'H2A': result(.10, 7), 'H2B': result(.20)}, result(.18))
        self.assertEqual(chosen['chosen'], 'H2B')
        self.assertIn('2025_capital', chosen['failures']['H2A'])


if __name__ == '__main__':
    unittest.main()
