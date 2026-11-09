import unittest
import numpy as np
from studies.trader_replication import martin_continue_fg as fg


class SetupRandomizationTests(unittest.TestCase):
    def test_random_order_selects_only_the_same_setups_and_keeps_their_stops(self):
        days = ['2023-12-29', '2024-01-02']
        candidates = [(1, 0, 1, 10., 9.5, 'n1'), (2, 1, 1, 20., 19., 'n1'),
                      (3, 2, 1, 30., 27., 'n1')]
        reg = [[((1., 0, 1),) + candidates[0][1:], ((1., 0, 2),) + candidates[1][1:]], []]
        rows = fg.candidate_rows(reg, [candidates, []], [candidates[:2], []], days)
        book, choices = fg.random_book(rows, 2, np.random.default_rng(3))
        self.assertEqual(len(book[0]), 2)
        self.assertEqual(len(set(choices[0][1])), 2)
        original = {e[1]: e[1:6] for e in candidates}
        for order in book[0]:
            self.assertEqual(order[1:6], original[order[1]])
        self.assertEqual([e[0][-1] for e in book[0]], [0, 1])

    def test_candidate_mismatch_stops_the_replay(self):
        days = ['2023-12-29', '2024-01-02']
        reg = [[(0, 0, 1, 10., 9.5, 'n1')], []]
        with self.assertRaises(AssertionError):
            fg.candidate_rows(reg, [[], []], [[], []], days)


if __name__ == '__main__':
    unittest.main()
