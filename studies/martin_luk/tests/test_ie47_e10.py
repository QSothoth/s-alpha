"""E10 entry layers derived from E6c's close breaks (retest limit, next open, setup filter, re-entry); before the code."""
import unittest

import numpy as np

from studies.martin_luk import ie47_e1 as M
from studies.martin_luk.tests.test_ie47_e1 import arrays


def base(a):
    return M.entry_book(a, {str(a['days'][0]): ['SYN_00']}, **M.E6['E6c'])


# night 0 picked; day 1 inside the previous range; day 2 closes 104 above the previous high 101 (low 99): break
ROWS = [(100, 102, 98, 100), (100, 101, 99, 100), (100, 105, 99, 104)]


class RetestTests(unittest.TestCase):
    def book(self, tail, adr=20):
        a = arrays(ROWS + tail, adr=adr)
        return a, M.derived_book(a, base(a), 'retest')

    def test_limit_at_the_broken_high_fills_at_the_level(self):
        a, (book, _, events) = self.book([(103, 104, 100.5, 102)])
        (pr, j, side, fill, stop, kind, day_exit), = book[3]
        self.assertEqual((pr[1], j, side, kind, day_exit), (0, 0, 1, M.RETEST_KIND, None))
        self.assertEqual(fill, 101.)
        self.assertAlmostEqual(stop, 99.)          # breakout-day low, inside the 5% cap
        self.assertEqual(sum(map(len, book)), 1)
        self.assertIn('filled', [e['why'] for e in events])

    def test_open_below_the_level_fills_at_the_open_and_gap_below_stop_cancels(self):
        _, (book, _, _) = self.book([(100.2, 103, 100, 102)])
        self.assertEqual(book[3][0][3], 100.2)
        _, (book, _, events) = self.book([(98.5, 103, 98, 102)])
        self.assertEqual(sum(map(len, book)), 0)
        self.assertIn('cancel_gap', [e['why'] for e in events])

    def test_same_day_stop_is_declared_and_expiry_after_three_days(self):
        _, (book, _, _) = self.book([(103, 104, 98.5, 99)])
        self.assertEqual(book[3][0][6], 99.)
        _, (book, _, events) = self.book([(105, 106, 102, 105)] * 3 + [(103, 104, 100, 102)])
        self.assertEqual(sum(map(len, book)), 0)
        self.assertIn('expired', [e['why'] for e in events])

    def test_stop_never_reads_the_fill_days_low_and_is_capped(self):
        a, (book, _, _) = self.book([(103, 104, 100.5, 102)], adr=3)    # 1.98% wide, cap 1.5%
        self.assertAlmostEqual(book[3][0][4], 101*.985)
        b = arrays(ROWS + [(103, 104, 100.9, 102)], adr=20)
        b['low'][3, 0] = 100.95
        self.assertEqual(M.derived_book(b, base(b), 'retest')[0][3][0][4], 99.)

    def test_no_break_no_order(self):
        a = arrays(ROWS[:2] + [(100, 101, 99, 100.5), (100, 101, 99, 100)], adr=20)
        self.assertEqual(sum(map(len, M.derived_book(a, base(a), 'retest')[0])), 0)


