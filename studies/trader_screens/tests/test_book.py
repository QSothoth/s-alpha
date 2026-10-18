"""Draft accounts: what is bought, when a position exits, and how it is sized."""
import unittest

import numpy as np

from studies.trader_screens import book as B


def bars(rows):
    a = np.array(rows, float)[:, None, :]              # days x 1 stock x (o, h, l, c)
    return a[..., 0], a[..., 1], a[..., 2], a[..., 3]


class ReplayTests(unittest.TestCase):
    def test_gap_and_touch_of_the_stop(self):
        o, h, l, c = bars([(10, 10.5, 9.8, 10), (9.0, 9.2, 8.8, 9.1), (10, 10, 10, 10)])
        r = B.replay(o, h, l, c, None, [[(0, 0, 10.0, 9.5, 'x')], [], []], B.BookRules(), 0, (0, 0))
        self.assertEqual(r['sells'][1][0]['why'], '跳空跌破止损')
        self.assertAlmostEqual(r['sells'][1][0]['price'], 9.0)
        o, h, l, c = bars([(10, 10.5, 9.8, 10), (10, 10.2, 9.4, 9.9)])
        r = B.replay(o, h, l, c, None, [[(0, 0, 10.0, 9.5, 'x')], []], B.BookRules(), 0, (0, 0))
        self.assertEqual((r['sells'][1][0]['why'], r['sells'][1][0]['price']), ('跌破止损', 9.5))

    def test_partial_on_day_three_then_the_trail(self):
        o, h, l, c = bars([(10, 10, 10, 10), (10.5, 11, 10.4, 11), (11, 11.5, 10.9, 11.4),
                           (11.4, 12.1, 11.3, 12), (12, 12, 10.9, 11)])
        trail = np.array([[0], [10], [10.5], [11], [11.5]], float)
        rules = B.BookRules(partial_day=3, partial_frac=1 / 3, trail='x')
        r = B.replay(o, h, l, c, trail, [[(0, 0, 10.0, 9.0, 'x')], [], [], [], []], rules, 0, (0, 0))
        self.assertEqual([s['why'] for s in r['sells'][3]], ['第 3 天分批'])
        self.assertFalse(r['sells'][3][0]['full'])
        self.assertEqual([s['why'] for s in r['sells'][4]], ['收盘跌破跟踪线'])
        self.assertTrue(r['sells'][4][0]['full'])
        self.assertEqual(len(r['trades']), 1)
        self.assertGreater(r['trades'][0]['ret'], 0)

    def test_daily_limit_takes_the_strongest_and_sizes_by_risk(self):
        o = h = l = c = np.full((2, 3), 10.0)
        entries = [[(-.9, 0, 10.0, 9.5, 'a'), (-.99, 1, 10.0, 9.0, 'b'), (-.5, 2, 10.0, 9.0, 'c')], []]
        r = B.replay(o, h, l, c, None, entries, B.BookRules(risk=.01, max_new=2, max_position=.5), 0, (0, 0))
        self.assertEqual([b['j'] for b in r['buys'][0]], [1, 0])
        self.assertAlmostEqual(r['buys'][0][0]['weight'], .10)          # 1% risk / 10% stop
        self.assertAlmostEqual(r['buys'][0][1]['weight'], .20)          # 1% risk / 5% stop
        self.assertEqual(r['skipped'][0], 1)

    def test_stop_is_at_least_one_percent_away(self):
        o = h = l = c = np.full((1, 1), 10.0)
        r = B.replay(o, h, l, c, None, [[(0, 0, 10.0, 9.99, 'x')]], B.BookRules(risk=.005), 0, (0, 0))
        self.assertAlmostEqual(r['buys'][0][0]['stop'], 9.9)
        self.assertAlmostEqual(r['buys'][0][0]['weight'], .30)          # 0.5% / 1% = 50%, capped at 30%

    def test_gate_blocks_or_halves_new_risk(self):
        o = h = l = c = np.full((1, 1), 10.0)
        e = [[(0, 0, 10.0, 9.0, 'x')]]
        r = B.replay(o, h, l, c, None, e, B.BookRules(risk=.01, gate_mode='half'), 0, (0, 0), np.array([False]))
        self.assertAlmostEqual(r['buys'][0][0]['weight'], .05)
        r = B.replay(o, h, l, c, None, e, B.BookRules(risk=.01), 0, (0, 0), np.array([False]))
        self.assertEqual(r['buys'][0], [])


if __name__ == '__main__':
    unittest.main()
