import unittest
import numpy as np
from studies.trader_replication import martin_continue_fe as fe


class RandomBookTests(unittest.TestCase):
    def test_preselection_is_unique_and_preserves_prior_stop_ratios(self):
        days = ['2023-12-29', '2024-01-02', '2024-01-03']
        close = np.array([[10., 20., 30.], [11., 21., 31.], [12., 22., 32.]])
        pool = np.array([[True, True, False], [True, True, True], [True, True, True]])
        reg = [[(0, 0, 1, 10., 9.5, 'n1'), (1, 1, 1, 20., 18., 'n1')], [], []]
        rows, outside = fe.eligible_rows(reg, pool, close, days)
        book, shortages, choices = fe.random_book(rows, close, 3, np.random.default_rng(2))
        self.assertEqual(outside, 0)
        self.assertEqual(shortages, [])
        self.assertEqual(len(set(choices[0][1])), 2)
        self.assertEqual({e[1] for e in book[0]}, {0, 1})
        np.testing.assert_allclose([e[4] / e[3] for e in book[0]], [.95, .9])
        altered = close.copy()
        altered[1:] *= 100
        book2, _, _ = fe.random_book(rows, altered, 3, np.random.default_rng(2))
        self.assertEqual(book[0], book2[0])

    def test_precision_unknown_is_recorded_and_excluded(self):
        opening = float(np.float32(3.96))
        stop = opening - 1e-9
        book = [[], [(0, 0, 1, opening, stop, 'n1')]]
        clean, unknown = fe.remove_precision_unknown(book, ['a', 'b'], ['US.A'])
        self.assertEqual(clean, [[], []])
        self.assertEqual(unknown[0][:2], ['b', 'US.A'])


if __name__ == '__main__':
    unittest.main()
