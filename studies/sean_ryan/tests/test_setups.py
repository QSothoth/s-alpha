"""Sean Ryan study on a synthetic panel: the second wave triggers on the day the base's top trades, never before,
from bars up to the day before; the pivot fill, yesterday's-low stop and the entry-day close rule; the reversal
day; the trail line excludes today."""
import unittest

import numpy as np

from studies.christian_flanders.tests.test_entries import panel
from studies.sean_ryan import replicate as R


def wave_rows():
    """60 flat sessions at 10, a first wave to ~16 over 8 sessions (one big-volume day), a 10-session base at
    15-15.6, then a day that trades through the base's top."""
    rows = [(10, 10.1, 9.9, 10)] * 60
    p = 10.0
    for _ in range(8):
        rows.append((p, p * 1.07, p * .99, p * 1.06))
        p *= 1.06
    rows += [(15.3, 15.6, 15.0, 15.3)] * 10
    rows.append((15.4, 16.0, 15.3, 15.9))                    # breaks the base's top 15.6
    return rows


def wave_panel(rows):
    A = panel(rows)
    F = A['F']
    F.turnover = np.full(F.c.shape, 5e7)
    F.turnover[61, 0] = 4e8                                   # the first wave's big-volume day
    F.v = F.turnover / F.c
    return A


