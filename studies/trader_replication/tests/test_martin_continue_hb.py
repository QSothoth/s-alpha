import copy
import unittest

import numpy as np

from studies.trader_replication.martin_continue_hb import freeze_orders, observe


class PreopenOrderTest(unittest.TestCase):
    def test_future_rows_and_prices_do_not_change_prior_frozen_orders(self):
        days = ['2025-01-02', '2025-01-03', '2025-01-06']
        codes = [f'US.{i}' for i in range(8)]
        close = np.full((3, 8), 10.)
        core = ((1., 0.), 0, 1, 10., 9., 'n1')
        trials = [((2., float(i)), i, 1, 10., 9., 'list', None, None, None, .5) for i in range(7)]
        book = [[core, *reversed(trials)], [], []]
        expected = freeze_orders(days, codes, book, close)
        changed_close, changed_book = close.copy(), copy.deepcopy(book)
        changed_close[1:] = 999.
        changed_book[1:] = [[((2., 0.), 7, 1, 999., 900., 'list')], []]
        got = freeze_orders(days, codes, changed_book, changed_close)
        prior = lambda rows: [r for r in rows if r['signal_day'] == days[0]]
        self.assertEqual(prior(expected), prior(got))
        self.assertEqual(len(prior(expected)), 7)
        self.assertEqual([r['code'] for r in prior(expected) if r['kind'] == 'list'],
                         [f'US.{i}' for i in range(6)])
        self.assertEqual(sum(r['code'] == 'US.0' for r in prior(expected)), 2)

    def test_missing_cancelled_and_precision_are_observations_only(self):
        order = {'kind': 'n1', 'stop': 10.}
        original = dict(order)
        self.assertEqual(observe(order, float('nan'), 9.)['status'], 'missing')
        same = observe(order, 10., 9.)
        self.assertEqual(same['status'], 'open_at_or_below_stop')
        self.assertTrue(same['open_stop_float32_equal'])
        self.assertTrue(observe(order, 11., 10.)['low_stop_float32_equal'])
        self.assertEqual(order, original)


if __name__ == '__main__':
    unittest.main()
