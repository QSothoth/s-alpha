"""Execution timing of short target lines (Qullamaggie: "the target is the 10 and 20-day"): a short covers when the
day's low reaches the line's value at the previous close, at the open when it opens below; a stop day covers at the
stop unless the open is already below the target; partial at the first line, the rest at the last."""
import unittest

import numpy as np

from studies.trader_replication import system as Y

NOCOST = dict(buy_cost=0, sell_cost=0, margin_rate=0, trail='', trims=(), risk=.01, max_position=10.0,
              max_gross=10.0)


def run(rows, lines, **kw):
    a = np.array(rows, float)
    p = {'open': a[:, :1], 'high': a[:, 1:2], 'low': a[:, 2:3], 'close': a[:, 3:4],
         'dates': np.array(['2025-01-%02d' % (i + 1) for i in range(len(a))]), 'codes': np.array(['US.AAA'])}
    ema = {k: np.array(v, float)[:, None] for k, v in lines.items()}
    e = [[] for _ in rows]
    e[0].append((0, 0, -1, 10.0, 10.5, 'short'))
    return Y.simulate(p, ema, Y.Rules(**{**NOCOST, **kw}), e, p['dates'][0], p['dates'][-1], audit=True)[2]


class ShortTargetTests(unittest.TestCase):
    def test_off_by_default(self):
        self.assertEqual(Y.Rules().short_targets, ())

    def test_covers_at_the_previous_close_line_when_the_low_reaches_it(self):
        rows = [(10, 10, 10, 10), (9.9, 10.0, 9.4, 9.6), (9.5, 9.6, 9.0, 9.1)]
        (t,) = run(rows, {'m10': [9.5, 9.0, 8.0]}, short_targets=('m10',))
        self.assertEqual((t['exit'], t['why']), ('2025-01-02', 'target'))
        self.assertAlmostEqual(t['executions'][-1]['price'], 9.5)       # day 0's line, not day 1's 9.0

    def test_opening_below_the_line_covers_at_the_open(self):
        rows = [(10, 10, 10, 10), (9.3, 9.4, 9.1, 9.2)]
        (t,) = run(rows, {'m10': [9.5, 9.0]}, short_targets=('m10',))
        self.assertAlmostEqual(t['executions'][-1]['price'], 9.3)

    def test_a_stop_day_covers_at_the_stop_unless_the_open_is_below_the_target(self):
        rows = [(10, 10, 10, 10), (9.8, 10.6, 9.4, 10.4)]               # reaches both 10.5 and 9.5
        (t,) = run(rows, {'m10': [9.5, 9.5]}, short_targets=('m10',))
        self.assertEqual((t['why'], t['executions'][-1]['price']), ('stop', 10.5))
        rows = [(10, 10, 10, 10), (9.4, 10.6, 9.3, 10.4)]
        (t,) = run(rows, {'m10': [9.5, 9.5]}, short_targets=('m10',))
        self.assertEqual((t['why'], t['executions'][-1]['price']), ('target', 9.4))

    def test_partial_at_the_first_line_rest_at_the_last(self):
        rows = [(10, 10, 10, 10), (9.9, 10.0, 9.4, 9.6), (9.5, 9.6, 8.9, 9.0)]
        (t,) = run(rows, {'m10': [9.5, 9.5, 9.5], 'm20': [9.0, 9.1, 9.1]}, short_targets=('m10', 'm20'),
                   short_target_frac=.5)
        ex = [(e['time'], e['price'], e['action']) for e in t['executions'][1:]]
        self.assertEqual([x[:2] for x in ex], [('2025-01-02', 9.5), ('2025-01-03', 9.1)])
        size0 = t['executions'][0]['shares']
        self.assertAlmostEqual(t['executions'][1]['shares'], size0 / 2)
        self.assertEqual(t['why'], 'target')

    def test_a_line_above_the_fill_is_not_a_target(self):
        rows = [(10, 10, 10, 10), (9.9, 10.0, 9.4, 9.6)]
        (t,) = run(rows, {'m10': [10.2, 10.2]}, short_targets=('m10',))
        self.assertEqual(t['why'], 'end')

    def test_day_partial_covers_at_the_close_of_day_n_when_in_profit(self):
        rows = [(10, 10, 10, 10), (9.9, 10.0, 9.6, 9.7), (9.7, 9.8, 9.3, 9.4), (9.4, 9.5, 9.2, 9.3)]
        (t,) = run(rows, {}, short_trim_day=2, short_trim_day_frac=.5)
        ex = [(e['time'], e['price'], e['action']) for e in t['executions'][1:]]
        self.assertEqual(ex[0], ('2025-01-03', 9.4, 'day_trim'))
        self.assertAlmostEqual(t['executions'][1]['shares'], t['executions'][0]['shares'] / 2)
        self.assertEqual((len(ex), t['why']), (2, 'end'))
        rows = [(10, 10, 10, 10), (10.0, 10.3, 9.9, 10.2), (10.2, 10.4, 10.0, 10.1)]   # not in profit: nothing
        (t,) = run(rows, {}, short_trim_day=2, short_trim_day_frac=.5)
        self.assertEqual([e['action'] for e in t['executions']], ['entry', 'end'])

    def test_longs_ignore_targets(self):
        a = np.array([(10, 10, 10, 10), (10.1, 10.6, 9.6, 10.5)], float)
        p = {'open': a[:, :1], 'high': a[:, 1:2], 'low': a[:, 2:3], 'close': a[:, 3:4],
             'dates': np.array(['2025-01-01', '2025-01-02']), 'codes': np.array(['US.AAA'])}
        e = [[(0, 0, 1, 10.0, 9.0, 'x')], []]
        (t,) = Y.simulate(p, {'m10': np.array([[9.8], [9.8]])}, Y.Rules(**NOCOST, short_targets=('m10',)), e,
                          '2025-01-01', '2025-01-02')[2]
        self.assertEqual(t['why'], 'end')


if __name__ == '__main__':
    unittest.main()
