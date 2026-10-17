"""Five-minute execution tests: which bar triggers, the stop chosen, and how the trade exits."""
import unittest

import numpy as np

from studies.martin_luk import intraday as I

NB = I.NB


def flat(px):
    a = np.full(NB, float(px))
    return [a.copy(), a.copy(), a.copy(), a.copy()]


class FirstEntry(unittest.TestCase):
    def test_breakout_triggers_at_prior_high_and_lod_includes_entry_bar(self):
        o, h, l, c = flat(100)
        h[3], l[1], l[3] = 101.2, 99.0, 99.5
        b, fill, lod = I.first_entry((o, h, l, c), 'bo', {'high': 101.0})
        self.assertEqual((b, fill, lod), (3, 101.0, 99.0))

    def test_gap_above_prior_high_waits_for_first_bar_high(self):
        o, h, l, c = flat(103)
        h[0], l[0] = 104.0, 102.5
        h[5] = 104.5
        b, fill, lod = I.first_entry((o, h, l, c), 'bo', {'high': 101.0})
        self.assertEqual((b, fill, lod), (5, 104.0, 102.5))

    def test_pullback_buys_the_close_of_the_reclaim_bar(self):
        o, h, l, c = flat(100.5)
        l[2], c[2], c[3] = 99.0, 99.4, 99.6   # pierces EMA 100 and stays below for two closes
        c[4] = 100.3                     # first close back above
        b, fill, lod = I.first_entry((o, h, l, c), 'pb', {'ema': np.array([102.0, 100.0, 95.0])})
        self.assertEqual((b, fill, lod), (4, 100.3, 99.0))

    def test_confirm_close_buys_the_first_close_above_trigger(self):
        o, h, l, c = flat(100)
        h[3], c[3] = 101.5, 100.8          # wick through 101 but closes below
        h[4], l[4], c[4] = 101.6, 100.7, 101.3
        l[1] = 99.2
        b, fill, lod = I.first_entry((o, h, l, c), 'bo', {'high': 101.0}, confirm_close=True)
        self.assertEqual((b, fill, lod), (4, 101.3, 99.2))

    def test_no_trigger_returns_none(self):
        self.assertIsNone(I.first_entry(tuple(flat(100)), 'bo', {'high': 101.0}))


def tiny(bars_by_day, prev_close=100.0):
    """P for one stock 'AAA' (+QQQ); day 0 is history, later days are given as {day: (o,h,l,c) arrays}."""
    D = len(bars_by_day) + 1
    arr = np.full((6, 2, D, NB), np.nan, np.float32)
    arr[:4, :, 0, :] = prev_close
    arr[4:, :, 0, :] = 1e6
    for d, bars in enumerate(bars_by_day, start=1):
        for k in range(4):
            arr[k, 0, d] = bars[k]
            arr[k, 1, d] = 300.0
        arr[4:, :, d] = 1e6
    days = np.array([f'2025-01-{i + 1:02d}' for i in range(D)])
    dly = I.daily(arr)
    z = np.zeros((D, 2))
    P = dict(days=days, syms=np.array(['AAA', 'QQQ']), arr=arr, stock=np.array([True, False]), d=dly,
             e9=z + 99.0, e21=z + 98.0, e50=z + 97.0, adr=z + 8.0, to20=z + 1e9, mom=z + 1.0, r63=z + .5,
             qqq_up=np.ones(D, bool))
    return P


class Shorts(unittest.TestCase):
    def test_breakdown_mirrors_breakout(self):
        o, h, l, c = flat(100)
        l[3], h[1], h[3] = 98.8, 100.9, 100.4
        b, fill, hod = I.first_short((o, h, l, c), 'sbd', {'low': 99.0})
        self.assertEqual((b, fill, hod), (3, 99.0, 100.9))

    def test_failed_bounce_shorts_close_back_below_ema21(self):
        o, h, l, c = flat(99.5)
        h[2], c[2], c[3] = 100.6, 100.2, 100.1    # pokes above EMA 100 and closes above twice
        c[4] = 99.7                               # first close back below
        b, fill, hod = I.first_short((o, h, l, c), 'sbr', {'e21': 100.0})
        self.assertEqual((b, fill, hod), (4, 99.7, 100.6))

    def test_short_stop_and_pnl_sign(self):
        P = tiny([tuple(flat(100))])
        P['arr'][1, 0, 0, :] = 100.2               # day 0: tight range 99.5..100.2
        P['arr'][2, 0, 0, :] = 99.5
        o, h, l, c = flat(99.6)
        h[0] = 99.8                                # HOD so far 99.8
        l[2] = 99.4                                # breaks the 99.5 prior low -> short at 99.5
        h[6] = 99.9                                # stop 99.8 hit
        P['arr'][:4, 0, 1] = np.array([o, h, l, c])
        P['d'] = I.daily(P['arr'])
        P['e9'][:] = 101; P['e21'][:] = 102; P['e50'][:] = 103; P['mom_dn'] = P['mom'] * 0 - .5
        cfg = I.Cfg(breakout=False, pullback=False, ep=False, short_bd=True)
        _, _, tr = I.simulate(P, cfg, P['days'][1], P['days'][-1])
        t = tr[0]
        self.assertEqual((t['side'], t['bar'], t['fill'], round(t['stop'], 4), t['why']), (-1, 2, 99.5, 99.8, 'stop'))
        self.assertLess(t['pnl'], 0)
        self.assertAlmostEqual(t['r'], (99.5 * .999 - 99.8 * 1.001) / (99.8 - 99.5), places=3)


