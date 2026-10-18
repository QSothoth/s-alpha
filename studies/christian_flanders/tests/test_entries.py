"""Entry timing of the Flanders study on a synthetic panel: fill, stop and same-day exit of each entry mode."""
import unittest

import numpy as np

from studies.christian_flanders import replicate as R
from studies.trader_screens import screens as S


def panel(rows, n_other=25):
    """rows: (open, high, low, close) for name 0; other names flat at 50 (the rank pool needs 20 names)."""
    T = len(rows)
    a = np.array(rows, float)
    o, h, l, c = (np.full((T, n_other + 1), 50.0) for _ in range(4))
    o[:, 0], h[:, 0], l[:, 0], c[:, 0] = a[:, 0], a[:, 1], a[:, 2], a[:, 3]
    p = dict(days=np.array([f'2025-{1 + i // 28:02d}-{1 + i % 28:02d}' for i in range(T)]),
             codes=np.array([f'US.X{i}' for i in range(n_other + 1)]), open=o, high=h, low=l, close=c,
             volume=np.full(o.shape, 1e6), turnover=np.full(o.shape, 5e7), raw_close=c.copy())
    return dict(days=p['days'], codes=p['codes'], market='us', F=S.Feat(p, 'us'), open=o, high=h, low=l, close=c,
                has=np.isfinite(c))


BASE = [(10, 10.2, 9.8, 10)] * 30


class EpEntryTests(unittest.TestCase):
    def entries(self, last, mode, **kw):
        A = panel(BASE + [last])
        cfg = dict(R.DRAFT, setups=['ep'], entry=mode, **kw)
        masks = R.STUDY.setups(A, cfg)
        e = R.STUDY.entries(A, cfg, masks)[30]
        return [x for x in e if x[1] == 0]

    def test_level_buys_the_open_with_the_day_low_stop(self):
        (e,) = self.entries((11.2, 11.9, 11.0, 11.5), 'level')
        self.assertEqual((e[3], e[4], e[6]), (11.2, 11.0, None))

    def test_pessimistic_bound_stops_a_close_below_the_fill_the_same_day(self):
        (e,) = self.entries((11.2, 11.9, 11.0, 11.1), 'level_pess')
        self.assertEqual((e[3], e[4], e[6]), (11.2, 11.0, 11.0))
        (e,) = self.entries((11.2, 11.9, 11.0, 11.5), 'level_pess')
        self.assertIsNone(e[6])

    def test_close_and_open_pct_are_exact(self):
        (e,) = self.entries((11.2, 11.9, 11.0, 11.5), 'close')
        self.assertEqual((e[3], e[4]), (11.5, 11.0))
        (e,) = self.entries((11.2, 11.9, 11.0, 11.5), 'open_pct', open_pct=.06)
        self.assertAlmostEqual(e[4], 11.2 * .94)
        self.assertIsNone(e[6])
        (e,) = self.entries((11.2, 11.9, 10.5, 11.5), 'open_pct', open_pct=.06)
        self.assertAlmostEqual(e[6], 11.2 * .94)                 # the low reached the fixed stop: out that day

    def test_gap_threshold_and_stop_floor(self):
        self.assertEqual(self.entries((10.9, 11.5, 10.8, 11.4), 'level'), [])      # +9% gap: no EP
        (e,) = self.entries((11.2, 11.9, 11.15, 11.5), 'level')
        self.assertAlmostEqual(e[4], 11.2 * .99)                 # a 0.4% stop is widened to 1%


    def test_far_low_drops_an_ep_near_the_52_week_low(self):
        self.assertEqual(len(self.entries((11.2, 11.9, 11.0, 11.5), 'close', ep={'far_low': .05})), 1)
        self.assertEqual(len(self.entries((11.2, 11.9, 11.0, 11.5), 'close', ep={'far_low': .20})), 0)


class PullbackTests(unittest.TestCase):
    def test_pullback_breaks_the_pullback_day_high(self):
        rows = [(10 + .05 * i, 10.2 + .05 * i, 9.9 + .05 * i, 10.1 + .05 * i) for i in range(80)]
        c = rows[-1][3]
        rows += [(c - .3, c - .2, c - .9, c - .3)]                  # dips to the 10 EMA, holds the 20
        rows += [(c - .3, c + .2, c - .4, c + .1)]                  # breaks that day's high
        A = panel(rows)
        cfg = dict(R.DRAFT, setups=['pb'], pool=dict(turnover=1e6, adr=0.0, above50=False))
        m, level, stop = R.STUDY.setups(A, cfg)['pb']
        self.assertTrue(m[-1, 0])
        self.assertFalse(m[-2, 0])
        self.assertAlmostEqual(level[-1, 0], c - .2)


class BreakoutTests(unittest.TestCase):
    def test_brk52_fills_at_the_prior_high_or_the_open_above_it(self):
        rows = [(10, 10.2, 9.8, 10)] * 260 + [(10.1, 10.6, 10.0, 10.5)]
        A = panel(rows)
        m, level, stop = R.STUDY.setups(A, dict(R.DRAFT, setups=['brk52'], pool=dict(above50=False)))['brk52']
        self.assertTrue(m[260, 0])
        self.assertFalse(m[259, 0])
        self.assertAlmostEqual(level[260, 0], 10.2)
        rows[-1] = (10.4, 10.6, 10.3, 10.5)                       # opened above the prior high
        A = panel(rows)
        m, level, _ = R.STUDY.setups(A, dict(R.DRAFT, setups=['brk52'], pool=dict(above50=False)))['brk52']
        self.assertAlmostEqual(level[260, 0], 10.4)

    def test_power_play_breaks_the_flag_after_a_doubling(self):
        rows = [(10, 10.2, 9.8, 10)] * 40
        rows += [(10 + i, 10.5 + i, 9.8 + i, 10.4 + i) for i in range(12)]          # 10 -> 22 in 12 days
        rows += [(21, 21.6, 20.0, 21.0)] * 10                                        # flag: 20-21.6 (8%)
        rows += [(21.2, 22.4, 21.0, 22.2)]                                           # breaks the flag high
        A = panel(rows)
        m, level, stop = R.STUDY.setups(A, dict(R.DRAFT, setups=['pp'], pool=dict(above50=False)))['pp']
        T = len(rows) - 1
        self.assertTrue(m[T, 0])
        self.assertFalse(m[T - 1, 0])
        self.assertAlmostEqual(level[T, 0], 21.6)
        self.assertAlmostEqual(stop[T, 0], 21.0)


class DraftTests(unittest.TestCase):
    def test_draft_setup_is_the_board_screen(self):
        rows = [(10 + .01 * i, 10.2 + .01 * i, 9.8 + .01 * i, 10 + .01 * i) for i in range(300)]
        rows[-12] = (12.5, 13.5, 12.4, 13.0)                     # the 52-week high, 12 days ago
        rows[-1] = (13.0, 13.8, 12.9, 13.6)                      # breaks it today
        A = panel(rows)
        mine = R.STUDY.setups(A, R.DRAFT)['hi52'][0]
        theirs = [x for x in S.ChristianFlanders().run(A['F'])['setups'] if x.kind == 'triggered'][0].mask
        np.testing.assert_array_equal(mine, theirs)


if __name__ == '__main__':
    unittest.main()
