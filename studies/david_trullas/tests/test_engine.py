"""Execution-timing tests for the David Trullas minute engine (synthetic bars only)."""
import unittest

import numpy as np

from studies.david_trullas import engine as E


def make_px(days):
    """days: list of (date, rows) with rows = [(minute_ET, o, h, l, c, v)]."""
    t, day, mins, o, h, l, c, v, dates = [], [], [], [], [], [], [], [], []
    for d, (date, rows) in enumerate(days):
        dates.append(date)
        for m, *bar in rows:
            t.append(np.datetime64(date + 'T00:00') + np.timedelta64(m, 'm'))
            day.append(d); mins.append(m)
            o.append(bar[0]); h.append(bar[1]); l.append(bar[2]); c.append(bar[3]); v.append(bar[4])
    a = np.array
    return dict(t=a(t), day=a(day), mins=a(mins), dates=dates, o=a(o, float), h=a(h, float), l=a(l, float),
                c=a(c, float), v=a(v, float))


def flat_day(date, base=100.0, n0=480, n1=960):
    return (date, [(m, base, base + .01, base - .01, base, 1000) for m in range(n0, n1)])


class Manage(unittest.TestCase):
    def setUp(self):
        rows = [(m, 100, 100.01, 99.99, 100, 1000) for m in range(540, 600)]
        self.date = '2025-01-02'
        self.rows = rows

    def px(self, bars):
        rows = list(self.rows)
        for k, b in enumerate(bars):
            rows.append((600 + k,) + b)
        rows += [(m, 100, 100.01, 99.99, 100, 1000) for m in range(600 + len(bars), 960)]
        return make_px([(self.date, rows)])

    def test_stop_before_target_same_bar(self):
        px = self.px([(100, 100, 100, 100, 1), (100, 102, 98, 100, 1)])
        i = 60                     # entry bar (minute 600)
        cfg = E.Cfg(add_pts=0)
        k, fill, added, avg, why = E.manage(px, i, 1, 100.0, 99.0, 101.0, 1, cfg, len(px['c']))
        self.assertEqual((k, why, fill), (61, 'stop', 99.0))

    def test_entry_bar_not_managed(self):
        # the entry bar itself dips below the stop: ignored, managed from the next bar on
        px = self.px([(100, 100, 98, 100, 1), (100, 101.5, 99.5, 101, 1)])
        cfg = E.Cfg(add_pts=0)
        k, fill, added, avg, why = E.manage(px, 60, 1, 100.0, 99.0, 101.0, 1, cfg, len(px['c']))
        self.assertEqual((k, why, fill), (61, 'target', 101.0))

    def test_intrabar_entry_bar_low_below_stop_is_a_loss(self):
        px = self.px([(100, 100.5, 98.5, 100.2, 1), (100.2, 102, 100.1, 101.5, 1)])
        cfg = E.Cfg()
        k, fill, added, avg, why = E.manage(px, 60, 1, 100.0, 99.0, 101.0, 1, cfg, len(px['c']), intrabar=True)
        self.assertEqual((k, why, fill), (60, 'stop', 99.0))

    def test_gap_through_stop_fills_at_open(self):
        px = self.px([(100, 100, 100, 100, 1), (98.5, 99, 98, 98.8, 1)])
        cfg = E.Cfg(add_pts=0)
        k, fill, added, avg, why = E.manage(px, 60, 1, 100.0, 99.0, 103.0, 1, cfg, len(px['c']))
        self.assertEqual((why, fill), ('stop', 98.5))

    def test_breakeven_from_next_bar(self):
        # bar 61 reaches +1R then falls back below entry in the same bar: BE not active yet, original stop holds;
        # bar 62 dips to entry: BE stop (entry + 1.5 NQ pts) hit
        px = self.px([(100, 100, 100, 100, 1), (100, 101.2, 99.5, 100.5, 1), (100.5, 100.6, 100.0, 100.2, 1)])
        cfg = E.Cfg(add_pts=0, be_at=1.0)
        k, fill, added, avg, why = E.manage(px, 60, 1, 100.0, 99.0, 105.0, 1, cfg, len(px['c']))
        self.assertEqual((k, why), (62, 'stop'))
        self.assertAlmostEqual(fill, 100.0 + 1.5 / E.NQ_PER_QQQ)

    def test_add_moves_stop_to_weighted_cost(self):
        add = 30 / E.NQ_PER_QQQ
        px = self.px([(100, 100, 100, 100, 1), (100, 100 + add + .01, 100, 100 + add, 1),
                      (100 + add, 100 + add, 100, 100.1, 1)])
        cfg = E.Cfg(add_pts=30, be_at=99)
        k, fill, added, avg, why = E.manage(px, 60, 1, 100.0, 99.0, 110.0, 3, cfg, len(px['c']))
        self.assertEqual((k, added, why), (62, 3, 'stop'))
        self.assertAlmostEqual(avg, 100 + add / 2)
        self.assertAlmostEqual(fill, avg + 1.5 / E.NQ_PER_QQQ)


