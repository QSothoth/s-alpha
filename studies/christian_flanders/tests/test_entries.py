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


class OrderTests(unittest.TestCase):
    def test_kind_order_puts_the_listed_setups_first(self):
        A = panel(BASE + [(11.2, 11.9, 11.0, 11.5)])
        m = np.zeros(A['close'].shape, bool)
        m[30, :2] = True
        masks = {'pb': (m, np.full(m.shape, 11.0), A['low']), 'ep': (m, A['open'], A['low'])}
        cfg = dict(R.DRAFT, entry='close', kind_order=['ep', 'hi52', 'pb'])
        e = sorted(R.STUDY.entries(A, cfg, masks)[30], key=lambda x: x[0])
        self.assertEqual([x[5] for x in e], ['ep', 'ep', 'pb', 'pb'])


    def test_close_any_buys_a_close_below_the_level(self):
        A = panel(BASE + [(10.0, 10.6, 9.9, 10.1)])
        m = np.zeros(A['close'].shape, bool)
        m[30, 0] = True
        masks = {'pb': (m, np.full(m.shape, 10.3), A['low'])}
        cfg = dict(R.DRAFT, entry='close')
        self.assertEqual(R.STUDY.entries(A, cfg, masks)[30], [])
        (e,) = R.STUDY.entries(A, dict(cfg, close_any=['pb']), masks)[30]
        self.assertEqual((e[3], e[4]), (10.1, 9.9))


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


class KindStrengthTests(unittest.TestCase):
    def test_only_the_named_kind_is_narrowed_and_on_the_day_before(self):
        rows = [(10, 10.2, 9.8, 10)] * 260 + [(19, 20.5, 19, 20.4)]     # 52-week low 9.8; up 108% on the last day
        A = panel(rows)
        ok = np.ones(A['F'].c.shape, bool)
        cfg = dict(R.DRAFT, strength_by_kind={'vcp': ['up100']})
        m_vcp = R.STUDY.kind_strength(A, cfg, 'vcp', ok)
        self.assertTrue(R.STUDY.kind_strength(A, cfg, 'hi52', ok).all())         # other kinds untouched
        self.assertFalse(m_vcp[-1, 0])                                           # day t's own close is not used
        A2 = panel(rows + [(20.4, 20.6, 20.2, 20.5)])
        self.assertTrue(R.STUDY.kind_strength(A2, cfg, 'vcp', np.ones(A2['F'].c.shape, bool))[-1, 0])


class BreakoutVolumeTests(unittest.TestCase):
    def masks(self, rows, vol_last, **o):
        A = panel(rows)
        A['F'].turnover[-1, 0] = vol_last                # name 0's last-day turnover (others 5e7 a day)
        cfg = dict(R.DRAFT, setups=['brkv'], brkv=o, pool={'adr': 0.0})
        return R.STUDY.setups(A, cfg)['brkv']

    @staticmethod
    def rising(n):                                       # a slow climb (above its 50-day), ADR about 4%
        return [(10 + .001 * i, 10.2 + .001 * i, 9.8 + .001 * i, 10 + .001 * i) for i in range(n)]

    def test_a_wide_up_day_on_heavy_volume_over_the_prior_high(self):
        rows = self.rising(260) + [(10.3, 11.3, 10.3, 11.2)]
        m, level, stop = self.masks(rows, 2e8)
        self.assertTrue(m[-1, 0])
        self.assertAlmostEqual(level[-1, 0], 10.2 + .259)  # the prior high, known the day before
        self.assertFalse(self.masks(rows, 5e7)[0][-1, 0])  # ordinary volume: no
        quiet = self.rising(260) + [(10.3, 10.6, 10.3, 10.55)]
        self.assertFalse(self.masks(quiet, 2e8)[0][-1, 0])  # +2% under 1 ADR: no

    def test_listing_uses_the_high_since_listing(self):
        rows = self.rising(60) + [(10.1, 11.0, 10.1, 10.9)]
        self.assertFalse(self.masks(rows, 2e8)[0][-1, 0])  # no 252-day high yet: the plain rule cannot fire
        m, level, _ = self.masks(rows, 2e8, listing=True)
        self.assertTrue(m[-1, 0])                         # the high since listing stands in
        self.assertAlmostEqual(level[-1, 0], 10.2 + .059)
