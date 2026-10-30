"""His other patterns on synthetic panels: each is a level and a shape known at t-1, closed over on day t with the
base's chase and volume rules; later bars never change day t."""
import unittest

import numpy as np

from studies.christian_flanders.tests.test_entries import panel
from studies.dan_zanger import replicate as R

FLAT = [(10, 10.2, 9.8, 10)] * 30
CFG = dict(R.DRAFT, pool=dict(turnover=20e6, adr=0.0, above50=False))


def fired(rows, name, t, vol=3.5, cfg=None, after=()):
    A = panel(rows + list(after))
    A['F'].v[t, 0] = vol * 1e6
    c = dict(CFG, setups=[name], **(cfg or {}))
    m, level, stop = R.STUDY.setups(A, c)[name]
    return bool(m[t, 0]), level[t, 0]


POLE = [(10 + .175 * i, 10.2 + .175 * i, 9.8 + .175 * i, 10 + .175 * i) for i in range(1, 21)]   # to 13.5
FLAG = [(13.2, 13.6, 12.8, 13.2)] * 10
TRI = ([(10, 11.0, 9.8, 10.5), (10.2, 10.4, 9.0, 9.2), (9.2, 9.6, 9.0, 9.5)] + [(9.6, 10.2, 9.5, 10)] * 3
       + [(10, 10.9, 9.6, 10.6)] * 4)
TRI_CFG = {'ztri': dict(days=10, depth=40.0, top=.03, recent=4)}


class FlagTests(unittest.TestCase):
    def test_breakout_of_a_tight_flag_after_a_pole(self):
        ok, level = fired(FLAT + POLE + FLAG + [(13.3, 14.0, 13.2, 13.9)], 'zflag', 60)
        self.assertTrue(ok)
        self.assertEqual(level, 13.6)                    # the flag's high, from t-1 and earlier

    def test_no_pole_no_flag(self):
        high_flat = [(12.9, 13.1, 12.6, 12.9)] * 40      # already at the flag's level: no 30% pole under it
        self.assertFalse(fired(high_flat + FLAG + [(13.3, 14.0, 13.2, 13.9)], 'zflag', 50)[0])

    def test_loose_flag(self):
        loose = [(13.2, 13.6, 11.5, 13.2)] * 10          # 18% deep
        self.assertFalse(fired(FLAT + POLE + loose + [(13.3, 14.0, 13.2, 13.9)], 'zflag', 60)[0])

    def test_later_bars_do_not_change_the_day(self):
        rows = FLAT + POLE + FLAG + [(13.3, 14.0, 13.2, 13.9)]
        self.assertEqual(fired(rows, 'zflag', 60), fired(rows, 'zflag', 60, after=[(5, 30, 1, 3)] * 5))


class TriangleTests(unittest.TestCase):
    def test_flat_top_rising_lows(self):
        ok, level = fired(FLAT[:25] + TRI + [(10.8, 11.4, 10.7, 11.3)], 'ztri', 35, cfg=TRI_CFG)
        self.assertTrue(ok)
        self.assertEqual(level, 11.0)

    def test_lows_not_rising(self):
        tri = TRI[:6] + [(10, 10.9, 8.9, 10.6)] + TRI[7:]
        self.assertFalse(fired(FLAT[:25] + tri + [(10.8, 11.4, 10.7, 11.3)], 'ztri', 35, cfg=TRI_CFG)[0])

    def test_needs_a_second_touch_of_the_top(self):
        tri = TRI[:6] + [(10, 10.5, 9.6, 10.3)] * 4      # recent highs 4.5% under the top
        self.assertFalse(fired(FLAT[:25] + tri + [(10.8, 11.4, 10.7, 11.3)], 'ztri', 35, cfg=TRI_CFG)[0])


class TrendlineTests(unittest.TestCase):
    def test_line_through_two_highs(self):
        h = np.full((12, 1), 10.0)
        h[2], h[7] = 20.0, 15.0
        line = R.trendline(h, span=10, recent=5, lower=.03)[:, 0]
        self.assertAlmostEqual(line[10], 12.0)           # 15 at row 7, falling 1 a row, read at row 10
        self.assertTrue(np.isnan(line[5]))               # no full span yet

    def test_needs_a_lower_high(self):
        h = np.full((12, 1), 10.0)
        h[2], h[7] = 20.0, 19.8
        self.assertTrue(np.isnan(R.trendline(h, span=10, recent=5, lower=.03)[10, 0]))

    def test_fresh_break_on_volume(self):
        down = [(14 - .2 * i, 14.2 - .2 * i, 13.6 - .2 * i, 13.8 - .2 * i) for i in range(30)]   # highs 14.2 -> 8.4
        rows = FLAT[:20] + down + [(8.1, 8.7, 8.0, 8.5)]   # the line is at 8.2
        cfg = {'zdtl': dict(span=30, recent=10, lower=.03)}
        ok, level = fired(rows, 'zdtl', 50, cfg=cfg)
        self.assertTrue(ok)
        self.assertAlmostEqual(level, 8.2)
        self.assertFalse(fired(rows, 'zdtl', 50, cfg=cfg, vol=2.0)[0])
        self.assertEqual(fired(rows, 'zdtl', 50, cfg=cfg), fired(rows, 'zdtl', 50, cfg=cfg, after=[(5, 30, 1, 3)] * 3))


class GroupTests(unittest.TestCase):
    def test_strongest_groups_as_of_the_day_before(self):
        from unittest import mock
        from studies.trader_screens import data as TSD
        A = panel(FLAT[:6])                              # 26 names: five industries of five, X25 without one
        rs = np.tile(np.arange(26, dtype=float) / 26, (6, 1))
        rs[3:, :5] = 1.0                                 # industry 0 (X0-X4) jumps to the top on row 3
        ind = {f'US.X{j}': f'g{j // 5}' for j in range(25)}
        with mock.patch.object(R.Zanger, 'rs', lambda self, A: rs), \
                mock.patch.object(TSD, 'industries', lambda codes, market: {c: ind.get(c, '') for c in codes}):
            g = R.STUDY.group_rank(A)
            ok = R.STUDY.strength_ok(A, dict(strength='grp80'))
        self.assertTrue(np.isnan(g[0]).all())           # nothing before the first day
        self.assertAlmostEqual(g[3, 0], .1)              # row 3 reads row 2: industry 0 still the weakest
        self.assertAlmostEqual(g[4, 0], .9)              # row 4 reads row 3's jump
        self.assertAlmostEqual(g[3, 24], .9)
        self.assertTrue(ok[3, 24] and not ok[3, 0])
        self.assertTrue(np.isnan(g[3, 25]))              # no industry: the stock floor RS >= 80 decides
        self.assertTrue(ok[3, 25])                       # rs 25/26 the day before


if __name__ == '__main__':
    unittest.main()
