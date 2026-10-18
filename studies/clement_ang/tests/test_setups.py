"""Clement study setups on a synthetic panel: the draft is the board screen; the 10 / 20 EMA pullback triggers on
the break of the pullback day's high."""
import unittest

import numpy as np

from studies.christian_flanders.tests.test_entries import panel
from studies.clement_ang import replicate as R
from studies.trader_screens import screens as S


class SetupTests(unittest.TestCase):
    def test_draft_is_the_board_screen(self):
        rows = [(10 + .02 * i, 10.3 + .02 * i, 9.9 + .02 * i, 10.2 + .02 * i) for i in range(300)]
        A = panel(rows)
        mine = R.STUDY.setups(A, R.DRAFT)['fine'][0]
        st = [x for x in S.ClementAng().run(A['F'])['setups'] if x.kind == 'triggered'][0]
        np.testing.assert_array_equal(mine, st.mask & ~st.skip)
        mine = R.STUDY.setups(A, dict(R.DRAFT, fine=dict(R.FINE)))['fine'][0]     # explicit values: the same
        np.testing.assert_array_equal(mine, st.mask & ~st.skip)

    def test_fine_values_relax(self):
        rows = [(10 + .02 * i, 10.3 + .02 * i, 9.9 + .02 * i, 10.2 + .02 * i) for i in range(300)]
        A = panel(rows)
        a = R.STUDY.setups(A, R.DRAFT)['fine'][0]
        b = R.STUDY.setups(A, dict(R.DRAFT, fine=dict(near=.25, tight=3.0)))['fine'][0]
        self.assertTrue((b >= a).all())

    def test_pullback_breaks_the_prior_high(self):
        rows = [(10 + .05 * i, 10.2 + .05 * i, 9.9 + .05 * i, 10.1 + .05 * i) for i in range(80)]
        c = rows[-1][3]
        rows += [(c - .3, c - .2, c - .9, c - .3)]                  # dips to the 10 EMA, holds the 20
        rows += [(c - .3, c + .2, c - .4, c + .1)]                  # breaks that day's high
        A = panel(rows)
        cfg = dict(R.DRAFT, setups=['pb'], pool=dict(turnover=1e6, adr=0.0, above50=False))
        m, level, stop = R.STUDY.setups(A, cfg)['pb']
        T = len(rows) - 1
        self.assertTrue(m[T, 0])
        self.assertAlmostEqual(level[T, 0], c - .2)


if __name__ == '__main__':
    unittest.main()
