"""Clement's failed-base short on synthetic panels: armed on t-1 data only (a former leader under its 20 EMA after
violating it, rallying on low volume), the limit at yesterday's 20 EMA, and no later bars read."""
import unittest

import numpy as np

from studies.christian_flanders.tests.test_entries import panel
from studies.clement_ang import replicate as R


class ClementShortTests(unittest.TestCase):
    def rows(self):
        up = [(10 + .2 * i, 10.3 + .2 * i, 9.9 + .2 * i, 10.2 + .2 * i) for i in range(80)]   # a leader
        top = up[-1][3]
        down = [(top - .5 * i, top - .5 * i + .1, top - .5 * i - .6, top - .5 * i - .5) for i in range(1, 8)]
        return up + down

    def test_armed_after_the_violation_and_level_is_yesterdays_ema(self):
        rows = self.rows()
        A = panel(rows)
        A['F'].v[-3:, 0] = 2e5                                      # the rally days on low volume
        z = R.STUDY.short_setups(A, {'turnover': 20e6, 'adr': 1.0, 'setups': ['fb20', 'fb20c']})[0]
        e20 = A['F'].ema(20)[:, 0]
        armed = np.flatnonzero(z['fb20']['armed'][:, 0])
        self.assertTrue(len(armed))
        t = armed[-1]
        self.assertLess(A['F'].c[t - 1, 0], e20[t - 1])             # still under the line the day before
        self.assertAlmostEqual(z['fb20']['level'][t, 0], e20[t - 1])

    def test_late_stage_needs_a_big_advance(self):
        rows = self.rows()
        A = panel(rows)
        A['F'].v[-3:, 0] = 2e5
        sc = {'turnover': 20e6, 'adr': 1.0, 'setups': ['fb20']}
        base = R.STUDY.short_setups(A, sc)[0]['fb20']['armed'][:, 0]
        big = R.STUDY.short_setups(A, dict(sc, run=1.0))[0]['fb20']['armed'][:, 0]      # 10 -> 26: +160%
        huge = R.STUDY.short_setups(A, dict(sc, run=2.0))[0]['fb20']['armed'][:, 0]
        self.assertTrue(base.any())
        np.testing.assert_array_equal(base, big)
        self.assertFalse(huge.any())

    def test_no_later_bars_are_read(self):
        rng = np.random.default_rng(13)
        c = 20 * np.exp(np.cumsum(rng.normal(.001, .04, 260)))
        rows = [(x, x * 1.04, x * .96, x * (1 + rng.normal(0, .01))) for x in c]
        rows = [(o, max(h, x), min(l, x), x) for (o, h, l, x) in rows]
        sc = {'turnover': 20e6, 'setups': ['fb20', 'fb20c'], 'leader': .5}
        full = R.STUDY.short_setups(panel(rows), sc)[0]
        cut = 200
        part = R.STUDY.short_setups(panel(rows[:cut + 1]), sc)[0]
        np.testing.assert_array_equal(full['fb20']['armed'][:cut + 1], part['fb20']['armed'])
        np.testing.assert_array_equal(full['fb20']['level'][:cut + 1], part['fb20']['level'])
        np.testing.assert_array_equal(full['fb20c'][:cut + 1], part['fb20c'])


if __name__ == '__main__':
    unittest.main()
