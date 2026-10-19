"""Kell's short triggers on synthetic panels: the Wedge Drop fires on the first close under the lower of the 10 / 20
EMA after an extended run, the Downside EMA Crossback on a later close under a failed rally's low, and neither
reads bars after its day."""
import unittest

import numpy as np

from studies.christian_flanders.tests.test_entries import panel, BASE
from studies.oliver_kell import replicate as R

SC = dict(turnover=20e6)          # the test panel's turnover is 50M (his pool floor is 100M)


def path():
    run = [(10 + i, 11.2 + i, 9.9 + i, 11 + i) for i in range(8)]                 # 11 -> 18: far above the 10-day
    fall = [(17.5, 17.6, 15.0, 15.2), (15.0, 15.3, 13.4, 13.5), (13.4, 13.5, 12.2, 12.4),   # drop: 12.4 < 20 EMA
            (12.3, 12.4, 11.7, 11.8), (11.8, 11.9, 11.4, 11.5)]
    rally = [(11.6, 13.6, 11.5, 12.3)]                                             # tags the falling 10 EMA
    after = [(12.2, 12.3, 11.0, 11.2), (11.1, 11.3, 10.8, 11.0)]
    return BASE + run + fall + rally + after


class KellShortTests(unittest.TestCase):
    def test_wedge_drop_is_the_first_close_under_the_lower_ema(self):
        A = panel(path())
        F = A['F']
        bottom = np.fmin(F.ema(10), F.ema(20))[:, 0]
        c = F.c[:, 0]
        first = next(t for t in range(38, len(c)) if c[t] < bottom[t] and c[t - 1] >= bottom[t - 1])
        m = R.STUDY.short_setups(A, dict(SC, setups=['drop']))[0]['drop'][:, 0]
        self.assertEqual(list(np.flatnonzero(m)), [first])

    def test_crossback_closes_under_the_rally_day_low(self):
        A = panel(path())
        z = R.STUDY.short_setups(A, SC)[0]
        drop = int(np.flatnonzero(z['drop'][:, 0])[0])
        got = list(np.flatnonzero(z['dcross'][:, 0]))
        F = A['F']
        rally = len(path()) - 3
        self.assertGreaterEqual(rally - drop, 2)
        self.assertTrue(F.h[rally, 0] >= F.ema(10)[rally, 0] and F.c[rally, 0] < F.ema(20)[rally, 0])
        self.assertEqual(got, [rally + 1])                     # 11.2 < the rally day's low 11.5, once

    def test_limits_after_the_drop_use_yesterdays_line(self):
        A = panel(path())
        z = R.STUDY.short_setups(A, dict(SC, setups=['drop', 'lim20', 'lim10']))[0]
        drop = int(np.flatnonzero(z['drop'][:, 0])[0])
        armed = np.flatnonzero(z['lim20']['armed'][:, 0])
        self.assertTrue(len(armed) and armed[0] > drop)                 # never before or on the drop day
        t = armed[0]
        self.assertAlmostEqual(z['lim20']['level'][t, 0], A['F'].ema(20)[t - 1, 0])

    def test_no_later_bars_are_read(self):
        rng = np.random.default_rng(7)
        c = 20 * np.exp(np.cumsum(rng.normal(0, .05, 300)))
        rows = [(x * (1 + rng.normal(0, .01)), x * 1.04, x * .96, x) for x in c]
        full = R.STUDY.short_setups(panel(rows), dict(SC, setups=['drop', 'dcross', 'lim20', 'lim10', 'lim50']))[0]
        cut = 230
        part = R.STUDY.short_setups(panel(rows[:cut + 1]), dict(SC, setups=['drop', 'dcross', 'lim20', 'lim10', 'lim50']))[0]
        for k in full:
            if isinstance(full[k], dict):
                np.testing.assert_array_equal(full[k]['armed'][:cut + 1], part[k]['armed'])
                np.testing.assert_array_equal(full[k]['level'][:cut + 1], part[k]['level'])
            else:
                self.assertTrue(np.array_equal(full[k][:cut + 1], part[k]), k)


if __name__ == '__main__':
    unittest.main()
