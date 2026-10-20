"""Minervini's baseline short: stage-4 template as of t-1, a close under the prior 10-day low, the stop 2% above the
prior 10-day high capped at 8% above the close; no later bars read."""
import unittest

import numpy as np

from studies.christian_flanders.tests.test_entries import panel
from studies.mark_minervini import replicate as R


class MinerviniShortTests(unittest.TestCase):
    def test_breakdown_in_a_stage_four_name(self):
        c = np.linspace(40, 15, 280)
        rows = [(x * 1.001, x * 1.01, x * .99, x) for x in c]
        rows[-6:-1] = [(15.2, 15.4, 15.0, 15.2)] * 5                 # a short pause
        rows.append((15.0, 15.1, 14.2, 14.3))                        # closes under the 10-day low
        A = panel(rows)
        z = R.STUDY.short_setups(A, {})[0]['s4']
        self.assertTrue(z['armed'][-1, 0])
        self.assertFalse(z['armed'][-2, 0])
        hi10 = max(r[1] for r in rows[-11:-1])
        self.assertAlmostEqual(z['stop'][-1, 0], min(hi10 * 1.02, 14.3 * 1.08))

    def test_no_later_bars_are_read(self):
        rng = np.random.default_rng(17)
        c = 30 * np.exp(np.cumsum(rng.normal(-.003, .03, 330)))
        rows = [(x, x * 1.03, x * .97, x) for x in c]
        full = R.STUDY.short_setups(panel(rows), {})[0]['s4']
        part = R.STUDY.short_setups(panel(rows[:301]), {})[0]['s4']
        np.testing.assert_array_equal(full['armed'][:301], part['armed'])
        np.testing.assert_array_equal(full['stop'][:301], part['stop'])
        self.assertTrue(full['armed'].any())


if __name__ == '__main__':
    unittest.main()
