"""Sean Ryan's short points on a synthetic panel: the fake-out is shorted at the close that falls back under the
breakout's pivot, with the stop at the high since the breakout; the breakdown at the close under a tight base after
a sharp drop; neither reads later bars."""
import unittest

import numpy as np

from studies.christian_flanders.tests.test_entries import panel
from studies.sean_ryan import replicate as R
from studies.sean_ryan.tests.test_setups import wave_panel, wave_rows

SC = dict(turnover=1e6)


class ShortTests(unittest.TestCase):
    def test_fake_out(self):
        rows = wave_rows() + [(15.8, 16.2, 15.2, 15.3)]        # the day after the break: red, back under 15.6
        A = wave_panel(rows)
        m, _ = R.STUDY.short_setups(A, dict(SC, setups=['fake']))
        T = len(rows) - 1
        self.assertTrue(m['fake']['armed'][T, 0])
        self.assertFalse(m['fake']['armed'][T - 1, 0])          # the breakout day itself
        self.assertAlmostEqual(m['fake']['stop'][T, 0], 16.2)  # the high since the breakout
        later = wave_panel(rows + [(30, 40, 1, 2)] * 3)
        np.testing.assert_array_equal(R.STUDY.short_setups(later, dict(SC, setups=['fake']))[0]['fake']['armed'][:T + 1],
                                      m['fake']['armed'])

    def test_no_fake_out_when_it_holds(self):
        rows = wave_rows() + [(15.9, 16.4, 15.7, 16.3)]
        m, _ = R.STUDY.short_setups(wave_panel(rows), dict(SC, setups=['fake']))
        self.assertFalse(m['fake']['armed'][-1, 0])

    def test_breakdown(self):
        rows = [(16, 16.1, 15.9, 16)] * 60
        p = 16.0
        for _ in range(8):                                       # a sharp drop to ~9.6
            rows.append((p, p * 1.01, p * .93, p * .94))
            p *= .94
        rows += [(p * 1.02, p * 1.04, p * 1.0, p * 1.02)] * 10   # a tight, weak base
        rows.append((p * 1.01, p * 1.02, p * .95, p * .96))      # closes under the base low
        A = panel(rows)
        m, _ = R.STUDY.short_setups(A, dict(SC, setups=['brk']))
        self.assertTrue(m['brk'][-1, 0])
        self.assertFalse(m['brk'][-2, 0])


if __name__ == '__main__':
    unittest.main()
