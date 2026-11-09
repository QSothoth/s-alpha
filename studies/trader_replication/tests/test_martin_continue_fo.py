import unittest
import numpy as np
from studies.trader_replication import system


class NextOpenAddTests(unittest.TestCase):
    def run_case(self, rows, extra=None):
        a = np.array(rows, float)
        days = np.array(['2025-01-%02d' % (i + 1) for i in range(len(a))])
        px = {'open': a[:, :1], 'high': a[:, 1:2], 'low': a[:, 2:3], 'close': a[:, 3:4],
              'dates': days, 'codes': np.array(['US.A'])}
        entries = [[(0, 0, 1, 10., 9., 'n1')]] + [[] for _ in range(len(a) - 1)]
        values = dict(trail='', trims=(), add_levels=(1,), add_next_open=True, risk=.1, max_position=3.,
                      max_gross=3., buy_cost=0., sell_cost=0., margin_rate=0.)
        values.update(extra or {})
        track = {}
        curve, _, trades = system.simulate(px, {}, system.Rules(**values), entries, days[0], days[-1],
                                           audit=True, track=track)
        return curve, trades[0], track.get('add_orders', [])

    def test_confirmed_close_waits_for_next_open_and_uses_opening_price(self):
        rows = [(10, 10, 10, 10), (10, 11.2, 9.9, 11.), (11.5, 11.6, 10.5, 11.2)]
        curve, trade, events = self.run_case(rows)
        adds = [x for x in trade['executions'] if x['action'] == 'add']
        self.assertEqual([(x['time'], x['price']) for x in adds], [('2025-01-03', 11.5)])
        self.assertEqual([(x['status'], x['signal_day']) for x in events],
                         [('confirmed', '2025-01-02'), ('filled', '2025-01-02')])
        changed = rows[:2] + [(11.5, 30., 10.5, 11.2)]
        changed_curve, changed_trade, _ = self.run_case(changed)
        np.testing.assert_allclose(curve[:2], changed_curve[:2])
        self.assertEqual([x for x in changed_trade['executions'] if x['action'] == 'add'], adds)

    def test_cancel_equal_missing_and_gap_stop(self):
        base = [(10, 10, 10, 10), (10, 11.2, 9.9, 11.)]
        _, t, e = self.run_case(base + [(10.8, 11., 10.5, 10.8)])
        self.assertFalse(any(x['action'] == 'add' for x in t['executions']))
        self.assertEqual(e[-1]['status'], 'open_below_level')
        _, _, e = self.run_case(base + [(11., 11.1, 10.8, 11.)])
        self.assertEqual(e[-2]['status'], 'precision_unknown')
        _, t, e = self.run_case(base + [(np.nan, 11.1, 10.8, 11.), (11.5, 11.6, 10.5, 11.2)])
        self.assertEqual([x['status'] for x in e], ['confirmed', 'missing_open', 'filled'])
        self.assertEqual([x['price'] for x in t['executions'] if x['action'] == 'add'], [11.5])
        _, t, e = self.run_case(base + [(8.9, 9., 8.8, 8.9)])
        self.assertEqual((t['why'], e[-1]['status']), ('gap_stop', 'position_exit'))

    def test_added_position_observes_raised_stop_later_that_day(self):
        rows = [(10, 10, 10, 10), (10, 11.2, 9.9, 11.), (11.5, 11.6, 9.9, 10.2)]
        _, trade, _ = self.run_case(rows)
        self.assertEqual([x['action'] for x in trade['executions']], ['entry', 'add', 'stop'])
        self.assertEqual(trade['executions'][-1]['price'], 10.)

    def test_open_adds_compete_in_fixed_existing_position_order(self):
        days = np.array(['2025-01-01', '2025-01-02', '2025-01-03'])
        o = np.array([[10., 10.], [10., 10.], [11.5, 11.5]])
        c = np.array([[10., 10.], [11., 11.], [11.5, 11.5]])
        px = {'open': o, 'high': np.maximum(o, c) + .1, 'low': np.minimum(o, c) - .1,
              'close': c, 'dates': days, 'codes': np.array(['A', 'B'])}
        entries = [[(0, 1, 1, 10., 9., 'n1'), (1, 0, 1, 10., 9., 'n1')], [], []]
        rules = system.Rules(trail='', trims=(), add_levels=(1,), add_next_open=True, risk=.04,
                             max_position=.8, max_gross=1., buy_cost=0., sell_cost=0., margin_rate=0.)
        track = {}
        _, _, trades = system.simulate(px, {}, rules, entries, days[0], days[-1], audit=True, track=track)
        events = [e for e in track['add_orders'] if e['status'] in ('filled', 'budget_rejected')]
        self.assertEqual([(e['code'], e['status']) for e in events], [('A', 'filled'), ('B', 'budget_rejected')])
        self.assertEqual(sum(x['action'] == 'add' for t in trades for x in t['executions']), 1)

    def test_default_close_add_stays_unchanged(self):
        rows = [(10, 10, 10, 10), (10, 11.2, 9.9, 11.), (11.5, 11.6, 10.5, 11.2)]
        _, trade, events = self.run_case(rows, {'add_next_open': False})
        self.assertEqual([x['time'] for x in trade['executions'] if x['action'] == 'add'], ['2025-01-02'])
        self.assertEqual(events, [])

    def test_pending_add_remains_visible_at_end_and_signal_add_is_rejected(self):
        rows = [(10, 10, 10, 10), (10, 11.2, 9.9, 11.)]
        _, trade, events = self.run_case(rows)
        self.assertEqual(trade['why'], 'end')
        self.assertEqual(trade['state']['add_pending'], {'level': 11., 'signal_day': '2025-01-02'})
        self.assertEqual([e['status'] for e in events], ['confirmed'])
        with self.assertRaises(ValueError):
            self.run_case(rows, {'add_signal': 'other_signal'})


if __name__ == '__main__':
    unittest.main()
