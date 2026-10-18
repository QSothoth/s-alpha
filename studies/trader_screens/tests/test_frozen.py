"""Rule-book helpers of the replicated system: exit levels read back from the engine, the ladder, the forward split."""
import unittest

import numpy as np

from studies.trader_replication import system as Y
from studies.trader_screens import frozen as scan

# one stock: entry at 100 with a 99 stop (1R = 1), +10R partial and add on day 2, a dip below cost on day 4
BARS = [(100, 100.5, 99.5, 100), (101, 105.5, 100.5, 105), (106, 111.5, 105.5, 111), (111, 112.5, 110.5, 112),
        (111, 111.5, 99.5, 101)]
DATES = np.array(['2026-01-05', '2026-01-06', '2026-01-07', '2026-01-08', '2026-01-09'])
RULES = Y.Rules(risk=.01, max_position=3.0, max_gross=5.0, trims=(10,), trim_frac=.3, trail='tl', add_levels=(10,))


def px(n):
    a = np.array(BARS[:n], float)
    return dict(open=a[:, :1], high=a[:, 1:2], low=a[:, 2:3], close=a[:, 3:4], dates=DATES[:n],
                codes=np.array(['US.X']))


def run(n, rules=RULES, entry=(0, 0, 1, 100.0, 99.0, 'x')):
    ema = {'tl': np.full((n, 1), 95.0)}
    entries = [[entry]] + [[] for _ in range(n - 1)]
    return Y.simulate(px(n), ema, rules, entries, DATES[0], DATES[n - 1], audit=True)


class PositionStateTests(unittest.TestCase):
    def test_levels_after_a_partial_and_an_add(self):
        _, _, tr = run(4)
        (t,) = tr
        self.assertEqual(t['why'], 'end')
        p = scan.position_state(t, px(4)['close'][:, 0], np.full(4, 95.0), DATES[:4], RULES)
        self.assertEqual(p['stop'], 100.0)                       # moved to cost by the executed add
        self.assertTrue(p['added'] and p['armed'])
        self.assertEqual(p['trims'], 1)
        self.assertIsNone(p['next_trim'])
        self.assertIsNone(p['next_add'])
        self.assertAlmostEqual(p['r_now'], 12.0)

    def test_the_engine_exits_the_next_day_at_the_stop_read_back(self):
        _, _, tr4 = run(4)
        p = scan.position_state(tr4[0], px(4)['close'][:, 0], np.full(4, 95.0), DATES[:4], RULES)
        _, _, tr5 = run(5)
        (t,) = tr5
        self.assertEqual(t['why'], 'stop')
        self.assertEqual(t['executions'][-1]['price'], p['stop'])
        self.assertAlmostEqual(sum(e['shares'] for e in t['executions'][-1:]), p['shares'])

    def test_untouched_position_keeps_its_stop_and_levels(self):
        _, _, tr = run(2)
        p = scan.position_state(tr[0], px(2)['close'][:, 0], np.full(2, 120.0), DATES[:2], RULES)
        self.assertEqual(p['stop'], 99.0)
        self.assertFalse(p['added'] or p['armed'])
        self.assertEqual(p['next_trim'], 110.0)
        self.assertEqual(p['next_add'], 110.0)

    def test_rules_it_cannot_read_back_are_refused(self):
        _, _, tr = run(2)
        with self.assertRaises(NotImplementedError):
            scan.position_state(tr[0], px(2)['close'][:, 0], np.full(2, 95.0), DATES[:2],
                                Y.Rules(trail='tl', breakeven_r=3.0))


class LadderTests(unittest.TestCase):
    def test_furthest_step_over_the_window(self):
        days = np.array(['d0', 'd1', 'd2'])
        mask = np.array([[True], [True], [False]])
        sets = {'raw': [{0}, {0}, set()], 'filtered': [set(), {0}, set()], 'capped': [set(), set(), set()]}
        self.assertEqual(scan.furthest_step(mask, sets, {}, 'US.X', 0, 0, 0, days), ('market_filter', None))
        self.assertEqual(scan.furthest_step(mask, sets, {}, 'US.X', 0, 0, 2, days), ('daily_cap', None))
        sets['capped'][1] = {0}
        ours = {('US.X', 'd1'): {'r': 2.0}}
        self.assertEqual(scan.furthest_step(mask, sets, ours, 'US.X', 0, 0, 2, days), ('traded', {'r': 2.0}))
        self.assertEqual(scan.furthest_step(mask, sets, ours, 'US.X', 0, 2, 2, days)[0], 'no_signal')


class ForwardTests(unittest.TestCase):
    def test_forward_starts_at_the_freeze_close(self):
        dates = np.array(['2026-10-15', '2026-10-16', '2026-10-19', '2026-10-20'])
        curve = [1.0, 2.0, 1.5, 2.2]
        trades = [{'entry': '2026-10-16'}, {'entry': '2026-10-19'}]
        f = scan.forward(curve, dates, trades, '2026-10-16')
        self.assertEqual((f['since'], f['days']), ('2026-10-16', 2))
        self.assertAlmostEqual(f['ret'], .1)
        self.assertAlmostEqual(f['maxdd'], .25)
        self.assertEqual(f['trades'], [{'entry': '2026-10-19'}])

    def test_years_until_ignores_days_after_the_freeze(self):
        dates = np.array(['2024-12-31', '2025-06-30', '2025-12-31', '2026-01-05'])
        y = scan.years_until([2.0, 3.0, 4.0, 8.0], dates, '2025-12-31')
        self.assertEqual(y, {'2024': 1.0, '2025': 1.0})
        self.assertEqual(scan.years_until([2.0, 3.0], dates[:2], '2025-12-31'), {'2024': 1.0})

    def test_no_forward_part_on_the_research_data(self):
        dates = np.array(['2026-10-15', '2026-10-16'])
        f = scan.forward([1.0, 2.0], dates, [], '2026-10-16')
        self.assertEqual(f['days'], 0)


if __name__ == '__main__':
    unittest.main()
