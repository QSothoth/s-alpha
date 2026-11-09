import unittest

import numpy as np

from studies.trader_replication.martin_continue_dg import next_open


class NextOpenTest(unittest.TestCase):
    def test_prior_close_candidates_keep_priority_and_low_only_sets_stop(self):
        a = ((1, 3), 0, 1, 10., 9., 'core')
        b = ((1, 4), 1, 1, 10., 8., 'core')
        rows = [[a, b], [], []]
        days = ['2024-01-02', '2024-01-03', '2024-01-04']
        opens = np.array([[10., 10.], [10.2, 10.3], [10., 10.]])
        lows = np.array([[9., 9.], [8.8, 9.], [9., 9.]])
        book, count = next_open(rows, opens, lows, days)
        self.assertEqual([e[0] for e in book[1]], [a[0], b[0]])
        self.assertEqual([e[6] for e in book[1]], [9., None])
        self.assertEqual(count['2024:day_stop'], 1)
        lows[1] = [9.5, 7.5]
        modified, _ = next_open(rows, opens, lows, days)
        self.assertEqual([e[:6] for e in book[1]], [e[:6] for e in modified[1]])
        self.assertEqual([e[6] for e in modified[1]], [None, 8.])

    def test_gap_below_stop_and_missing_low_cancel(self):
        rows = [[(0, 0, 1, 10., 9., 'core'), (1, 1, 1, 10., 8., 'core')], []]
        opens = np.array([[10., 10.], [8., 10.]])
        lows = np.array([[9., 9.], [7., np.nan]])
        with self.assertRaisesRegex(ValueError, 'missing intraday low'):
            next_open(rows, opens, lows, ['2024-01-02', '2024-01-03'])
        opens[1, 1] = np.nan
        book, count = next_open(rows, opens, lows, ['2024-01-02', '2024-01-03'])
        self.assertEqual(book[1], [])
        self.assertEqual(count['2024:open_below_stop'], 1)
        self.assertEqual(count['2024:missing_open'], 1)


if __name__ == '__main__':
    unittest.main()
