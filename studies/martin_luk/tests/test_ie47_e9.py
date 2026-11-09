"""E9 diagnostic arms: random names from the night's pool and a random close inside the watch; written before the code."""
import unittest

import numpy as np

from studies.martin_luk import ie47_e1 as M
from studies.martin_luk.tests.test_ie47_e1 import arrays


class Fixed:
    """An rng stub whose integers() always returns one offset."""
    def __init__(self, k):
        self.k = k

    def integers(self, lo, hi):
        assert lo <= self.k < hi
        return self.k


class RandomPicksTests(unittest.TestCase):
    def test_same_count_from_that_nights_pool_without_replacement(self):
        days = np.array([f'2025-01-{i+2:02d}' for i in range(3)])
        codes = np.array([f'SYN_{j:02}' for j in range(6)])
        pool = np.zeros((3, 6), bool)
        pool[0, [1, 2, 3]] = True
        pool[1, [4, 5]] = True
        picks = {days[0]: ['SYN_00', 'SYN_05'], days[1]: ['SYN_00', 'SYN_01', 'SYN_02']}
        for seed in range(20):
            out = M.random_picks(picks, pool, days, codes, np.random.default_rng(seed))
            self.assertEqual(set(out), set(picks))
            self.assertEqual(len(out[days[0]]), 2)
            self.assertEqual(len(set(out[days[0]])), 2)
            self.assertLessEqual(set(out[days[0]]), {'SYN_01', 'SYN_02', 'SYN_03'})
            self.assertEqual(sorted(out[days[1]]), ['SYN_04', 'SYN_05'])  # only two in the pool
        a = M.random_picks(picks, pool, days, codes, np.random.default_rng(1))
        self.assertEqual(a, M.random_picks(picks, pool, days, codes, np.random.default_rng(1)))


class RandomDayBookTests(unittest.TestCase):
    # never closes above the previous high: entry_book never triggers
    ROWS = [(100, 102, 98, 100), (100, 101, 97, 99), (99, 100, 96, 98), (98, 99, 95, 97),
            (97, 98, 94, 96), (96, 97, 93, 95), (95, 96, 92, 94)]

    def test_buys_the_drawn_close_without_a_break(self):
        a = arrays(self.ROWS, adr=20)
        picks = {str(a['days'][0]): ['SYN_00']}
        self.assertEqual(sum(map(len, M.entry_book(a, picks, **M.E6['E6c'])[0])), 0)
        for k in range(1, 6):
            book, mask, _ = M.random_day_book(a, picks, Fixed(k))
            self.assertEqual([d for d, row in enumerate(book) if row], [k])
            (_, j, side, fill, stop, kind, day_exit), = book[k]
            self.assertEqual((j, side, fill, kind, day_exit), (0, 1, a['close'][k, 0], M.CLOSE_KIND, None))
            self.assertAlmostEqual(stop, a['low'][k, 0])
            self.assertTrue(mask[k, 0])

    def test_offsets_cover_the_whole_watch(self):
        a = arrays(self.ROWS, adr=20)
        picks = {str(a['days'][0]): ['SYN_00']}
        seen = {next(d for d, row in enumerate(M.random_day_book(a, picks, np.random.default_rng(s))[0]) if row)
                for s in range(200)}
        self.assertEqual(seen, {1, 2, 3, 4, 5})

    def test_same_tuple_as_entry_book_on_a_break_day_including_the_cap(self):
        rows = [(99, 100, 98, 99), (95, 105, 90, 104), (104, 105, 103, 104)]
        for adr in (20, 4, 1):
            a = arrays(rows, adr=adr)
            picks = {str(a['days'][0]): ['SYN_00']}
            want = M.entry_book(a, picks, **M.E6['E6c'])
            got = M.random_day_book(a, picks, Fixed(1))
            self.assertEqual(want[0], got[0])
            self.assertEqual([e['why'] for e in want[2]], [e['why'] for e in got[2]])

    def test_keep_restricts_watches_and_a_repick_restarts(self):
        a = arrays(self.ROWS, adr=20)
        d = list(map(str, a['days']))
        picks = {d[0]: ['SYN_00'], d[1]: ['SYN_00']}
        # re-picked on night 1: the night-0 watch (day 2) is dropped, night 1 + 2 -> day 3
        book = M.random_day_book(a, picks, Fixed(2))[0]
        self.assertEqual([i for i, row in enumerate(book) if row], [3])
        self.assertEqual(book[3][0][0][1], 1)
        book = M.random_day_book(a, picks, Fixed(2), keep={(d[0], 'SYN_00')})[0]
        self.assertEqual(sum(map(len, book)), 0)   # night 0 kept but replaced; night 1 not kept
        book = M.random_day_book(a, {d[0]: ['SYN_00']}, Fixed(2), keep={(d[0], 'SYN_00')})[0]
        self.assertEqual([i for i, row in enumerate(book) if row], [2])
        book = M.random_day_book(a, {d[0]: ['SYN_00']}, Fixed(2), keep=set())[0]
        self.assertEqual(sum(map(len, book)), 0)

    def test_invalid_drawn_bar_consumes_the_watch(self):
        a = arrays(self.ROWS, adr=20)
        a['close'][2, 0] = np.nan
        book, _, events = M.random_day_book(a, {str(a['days'][0]): ['SYN_00']}, Fixed(2))
        self.assertEqual(sum(map(len, book)), 0)
        self.assertIn('invalid_bar', [e['why'] for e in events])

    def test_triggered_watches_are_keyed_by_observed_night(self):
        rows = [(99, 100, 98, 99), (99, 100, 98, 99.5), (95, 105, 90, 104)]
        a = arrays(rows, adr=20)
        _, _, events = M.entry_book(a, {str(a['days'][0]): ['SYN_00']}, **M.E6['E6c'])
        self.assertEqual(M.triggered_watches(events), {(str(a['days'][0]), 'SYN_00')})


if __name__ == '__main__':
    unittest.main()