class NoLookahead(unittest.TestCase):
    def test_setups_unchanged_by_future_bars(self):
        rng = np.random.default_rng(3)
        days = []
        for k, date in enumerate(['2025-01-02', '2025-01-03', '2025-01-06']):
            p, rows = 100.0, []
            for m in range(480, 960):
                r = rng.normal(0, .05)
                o = p; p = p + r
                rows.append((m, o, max(o, p) + abs(rng.normal(0, .02)), min(o, p) - abs(rng.normal(0, .02)), p,
                             float(rng.integers(100, 5000))))
            days.append((date, rows))
        px = make_px(days)
        for cfg in (E.Cfg(trig='vol', zone='either', zone_tol=.01, windows=((480, 960),)),
                    E.Cfg(trig='macd', min_range=5, windows=((480, 960),)),
                    E.Cfg(trig='macd', tf=5, piv=1, min_range=2, windows=((480, 960),)),
                    E.Cfg(trig='open', min_range=2, open_drop=5, open_lows=2),
                    E.Cfg(trig='macd+open', min_range=2, open_drop=5, open_lows=2, windows=((480, 960),)),
                    E.Cfg(trig='mfail', min_range=2, mfail_gap=0.5, windows=((480, 960),)),
                    E.Cfg(trig='macd', min_range=2, macd_drop=5, windows=((560, 960),))):
            d = max((1, 2), key=lambda d: len(E.setups(E.Market(px), d, cfg)))
            full = E.setups(E.Market(px), d, cfg)
            self.assertTrue(full, cfg.trig)
            cut_bar = full[len(full) // 2][0]
            cut = {k: (v[:cut_bar + 1] if k != 'dates' else v) for k, v in px.items()}
            part = E.setups(E.Market(cut), d, cfg)
            self.assertEqual([x for x in full if x[0] <= cut_bar], part)

    def test_open_sweep_enters_on_the_bullish_sweep_bar(self):
        rows = [(m, 100, 100.05, 99.95, 100, 1000) for m in range(480, 570)]
        rows += [(570, 99.7, 100.02, 99.65, 99.9, 9000),     # 09:30 sweeps the 99.95 pre-open low, closes bullish
                 (571, 99.9, 100.3, 99.85, 100.2, 5000)]
        rows += [(m, 100.2, 100.25, 100.15, 100.2, 1000) for m in range(572, 960)]
        px = make_px([('2025-01-02', rows)])
        cfg = E.Cfg(trig='open', open_sets='B', min_range=1)
        got = E.setups(E.Market(px), 0, cfg)
        self.assertEqual(len(got), 1)
        i, entry, stop, top, kind, units, intrabar = got[0]
        self.assertEqual((px['mins'][i], kind, intrabar), (570, 'open_B', False))
        self.assertAlmostEqual(entry, 99.9)
        self.assertAlmostEqual(stop, 99.65 - E.TICK)

    def test_macd_entry_is_stop_order_above_fib(self):
        rng = np.random.default_rng(5)
        rows, p = [], 100.0
        for m in range(480, 960):
            o = p; p = p + rng.normal(0, .05)
            rows.append((m, o, max(o, p) + .01, min(o, p) - .01, p, float(rng.integers(100, 5000))))
        px = make_px([('2025-01-02', rows)])
        cfg = E.Cfg(trig='macd', min_range=5, windows=((480, 960),))
        for i, entry, stop, top, kind, units, intrabar in E.setups(E.Market(px), 0, cfg):
            low = stop + E.TICK
            self.assertTrue(intrabar)
            self.assertGreaterEqual(px['h'][i], entry - 1e-9)                 # the bar traded through the order
            self.assertGreaterEqual(entry, low + cfg.fib_in * (top - low))    # never filled below the fib level
            self.assertTrue(1 <= units <= 4)


if __name__ == '__main__':
    unittest.main()