class WaveTests(unittest.TestCase):
    def setUp(self):
        self.rows = wave_rows()
        self.A = wave_panel(self.rows)
        self.cfg = dict(R.DRAFT, pool=dict(turnover=1e6, price=1.0))
        self.T = len(self.rows) - 1

    def test_triggers_on_the_break_only(self):
        m, pivot, stop = R.STUDY.setups(self.A, self.cfg)['wave2']
        self.assertTrue(m[self.T, 0])
        self.assertFalse(m[self.T - 1, 0])                    # inside the base: no trigger
        self.assertAlmostEqual(pivot[self.T, 0], 15.6)
        self.assertAlmostEqual(stop[self.T, 0], 15.0)          # yesterday's low

    def test_no_wave_without_big_volume(self):
        A = panel(self.rows)                                    # flat turnover: no surge
        m = R.STUDY.setups(A, self.cfg)['wave2'][0]
        self.assertFalse(m[:, 0].any())

    def test_no_future_bars(self):
        """Cutting the panel after day T leaves the day-T decision unchanged."""
        full = R.STUDY.setups(self.A, self.cfg)['wave2'][0]
        rows = self.rows + [(16, 30, 1, 2)] * 5                 # wild later bars
        later = R.STUDY.setups(wave_panel(rows), self.cfg)['wave2'][0]
        np.testing.assert_array_equal(full[:self.T + 1], later[:self.T + 1])

    def test_pivot_fill_and_entry_day_close(self):
        masks = R.STUDY.setups(self.A, self.cfg)
        (e,) = [x for x in R.STUDY.entries(self.A, self.cfg, masks)[self.T] if x[1] == 0]
        self.assertAlmostEqual(e[3], 15.6)                     # max(open 15.4, pivot 15.6)
        self.assertAlmostEqual(e[4], 15.0)                     # 3.8% below: inside [2%, 8%]
        self.assertIsNone(e[6])                                # closed above the fill: held
        rows = self.rows[:-1] + [(15.4, 15.8, 15.3, 15.45)]    # through the pivot, closes under it
        A = wave_panel(rows)
        (e,) = [x for x in R.STUDY.entries(A, self.cfg, R.STUDY.setups(A, self.cfg))[self.T] if x[1] == 0]
        self.assertAlmostEqual(e[6], 15.45)                    # sold at the close
        rows = self.rows[:-1] + [(15.4, 15.8, 14.9, 15.45)]    # and touches the stop: stopped (pessimistic)
        A = wave_panel(rows)
        (e,) = [x for x in R.STUDY.entries(A, self.cfg, R.STUDY.setups(A, self.cfg))[self.T] if x[1] == 0]
        self.assertAlmostEqual(e[6], 15.0)
        self.assertTrue(A['low'][self.T, 0] <= e[3] <= A['high'][self.T, 0])

    def test_close_and_pivot_close_modes(self):
        rows = self.rows[:-1] + [(15.4, 15.8, 14.9, 15.45)]    # through the pivot 15.6, low under the stop 15.0
        A = wave_panel(rows)
        masks = R.STUDY.setups(A, self.cfg)
        (e,) = [x for x in R.STUDY.entries(A, dict(self.cfg, entry='pivot_close'), masks)[self.T] if x[1] == 0]
        self.assertAlmostEqual(e[6], 15.45)                    # closed above the stop: sold at the close
        self.assertEqual([x for x in R.STUDY.entries(A, dict(self.cfg, entry='close'), masks)[self.T]
                          if x[1] == 0], [])                   # closed under the pivot: no close entry
        A = wave_panel(self.rows)
        masks = R.STUDY.setups(A, self.cfg)
        (e,) = [x for x in R.STUDY.entries(A, dict(self.cfg, entry='close'), masks)[self.T] if x[1] == 0]
        self.assertAlmostEqual(e[3], 15.9)                     # the close
        self.assertAlmostEqual(e[4], 15.0)                     # yesterday's low
        self.assertIsNone(e[6])
        (e,) = [x for x in R.STUDY.entries(A, dict(self.cfg, entry='close', stop_from='day'), masks)[self.T]
                if x[1] == 0]
        self.assertAlmostEqual(e[4], 15.3)                     # the day's low

    def test_shakeout(self):
        rows = self.rows[:-1] + [(15.1, 15.2, 14.6, 14.7), (14.7, 14.8, 14.4, 14.5),   # under the base low 15.0
                                 (14.6, 15.4, 14.5, 15.3)]                            # closes back above it
        A = wave_panel(rows)
        cfg = dict(self.cfg, setups=['shake'], entry='close', stop_from='day')
        m, neck, under = R.STUDY.setups(A, cfg)['shake']
        T = len(rows) - 1
        self.assertTrue(m[T, 0])
        self.assertFalse(m[T - 1, 0])
        self.assertAlmostEqual(neck[T, 0], 15.0)
        (e,) = [x for x in R.STUDY.entries(A, cfg, {'shake': (m, neck, under)})[T] if x[1] == 0]
        self.assertAlmostEqual(e[3], 15.3)
        self.assertAlmostEqual(e[4], 14.4)                     # the undercut's low, not the day's low

    def test_stop_bounds(self):
        rows = self.rows[:-2] + [(15.3, 15.6, 13.0, 15.3), (15.4, 16.0, 15.3, 15.9)]   # yesterday's low far
        A = wave_panel(rows)
        e = [x for x in R.STUDY.entries(A, self.cfg, R.STUDY.setups(A, self.cfg))[self.T] if x[1] == 0]
        self.assertEqual(len(e), 1)
        self.assertAlmostEqual(e[0][4], e[0][3] * .92)         # capped at 8%

    def test_reversal_day(self):
        rows = [(10, 10.2, 9.8, 10)] * 60 + [(10.5, 12, 10.4, 10.6)]   # new high, closes at the lows
        A = panel(rows)
        A['F'].v = np.full(A['F'].c.shape, 1e6)
        A['F'].v[60, 0] = 5e6
        rev = R.STUDY.named(A, None, 'rev')
        self.assertTrue(rev[60, 0])
        self.assertFalse(rev[59, 0])

    def test_trail_line_is_before_today(self):
        rows = [(10, 10.2, 9.8 - .01 * i, 10) for i in range(30)]
        A = panel(rows)
        plo = R.STUDY.named(A, None, 'plo10')
        self.assertAlmostEqual(plo[29, 0], min(r[2] for r in rows[19:29]))


if __name__ == '__main__':
    unittest.main()
