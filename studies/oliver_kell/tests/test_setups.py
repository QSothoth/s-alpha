"""Oliver Kell study setups on a synthetic panel: the draft is the board screen; the Wedge Pop fills at the close
under both entry modes; risk is halved the day after the pool index closed below its 20 EMA."""
import unittest

import numpy as np

from studies.christian_flanders.tests.test_entries import panel
from studies.oliver_kell import replicate as R
from studies.trader_screens import screens as S


def pop_rows():
    rows = [(10 + .03 * i, 10.2 + .03 * i, 9.9 + .03 * i, 10.1 + .03 * i) for i in range(60)]
    c = rows[-1][3]
    rows += [(c - .05 * k, c - .05 * k + .1, c - .05 * k - .1, c - .05 * k - .02) for k in range(1, 9)]
    c = rows[-1][3]
    rows += [(c, c + .6, c - .05, c + .55)]                          # closes back above the 10 / 20 EMA
    return rows


class SetupTests(unittest.TestCase):
    def test_draft_is_the_board_screen(self):
        A = panel(pop_rows())
        mine = R.STUDY.setups(A, R.DRAFT)
        st = S.OliverKell().run(A['F'])['setups']
        np.testing.assert_array_equal(mine['pop'][0], st[0].mask)
        np.testing.assert_array_equal(mine['cross'][0], st[2].mask)

    def test_pop_fills_at_the_close(self):
        rows = pop_rows()
        A = panel(rows)
        cfg = dict(R.DRAFT, setups=['pop'])
        T = len(rows) - 1
        m = np.zeros(A['close'].shape, bool)
        m[T, 0] = True
        masks = {'pop': (m, np.full(m.shape, rows[-1][3] - .3), A['low'])}
        for mode in ('level', 'close'):
            (e,) = [x for x in R.STUDY.entries(A, dict(cfg, entry=mode), masks)[T] if x[1] == 0]
            self.assertAlmostEqual(e[3], rows[-1][3])
            self.assertAlmostEqual(e[4], rows[-1][2])

    def test_risk_halves_after_the_index_closed_below(self):
        rows = [(10 + .1 * i, 10.2 + .1 * i, 9.8 + .1 * i, 10 + .1 * i) for i in range(40)] + [(9, 9.1, 8, 8)] * 3
        A = panel(rows)
        s = R.STUDY.named(A, None, 'idxhalf20')
        self.assertEqual(s[40], 1.0)                                 # the day of the drop: yesterday was above
        self.assertEqual(s[41], .5)

    def test_double_inside_breaks_the_mother_bar(self):
        rows = [(10 + .03 * i, 10.2 + .03 * i, 9.9 + .03 * i, 10.1 + .03 * i) for i in range(60)]
        c = rows[-1][3]
        rows += [(c, c + .5, c - .5, c), (c, c + .3, c - .3, c), (c, c + .2, c - .2, c),   # mother, inside, inside
                 (c, c + .7, c - .1, c + .6)]                                               # breaks the mother high
        A = panel(rows)
        cfg = dict(R.DRAFT, setups=['ib2'], pool=dict(turnover=1e6, adr=0.0))
        m, level, _ = R.STUDY.setups(A, cfg)['ib2']
        T = len(rows) - 1
        self.assertTrue(m[T, 0])
        self.assertFalse(m[T - 1, 0])
        self.assertAlmostEqual(level[T, 0], c + .5)

    def test_undercut_and_rally(self):
        rows = [(10 + .05 * i, 10.2 + .05 * i, 9.9 + .05 * i, 10.1 + .05 * i) for i in range(80)]
        c = rows[-1][3]
        rows += [(c - .6, c - .5, c - 1.2, c - 1.1), (c - 1.0, c + .1, c - 1.1, c)]   # closes below, then back above
        A = panel(rows)
        m = R.STUDY.setups(A, dict(R.DRAFT, setups=['ur'], pool=dict(turnover=1e6, adr=0.0)))['ur'][0]
        self.assertTrue(m[-1, 0])
        self.assertFalse(m[-2, 0])

    def test_exit_signals(self):
        rows = [(10, 10.2, 9.8, 10)] * 15 + [(13.5, 13.6, 13.4, 13.5), (9, 9.1, 8.9, 9)]
        A = panel(rows)
        ext = R.STUDY.named(A, None, 'ext10_30')
        below = R.STUDY.named(A, None, 'below_ema10')
        self.assertTrue(ext[15, 0])                                  # 13.5 vs a 10-day line near 10.35
        self.assertFalse(ext[14, 0])
        self.assertTrue(below[16, 0])
        self.assertFalse(below[14, 0])


if __name__ == '__main__':
    unittest.main()