class HKSlots(unittest.TestCase):
    def test_auctions_and_lunch_map_to_the_right_five_minute_slots(self):
        m = lambda hh, mm: I._hk_slot(hh * 60 + mm)
        self.assertEqual([m(9, 30), m(9, 31), m(9, 35), m(9, 36), m(12, 0), m(13, 1), m(13, 5), m(16, 0), m(16, 8)],
                         [0, 0, 0, 1, 29, 30, 30, 65, 65])


class Simulate(unittest.TestCase):
    def run_bo(self, days_bars, **kw):
        P = tiny(days_bars)
        # make day 0 an inside/tight setup: high 100.5 low 99.8 (range 0.7% <= 0.5*ADR 8%)
        P['arr'][1, 0, 0, :] = 100.5
        P['arr'][2, 0, 0, :] = 99.8
        P['d'] = I.daily(P['arr'])
        cfg = I.Cfg(pullback=False, ep=False, **kw)
        return I.simulate(P, cfg, P['days'][1], P['days'][-1])

    def test_intraday_stop_then_no_reentry_same_day(self):
        o, h, l, c = flat(100.2)
        h[2] = 100.8                       # trigger at 100.5, LOD so far 100.2
        l[6], c[6:] = 99.9, 100.0          # stop at 100.2 hit on bar 6
        _, _, tr = self.run_bo([(o, h, l, c)])
        t = tr[0]
        self.assertEqual((t['bar'], t['fill'], round(t['stop'], 4), t['why']), (2, 100.5, 100.2, 'stop'))
        self.assertAlmostEqual(t['r'], (100.2 * .999 - 100.5 * 1.001) / (100.5 - 100.2), places=3)

    def test_trim_at_3r_then_no_follow_through_exit_at_close(self):
        o, h, l, c = flat(100.4)
        l[0] = 100.3                       # LOD before the trigger
        h[1] = 100.6                       # fill 100.5, lod 100.3 -> R = 0.2, 3R = 101.1
        h[10] = 101.2
        c[-1] = 100.4                      # closes below the fill
        _, _, tr = self.run_bo([(o, h, l, c)])
        self.assertEqual(tr[0]['why'], 'nft')
        sold = .15 * 101.1 + .85 * 100.4
        self.assertAlmostEqual(tr[0]['ret'], (sold * .999 - 100.5 * 1.001) / 100.5, places=6)

    def test_adr_floor_moves_the_stop_below_a_too_close_day_low(self):
        o, h, l, c = flat(100.4)
        l[0] = 100.3                       # LOD 100.3 is only 0.2% below the 100.5 fill
        h[1], l[6] = 100.6, 99.5           # 99.5 would hit the LOD stop but not a 0.5 x 8% ADR = 4% floor
        _, _, tr = self.run_bo([(o, h, l, c)], stop_floor_adr=.5)
        self.assertAlmostEqual(tr[0]['stop'], 100.5 * .96, places=4)
        self.assertNotEqual(tr[0]['why'], 'stop')

    def test_close_stop_ignores_the_entry_day_wick(self):
        o, h, l, c = flat(100.45)
        l[0] = 100.3
        h[1], l[6], c[-1] = 100.6, 100.0, 100.55   # wick under the 100.3 stop, close back above the fill
        _, _, tr = self.run_bo([(o, h, l, c)], close_stop_day0=True)
        self.assertEqual(tr[0]['why'], 'end')

    def test_overnight_gap_below_stop_exits_at_next_open(self):
        o, h, l, c = flat(100.45)
        l[0] = 100.3
        h[1], c[-1] = 100.7, 100.6
        o2, h2, l2, c2 = flat(99.0)
        _, _, tr = self.run_bo([(o, h, l, c), (o2, h2, l2, c2)])
        self.assertEqual((tr[0]['exit'], tr[0]['why']), ('2025-01-03', 'gap_stop'))


if __name__ == '__main__':
    unittest.main()
