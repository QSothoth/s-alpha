"""Execution timing of the day-N partial (Qullamaggie's "sell 1/3-1/2 after 3-5 days") and of adds on a new buy
point (Christian Flanders' "add at new buy points"): which close, which price, which stop afterwards."""
import unittest

import numpy as np

from studies.trader_replication import system as Y

NOCOST = dict(buy_cost=0, sell_cost=0, margin_rate=0, trail='', trims=(), risk=.01, max_position=10.0,
              max_gross=10.0)


def px(rows):
    a = np.array(rows, float)
    return {'open': a[:, :1], 'high': a[:, 1:2], 'low': a[:, 2:3], 'close': a[:, 3:4],
            'dates': np.array(['2025-01-%02d' % (i + 1) for i in range(len(a))]), 'codes': np.array(['US.AAA'])}


def run(rows, ema=None, **kw):
    p = px(rows)
    e = [[] for _ in rows]
    e[0].append((0, 0, 1, 10.0, 9.5, 'x'))
    return Y.simulate(p, ema or {}, Y.Rules(**{**NOCOST, **kw}), e, p['dates'][0], p['dates'][-1], audit=True)


UP = [(10, 10, 10, 10), (10.1, 10.6, 10.0, 10.5), (10.5, 10.9, 10.4, 10.8), (10.8, 11.1, 10.7, 11.0),
      (11.0, 11.2, 10.9, 11.1)]


class DayTrimTests(unittest.TestCase):
    def test_sells_the_fraction_at_the_close_of_day_n(self):
        _, _, (t,) = run(UP, trim_day=3, trim_day_frac=1 / 3)
        ex = [e for e in t['executions'] if e['action'] == 'day_trim']
        self.assertEqual([(e['time'], e['price']) for e in ex], [('2025-01-04', 11.0)])
        size0 = t['executions'][0]['shares']
        self.assertAlmostEqual(ex[0]['shares'], size0 / 3)
        self.assertEqual(t['why'], 'end')

    def test_no_trim_when_not_in_profit_unless_asked(self):
        rows = UP[:3] + [(10.0, 10.1, 9.7, 9.9), UP[4]]
        _, _, (t,) = run(rows, trim_day=3, trim_day_frac=1 / 3)
        self.assertFalse(any(e['action'] == 'day_trim' for e in t['executions']))
        _, _, (t,) = run(rows, trim_day=3, trim_day_frac=1 / 3, trim_day_profit=False)
        self.assertEqual([e['price'] for e in t['executions'] if e['action'] == 'day_trim'], [9.9])

    def test_breakeven_after_the_trim_exits_at_the_fill_next(self):
        rows = UP[:4] + [(10.6, 10.7, 9.8, 10.2)]       # dips below the 10.0 fill, stays above the 9.5 stop
        _, _, (t,) = run(rows, trim_day=3, trim_day_frac=.5, trim_day_breakeven=True)
        self.assertEqual(t['why'], 'stop')
        self.assertEqual(t['executions'][-1]['price'], 10.0)
        _, _, (t,) = run(rows, trim_day=3, trim_day_frac=.5)
        self.assertEqual(t['why'], 'end')

    def test_trim_happens_once(self):
        _, _, (t,) = run(UP, trim_day=1, trim_day_frac=.25)
        self.assertEqual(sum(e['action'] == 'day_trim' for e in t['executions']), 1)


class SignalAddTests(unittest.TestCase):
    def sig(self, days):
        m = np.zeros((len(UP), 1), bool)
        m[list(days), 0] = True
        return {'buy': m}

    def test_adds_at_the_signal_close_and_raises_the_stop_to_that_low(self):
        _, _, (t,) = run(UP, ema=self.sig([2]), add_signal='buy', add_frac=.5, add_signal_stop='low')
        adds = [e for e in t['executions'] if e['action'] == 'add']
        self.assertEqual([(e['time'], e['price']) for e in adds], [('2025-01-03', 10.8)])
        self.assertAlmostEqual(adds[0]['shares'] * 10.8, .5 * t['executions'][0]['shares'] * 10.8)
        rows = UP[:3] + [(10.6, 10.7, 10.3, 10.5), UP[4]]       # day 3 low 10.3 breaks the raised 10.4 stop
        _, _, (t,) = run(rows, ema=self.sig([2]), add_signal='buy', add_frac=.5, add_signal_stop='low')
        self.assertEqual((t['why'], t['executions'][-1]['price']), ('stop', 10.4))

    def test_keep_stop_limit_and_no_add_on_the_entry_day(self):
        _, _, (t,) = run(UP, ema=self.sig([0, 1, 2, 3]), add_signal='buy', add_signal_frac=.25, add_signal_max=2)
        adds = [e['time'] for e in t['executions'] if e['action'] == 'add']
        self.assertEqual(adds, ['2025-01-02', '2025-01-03'])
        rows = UP[:3] + [(10.0, 10.1, 9.6, 9.9), UP[4]]          # 9.6 keeps above the original 9.5 stop
        _, _, (t,) = run(rows, ema=self.sig([1]), add_signal='buy', add_signal_frac=.25)
        self.assertEqual(t['why'], 'end')

    def test_signal_adds_leave_r_add_levels_alone(self):
        _, _, (t,) = run(UP, ema=self.sig([2]), add_signal='buy', add_signal_frac=.25, add_r=1.0)
        self.assertEqual([e['time'] for e in t['executions'] if e['action'] == 'add'], ['2025-01-02', '2025-01-03'])

    def test_winners_only(self):
        rows = UP[:2] + [(10.0, 10.1, 9.7, 9.9)] + UP[3:]       # day 2 closes under the 10.0 fill: no add then
        _, _, (t,) = run(rows, ema=self.sig([2, 3]), add_signal='buy', add_signal_frac=.25, add_signal_profit=True)
        self.assertEqual([e['time'] for e in t['executions'] if e['action'] == 'add'], ['2025-01-04'])
        _, _, (t,) = run(rows, ema=self.sig([2, 3]), add_signal='buy', add_signal_frac=.25)
        self.assertEqual([e['time'] for e in t['executions'] if e['action'] == 'add'], ['2025-01-03', '2025-01-04'])

    def test_defaults_change_nothing(self):
        a = run(UP)[0]
        b = run(UP, ema=self.sig([1, 2]), trim_day=0, add_signal='')[0]
        np.testing.assert_allclose(a, b)


if __name__ == '__main__':
    unittest.main()
