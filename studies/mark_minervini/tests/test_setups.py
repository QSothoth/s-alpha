"""Mark Minervini study setups on a synthetic panel: the draft is the board screen; the corrected entry buys the
close with the day's low as stop, and stop 'base' puts back the base low (at most 8% below)."""
import unittest

import numpy as np

from studies.christian_flanders.tests.test_entries import panel
from studies.mark_minervini import replicate as R
from studies.trader_screens import screens as S


class SetupTests(unittest.TestCase):
    def test_draft_is_the_board_screen(self):
        rows = [(10 + .02 * i, 10.3 + .02 * i, 9.9 + .02 * i, 10.2 + .02 * i) for i in range(300)]
        A = panel(rows)
        mine = R.STUDY.setups(A, R.DRAFT)['vcp_mm']
        st = [x for x in S.MarkMinervini().run(A['F'])['setups'] if x.kind == 'triggered'][0]
        np.testing.assert_array_equal(mine[0], st.mask)

    def test_close_entry_stops(self):
        rows = [(10, 10.2, 9.8, 10)] * 30 + [(10, 10.6, 9.95, 10.5)]
        A = panel(rows)
        m = np.zeros(A['close'].shape, bool)
        m[30, 0] = True
        masks = {'vcp_mm': (m, np.full(m.shape, 10.2), A['low'])}
        cfg = dict(R.DRAFT, entry='close', stop='day')
        (e,) = R.STUDY.entries(A, cfg, masks)[30]
        self.assertEqual((e[3], e[4]), (10.5, 9.95))
        (e,) = R.STUDY.entries(A, dict(cfg, stop='base'), masks)[30]
        self.assertAlmostEqual(e[4], 9.8)                           # the 10-day low before the day


if __name__ == '__main__':
    unittest.main()