class NextOpenTests(unittest.TestCase):
    def test_buys_the_next_open_above_the_broken_high(self):
        a = arrays(ROWS + [(104.0, 106, 103, 105)], adr=20)
        (pr, j, side, fill, stop, kind, day_exit), = M.derived_book(a, base(a), 'next_open')[0][3]
        self.assertEqual((fill, kind, day_exit), (104.0, M.OPEN_KIND, None))
        self.assertAlmostEqual(stop, 99.)          # breakout low 99 is 4.8% away: inside the 5% cap
        a = arrays(ROWS + [(104.0, 106, 103, 105)], adr=8)
        self.assertAlmostEqual(M.derived_book(a, base(a), 'next_open')[0][3][0][4], 104*.96)   # cap ADR/2 = 4%

    def test_open_not_above_the_broken_high_is_skipped_and_same_day_stop_declared(self):
        a = arrays(ROWS + [(100.5, 106, 100, 105)], adr=20)
        self.assertEqual(sum(map(len, M.derived_book(a, base(a), 'next_open')[0])), 0)
        a = arrays(ROWS + [(104.0, 106, 98.5, 100)], adr=20)
        self.assertAlmostEqual(M.derived_book(a, base(a), 'next_open')[0][3][0][6], 99.)


    def test_open_more_than_three_percent_above_the_broken_high_is_not_chased(self):
        a = arrays(ROWS + [(104.1, 106, 103, 105)], adr=20)          # 101 * 1.03 = 104.03
        book, _, events = M.derived_book(a, base(a), 'next_open')
        self.assertEqual(sum(map(len, book)), 0)
        self.assertIn('chase', [e['why'] for e in events])
        a = arrays(ROWS + [(104.0, 106, 103, 105)], adr=20)
        self.assertEqual(sum(map(len, M.derived_book(a, base(a), 'next_open')[0])), 1)


class SetupTests(unittest.TestCase):
    def test_only_breaks_after_an_inside_or_narrow_day_and_others_keep_watching(self):
        a = arrays(ROWS, adr=20)
        self.assertEqual([len(x) for x in M.entry_book(a, {str(a['days'][0]): ['SYN_00']}, **M.E6['E6c'],
                                                      setup=True)[0]], [0, 0, 1])
        # day 1 is wider than day 0 and not narrow (ADR 2): the day-2 break waits; day 3 is inside day 2, day 4 breaks
        b = arrays([(100, 101, 99, 100), (100, 103, 97, 100), (100, 105, 99, 104), (104, 104.5, 103, 104.4),
                    (104.4, 106, 104, 105.5)], adr=2)
        book = M.entry_book(b, {str(b['days'][0]): ['SYN_00']}, **M.E6['E6c'], setup=True)[0]
        self.assertEqual([len(x) for x in book], [0, 0, 0, 0, 1])


class ReentryTests(unittest.TestCase):
    def test_stopped_then_closes_back_above_the_fill_rebuys_once(self):
        a = arrays(ROWS + [(103, 103, 98, 100), (100, 103, 99.5, 103), (103, 106, 102, 105.5),
                           (105, 107, 104, 106)], adr=20)
        e9 = np.full_like(a['close'], 50.)
        book = M.reentry_book(a, base(a)[0], e9)
        self.assertEqual([d for d, row in enumerate(book) if row], [2, 5])
        (pr, j, side, fill, stop, kind, day_exit) = book[5][0]
        self.assertEqual((fill, kind, day_exit), (105.5, M.RE_KIND, None))
        self.assertAlmostEqual(stop, 102.)

    def test_reaching_three_r_before_the_stop_is_not_a_clean_stop(self):
        # fill 104, stop 99: 3R = 119; day 3 high 120 first, then stopped, then back above the fill
        a = arrays(ROWS + [(104, 120, 103, 110), (105, 106, 98, 100), (100, 106, 99.5, 105.5)], adr=20)
        e9 = np.full_like(a['close'], 50.)
        self.assertEqual([d for d, row in enumerate(M.reentry_book(a, base(a)[0], e9)) if row], [2])

    def test_retest_fill_events_carry_the_days_after_the_break(self):
        a = arrays(ROWS + [(105, 106, 102, 105), (103, 104, 100.5, 102)], adr=20)
        _, _, events = M.derived_book(a, base(a), 'retest')
        self.assertEqual([(e['why'], e.get('after')) for e in events], [('filled', 2)])

    def test_trail_exit_first_means_no_reentry(self):
        a = arrays(ROWS + [(103, 103, 100, 101), (101, 101, 98, 100), (100, 106, 99.5, 105.5)], adr=20)
        e9 = np.full_like(a['close'], 50.)
        e9[3] = 102.                                 # day 3 closes below the 9 EMA before any stop
        self.assertEqual([d for d, row in enumerate(M.reentry_book(a, base(a)[0], e9)) if row], [2])


if __name__ == '__main__':
    unittest.main()
