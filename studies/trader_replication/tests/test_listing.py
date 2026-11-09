"""New listings measured since listing (Feat.listing, TRADER_LISTING=1): yearly measures exist from the first bars of
a name that starts inside the panel, read only bars up to that day, and leave warm-up names and old names alone."""
import unittest

import numpy as np

from studies.trader_replication import common as C, ledger as L
from studies.trader_screens import screens as S


def feat(listing, n=400):
    """Column 0 has bars from the first row, column 1 lists on row 100; both climb 1 a day."""
    c = np.column_stack([100. + np.arange(n), 100. + np.arange(n)])
    c[:100, 1] = np.nan
    p = dict(days=np.arange(n), codes=np.array(['US.OLD', 'US.NEW']), open=c, high=c + 1, low=c - 1, close=c,
             volume=c * 0 + 1, turnover=c * 0 + 1e7, raw_close=c)
    F = S.Feat(p, 'us')
    F.listing = listing
    return F


class Listing(unittest.TestCase):
    def test_off_leaves_new_listings_empty(self):
        self.assertTrue(np.isnan(feat(False).hi(252)[150, 1]))

    def test_high_and_low_since_listing(self):
        F = feat(True)
        self.assertEqual(F.hi(252)[150, 1], F.h[150, 1])
        self.assertEqual(F.lo(252)[150, 1], F.l[100, 1])
        self.assertTrue(np.isnan(F.hi(252)[99, 1]))           # not listed yet

    def test_full_window_is_the_rolling_value(self):
        self.assertEqual(feat(True).hi(252)[399, 1], feat(False).hi(252)[399, 1])
        self.assertEqual(feat(True).ret(252)[399, 1], feat(False).ret(252)[399, 1])

    def test_panel_start_names_stay_in_warm_up(self):
        F = feat(True)
        self.assertTrue(np.isnan(F.hi(252)[150, 0]))
        self.assertTrue(np.isnan(F.ret(252)[150, 0]))

    def test_return_since_first_close_after_20_bars(self):
        F = feat(True)
        self.assertEqual(F.ret(252)[150, 1], F.c[150, 1] / F.c[100, 1] - 1)
        self.assertTrue(np.isnan(F.ret(252)[110, 1]))

    def test_short_windows_untouched(self):
        self.assertTrue(np.isnan(feat(True).hi(20)[110, 1]))
        self.assertTrue(np.isnan(feat(True).ret(21)[110, 1]))

    def test_no_look_ahead(self):
        whole, cut = feat(True), feat(True, 160)
        self.assertEqual(whole.hi(252)[150, 1], cut.hi(252)[150, 1])
        self.assertEqual(whole.ret(252)[150, 1], cut.ret(252)[150, 1])


class Market(unittest.TestCase):
    def test_ticker_market(self):
        self.assertEqual([L.market(t) for t in ('NVDA', 'BRK.B', '09992', '600519')], ['us', 'us', 'hk', 'cn'])

    def test_untestable_is_a_stage(self):
        self.assertIn('untestable', C.STAGES)


if __name__ == '__main__':
    unittest.main()
