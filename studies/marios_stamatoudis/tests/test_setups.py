"""Marios Stamatoudis study on a synthetic panel: the EP needs a gap of at least 5% that opens above the prior
63-day high on 3x volume, decided from the open and earlier bars; the close entry with the day-low stop; the 1-ADR
stop-width rule."""
import unittest

import numpy as np

from studies.christian_flanders.tests.test_entries import panel
from studies.marios_stamatoudis import replicate as R

BASE = [(10, 10.3, 9.7, 10)] * 80


def ep_panel(last, vol=4e6):
    A = panel(BASE + [last])
    F = A['F']
    F.v = np.full(F.c.shape, 1e6)
    F.v[-1, 0] = vol
    F.turnover = F.v * F.c * 10                     # 20-day turnover well above 20M
    return A


class EpTests(unittest.TestCase):
    cfg = dict(R.DRAFT, setups=['ep'])

    def mask(self, A):
        return R.STUDY.setups(A, self.cfg)['ep'][0]

    def test_gap_out_of_the_range(self):
        A = ep_panel((10.6, 11.2, 10.5, 11.0))      # +6% gap, above the 63-day high 10.3, 4x volume
        self.assertTrue(self.mask(A)[-1, 0])

    def test_small_gap_or_inside_the_range(self):
        self.assertFalse(self.mask(ep_panel((10.2, 11.2, 10.1, 11.0)))[-1, 0])      # +2% gap
        A = panel(BASE[:-10] + [(10, 11, 9.7, 10)] + BASE[-9:] + [(10.6, 11.2, 10.5, 11.0)])
        F = A['F']
        F.v = np.full(F.c.shape, 1e6)
        F.v[-1, 0] = 4e6
        F.turnover = F.v * F.c * 10
        self.assertFalse(self.mask(A)[-1, 0])                                        # opens under the 11 high

    def test_needs_volume(self):
        self.assertFalse(self.mask(ep_panel((10.6, 11.2, 10.5, 11.0), vol=1.5e6))[-1, 0])

    def test_close_entry_and_day_low_stop(self):
        A = ep_panel((10.6, 11.2, 10.5, 11.0))
        masks = R.STUDY.setups(A, self.cfg)
        T = len(BASE)
        entries = R.STUDY.entries(A, self.cfg, masks)[T]
        (e,) = [x for x in entries if x[1] == 0]
        self.assertAlmostEqual(e[3], 11.0)
        self.assertAlmostEqual(e[4], 10.5)
        self.assertTrue(A['low'][T, 0] <= e[3] <= A['high'][T, 0])

    def test_stop_wider_than_one_adr_is_skipped(self):
        A = ep_panel((10.6, 11.6, 10.0, 11.5))      # stop 13% below the close; ADR ~6%
        masks = R.STUDY.setups(A, self.cfg)
        self.assertTrue(masks['ep'][0][-1, 0])
        self.assertEqual([x for x in R.STUDY.entries(A, self.cfg, masks)[len(BASE)] if x[1] == 0], [])

    def test_no_future_bars(self):
        A = ep_panel((10.6, 11.2, 10.5, 11.0))
        B = panel(BASE + [(10.6, 11.2, 10.5, 11.0)] + [(30, 40, 1, 2)] * 3)
        F = B['F']
        F.v = np.full(F.c.shape, 1e6)
        F.v[len(BASE), 0] = 4e6
        F.turnover = F.v * F.c * 10
        np.testing.assert_array_equal(self.mask(A), self.mask(B)[:len(BASE) + 1])


if __name__ == '__main__':
    unittest.main()
