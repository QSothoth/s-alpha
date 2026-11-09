"""E11 RE2: a re-buy that is itself cleanly stopped may be re-bought once more; at most two per signal. Before the code."""
import unittest

import numpy as np

from studies.martin_luk import e11_research as E11, ie47_e1 as M
from studies.martin_luk.tests.test_ie47_e1 import arrays
from studies.martin_luk.tests.test_ie47_e10 import ROWS, base

# fill 104 stop 99 on day 2; stopped day 3; re-bought day 5 at 105.5 (stop 102); stopped day 6;
# day 7 closes 106 above 105.5: second re-buy (stop = day 7 low 102.5); stopped day 8; day 9 back above 106
TAIL = [(103, 103, 98, 100), (100, 103, 99.5, 103), (103, 106, 102, 105.5),
        (105, 106, 101, 103), (103, 107, 102.5, 106), (106, 106, 102, 103), (103, 108, 102.6, 107)]


class ChainedReentryTests(unittest.TestCase):
    def book(self, rounds):
        a = arrays(ROWS + TAIL, adr=20)
        return E11.reentry_rounds(a, base(a)[0], np.full_like(a['close'], 50.), rounds)

    def test_one_round_matches_e10(self):
        a = arrays(ROWS + TAIL, adr=20)
        e9 = np.full_like(a['close'], 50.)
        self.assertEqual(E11.reentry_rounds(a, base(a)[0], e9, 1), M.reentry_book(a, base(a)[0], e9))

    def test_second_rebuy_after_the_first_rebuy_is_stopped(self):
        book = self.book(2)
        self.assertEqual([d for d, row in enumerate(book) if row], [2, 5, 7])
        (pr, j, side, fill, stop, kind, day_exit), = book[7]
        self.assertEqual((fill, kind, day_exit), (106., E11.RE2_KIND, None))
        self.assertAlmostEqual(stop, 102.5)
        self.assertEqual(book[5][0][5], M.RE_KIND)

    def test_no_third_rebuy(self):
        self.assertFalse(self.book(2)[9])


if __name__ == '__main__':
    unittest.main()
