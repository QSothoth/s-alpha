import unittest

import numpy as np

from studies.trader_replication.system import Rules, simulate

from studies.trader_replication.martin_continue_hd import at_open_proxy


class GapPriceProxyTest(unittest.TestCase):
    def test_only_post_entry_gap_exit_price_changes(self):
        gap = ((1., 0), 0, 1, 8., 9., 'n1', 7., None, None, .5, None, True)
        normal = ((2., 1), 1, 1, 10., 9., 'list', 9., None, None, .5, None, True)
        nofill = ((3., 2), 2, 1, float('nan'), 9., 'list', None)
        book = [[gap, normal, nofill], []]
        out, changed = at_open_proxy(book)
        self.assertEqual(changed, [(0, 0, 'n1')])
        self.assertEqual(out[0][0][6], 8.)
        self.assertEqual(out[0][0][:6], gap[:6])
        self.assertEqual(out[0][0][7:], gap[7:])
        self.assertEqual(out[0][1], normal)
        self.assertEqual(book[0][0][6], 7.)


    def test_gap_proxy_changes_only_post_entry_exit_on_same_frozen_plan(self):
        days = np.array(['2025-01-02', '2025-01-03'])
        op = np.array([[10.], [8.]])
        px = {'dates': days, 'codes': np.array(['US.A']), 'open': op,
              'high': np.array([[10.], [8.]]), 'low': np.array([[10.], [7.5]]), 'close': op}
        rules = Rules(trail='', trims=(), risk=.01, max_position=1., max_gross=1., gross_cost=True,
                      intraday_kinds=('n1',), buy_cost=0., sell_cost=0., margin_rate=0.)
        original = [[], [((1., 0), 0, 1, 8., 9., 'n1', 7.5)]]
        ideal, _ = at_open_proxy(original)
        outputs = []
        for book in (original, ideal):
            track = {}
            curve, _, trades = simulate(px, {}, rules, book, days[1], days[-1], audit=True, track=track, preopen=True)
            outputs.append((curve, trades, track))
        left, right = outputs
        self.assertEqual(left[2]['preopen_plans'][0]['orders'][0]['shares'],
                         right[2]['preopen_plans'][0]['orders'][0]['shares'])
        self.assertEqual(left[1][0]['fill'], right[1][0]['fill'])
        self.assertEqual((left[1][0]['executions'][-1]['price'], right[1][0]['executions'][-1]['price']),
                         (7.5, 8.))
        self.assertLess(left[0][-1], right[0][-1])


if __name__ == '__main__':
    unittest.main()
