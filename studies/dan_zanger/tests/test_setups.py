"""Dan Zanger study on a synthetic panel: the base breakout is decided at day t's close from bars up to t (pivot and
base from t-1), bought at that close with his stop; the exit signal reads only the day's close and earlier bars."""
import unittest

import numpy as np

from studies.christian_flanders.tests.test_entries import panel
from studies.dan_zanger import replicate as R

FLAT = [(10, 10.2, 9.8, 10)] * 30
CFG = dict(R.DRAFT, pool=dict(turnover=20e6, adr=0.0, above50=False))


def build(last, vol=3.5, after=()):
    A = panel(FLAT + [last] + list(after))
    A['F'].v[30, 0] = vol * 1e6
    return A


class BreakoutTests(unittest.TestCase):
    def signal(self, A, cfg=CFG):
        m, pivot, stop = R.STUDY.setups(A, cfg)['zbase']
        return bool(m[30, 0]), pivot[30, 0], stop[30, 0]

    def test_close_over_the_pivot_on_volume(self):
        ok, pivot, stop = self.signal(build((10.1, 10.6, 10.0, 10.5)))
        self.assertTrue(ok)
        self.assertEqual(pivot, 10.2)                    # the prior 20 sessions' high, not the day's own
        self.assertAlmostEqual(stop, 10.5 * .95)

    def test_needs_three_times_volume(self):
        self.assertFalse(self.signal(build((10.1, 10.6, 10.0, 10.5), vol=2.9))[0])

    def test_never_more_than_five_percent_over(self):
        self.assertFalse(self.signal(build((10.1, 11.0, 10.0, 10.75)))[0])

    def test_intraday_poke_that_closes_under_is_no_signal(self):
        self.assertFalse(self.signal(build((10.1, 10.6, 10.0, 10.15)))[0])

    def test_pivot_stop(self):
        _, _, stop = self.signal(build((10.1, 10.6, 10.0, 10.5)), dict(CFG, stop='pivot', stop_pct=.03))
        self.assertAlmostEqual(stop, 10.2 * .97)

    def test_later_bars_do_not_change_the_day(self):
        a = self.signal(build((10.1, 10.6, 10.0, 10.5)))
        b = self.signal(build((10.1, 10.6, 10.0, 10.5), after=[(5, 20, 1, 3)] * 5))
        self.assertEqual(a, b)

    def test_entry_buys_the_close_with_his_stop(self):
        A = build((10.1, 10.6, 10.0, 10.5))
        masks = R.STUDY.setups(A, CFG)
        (e,) = [x for x in R.STUDY.entries(A, CFG, masks)[30] if x[1] == 0]
        self.assertEqual(e[3], 10.5)
        self.assertAlmostEqual(e[4], 10.5 * .95)
        self.assertNotIn('zbase', R.STUDY.intraday_kinds(CFG, ['zbase']))


    def test_low_stop_capped(self):
        A = build((10.1, 10.6, 10.0, 10.5))
        cfg = dict(CFG, stop='low', stop_cap=.05)
        (e,) = [x for x in R.STUDY.entries(A, cfg, R.STUDY.setups(A, cfg))[30] if x[1] == 0]
        self.assertAlmostEqual(e[4], 10.0)               # the day's low, 4.8% under the close
        A = build((10.1, 10.6, 9.5, 10.5))
        (e,) = [x for x in R.STUDY.entries(A, cfg, R.STUDY.setups(A, cfg))[30] if x[1] == 0]
        self.assertAlmostEqual(e[4], 10.5 * .95)         # a low 9.5% under is capped at 5%

    def test_earnings_gap_alongside(self):
        A = build((11.2, 11.9, 11.0, 11.5))
        cfg = dict(CFG, setups=['zbase', 'ep'], entry='close')
        masks = R.STUDY.setups(A, cfg)
        self.assertEqual(set(masks), {'zbase', 'ep'})
        self.assertTrue(masks['ep'][0][30, 0])           # opened 12% over the prior close
        kinds = {x[5] for x in R.STUDY.entries(A, cfg, masks)[30] if x[1] == 0}
        self.assertEqual(kinds, {'ep'})                  # 11.5 is more than 5% over the pivot: no zbase


class ExitTests(unittest.TestCase):
    def test_asleep_or_trendline(self):
        rows = FLAT + [(10, 10.6, 10.0, 10.5), (10.5, 10.9, 10.4, 10.8), (10.8, 10.9, 10.6, 10.7),
                       (10.7, 10.8, 10.5, 10.6), (10.6, 10.7, 10.4, 10.5), (10.5, 10.6, 10.3, 10.4),
                       (10.4, 10.5, 9.0, 9.2)]
        A = panel(rows)
        x = R.STUDY.named(A, None, 'zexit5')[:, 0]
        self.assertFalse(x[33])                          # 10.6 is above the close five sessions earlier (10.0)
        self.assertTrue(x[35])                           # 10.4 is not above 10.5 five sessions earlier: asleep
        self.assertTrue(R.STUDY.named(A, None, 'zexit0')[36, 0])   # 9.2 under the prior 10-day low (9.8)
        self.assertFalse(R.STUDY.named(A, None, 'zexit0')[35, 0])

    def test_reversal_on_volume(self):
        rows = FLAT + [(10, 10.6, 10.0, 10.5), (10.5, 11.0, 10.4, 10.9), (10.9, 11.2, 10.5, 10.6)]
        A = panel(rows)
        A['F'].v[32, 0] = 2.5e6
        x = R.STUDY.named(A, None, 'zrev0')[:, 0]
        self.assertTrue(x[32])                           # down close in the lower half on 2.5x volume
        self.assertFalse(x[31])
        self.assertFalse(R.STUDY.named(A, None, 'zexit0')[32, 0])


class GateTests(unittest.TestCase):
    def test_total_and_drawdown_gates(self):
        ref = dict(total=.2, maxdd=.19)
        st = dict(total=-.06, maxdd=.46)
        self.assertEqual(R.Zanger.passes(st, ref, ['total', 'dd+0.05']), ['total', 'dd+0.05'])
        self.assertEqual(R.Zanger.passes(dict(total=.25, maxdd=.2), ref, ['total', 'dd+0.05']), [])


if __name__ == '__main__':
    unittest.main()
