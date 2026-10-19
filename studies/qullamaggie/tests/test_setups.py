"""Qullamaggie study setups on a synthetic panel: the draft is the board screen; the stop-width rule is applied to
the actual fill (the close under the corrected entry)."""
import unittest

import numpy as np

from studies.christian_flanders.tests.test_entries import panel, BASE
from studies.qullamaggie import replicate as R
from studies.trader_screens import screens as S


class SetupTests(unittest.TestCase):
    def test_draft_is_the_board_screen(self):
        rows = [(10 + .02 * i, 10.3 + .02 * i, 9.9 + .02 * i, 10.2 + .02 * i) for i in range(300)]
        A = panel(rows)
        mine = R.STUDY.setups(A, R.DRAFT)
        st = S.Qullamaggie().run(A['F'])['setups']
        np.testing.assert_array_equal(mine['brk'][0], [s for s in st if s.kind == 'triggered'][0].mask)
        np.testing.assert_array_equal(mine['ep'][0], [s for s in st if s.name == 'EP'][0].mask)

    def test_ep_values_default_to_the_board(self):
        A = self.ep_rows((10.9, 11.5, 10.8, 11.2))
        A['F'].v[-1] = 5e6
        a = R.STUDY.setups(A, R.DRAFT)['ep'][0]
        b = R.STUDY.setups(A, dict(R.DRAFT, ep={'min_gap': .10, 'liquid': 20e6, 'heavy': 3.0}))['ep'][0]
        np.testing.assert_array_equal(a, b)
        self.assertFalse(a[-1, 0])                                   # a 9% gap is below the board's 10%
        c = R.STUDY.setups(A, dict(R.DRAFT, ep={'min_gap': .08}))['ep'][0]
        self.assertTrue(c[-1, 0])

    def ep_rows(self, last):
        rows = [list(r) for r in BASE]
        return panel([tuple(r) for r in rows] + [last])

    def test_close_entry_uses_the_day_low_and_the_ep_cap(self):
        A = self.ep_rows((11.2, 11.9, 11.0, 11.5))
        A['F'].v[-1] = A['F'].volume[-1] = 5e6                         # 5x volume: an EP day
        cfg = dict(R.DRAFT, setups=['ep'], entry='close', stop_adr={'ep': 100.0})
        (e,) = [x for x in R.STUDY.entries(A, cfg, R.STUDY.setups(A, cfg))[30] if x[1] == 0]
        self.assertEqual((e[3], e[4], e[5]), (11.5, 11.0, 'ep'))
        cfg = dict(cfg, stop_adr={'ep': 1.5})                         # ADR ~4%: a 4.3% stop is within 1.5 ADR
        self.assertEqual(len([x for x in R.STUDY.entries(A, cfg, R.STUDY.setups(A, cfg))[30] if x[1] == 0]), 1)
        cfg = dict(cfg, stop_adr={'ep': 1.0})
        self.assertEqual(len([x for x in R.STUDY.entries(A, cfg, R.STUDY.setups(A, cfg))[30] if x[1] == 0]), 0)

    def test_green_light_needs_both_lines_rising_the_day_before(self):
        rows = [(10 + .1 * i, 10.2 + .1 * i, 9.8 + .1 * i, 10 + .1 * i) for i in range(40)] + [(9, 9.1, 8, 8)] * 3
        A = panel(rows)
        ok = R.STUDY.market_ok(A, dict(R.DRAFT, filter='light'))
        self.assertFalse(ok[20])                                   # the 20-day line is not there yet
        self.assertTrue(ok[40])                                    # yesterday: rising lines, 10 above 20
        self.assertFalse(ok[42])                                   # the 10-day line turned down
        q = R.STUDY.market_ok(A, dict(R.DRAFT, filter='light_q'))     # name 0 carries the turnover-weighted
        self.assertTrue(q[40])                                       # index too (equal turnover here)
        self.assertFalse(q[42])
        s = R.STUDY.named(A, None, 'lighthalf')
        self.assertEqual((s[40], s[42]), (1.0, .5))


if __name__ == '__main__':
    unittest.main()
