"""Timing tests for the replication stages: weekly EMA as charted mid-week, 5-minute triggers, previous-day masks."""
import unittest

import numpy as np

from studies.martin_luk import replicate as R
from studies.martin_luk.intraday import NB


def bars(rows):
    """rows: (open, high, low) for the first bars of a day; the rest are NaN."""
    o5, h5, l5 = (np.full(NB, np.nan) for _ in range(3))
    for b, (o, h, l) in enumerate(rows):
        o5[b], h5[b], l5[b] = o, h, l
    return o5, h5, l5


class TriggerTests(unittest.TestCase):
    def test_pdh_break_fills_at_the_prior_high_with_low_of_day_so_far(self):
        o5, h5, l5 = bars([(10.0, 10.2, 9.8), (10.1, 10.6, 10.0), (10.5, 10.9, 10.4)])
        self.assertEqual(R.first_trigger(o5, h5, l5, 'E2', pdh=10.5, e9p=9.0), (1, 10.5, 9.8))

    def test_open_above_the_prior_high_waits_for_the_first_bar_high(self):
        o5, h5, l5 = bars([(11.0, 11.2, 10.8), (11.1, 11.1, 10.7), (11.0, 11.4, 10.9)])
        self.assertEqual(R.first_trigger(o5, h5, l5, 'E2', pdh=10.5, e9p=9.0), (2, 11.2, 10.7))

    def test_pullback_needs_a_dip_then_a_break_of_the_previous_bar_high(self):
        o5, h5, l5 = bars([(10.0, 10.1, 9.6), (9.7, 9.8, 9.4), (9.5, 9.7, 9.45), (9.7, 9.9, 9.6)])
        # dip below e9 = 9.5 on bar 1; bar 2 does not exceed bar 1's high; bar 3 does
        self.assertEqual(R.first_trigger(o5, h5, l5, 'E4', pdh=11.0, e9p=9.5), (3, 9.7, 9.4))

    def test_handshake_dips_to_the_higher_of_prior_high_and_ema9(self):
        o5, h5, l5 = bars([(11.0, 11.2, 10.6), (10.6, 10.7, 10.45), (10.5, 10.8, 10.5)])
        # gap above the prior high 10.5 (EMA9 9.8): the fade to 10.45 counts, bar 2 breaks bar 1's high
        self.assertEqual(R.first_trigger(o5, h5, l5, 'E11', pdh=10.5, e9p=9.8), (2, 10.7, 10.45))
        self.assertIsNone(R.first_trigger(o5, h5, l5, 'E4', pdh=10.5, e9p=9.8))

    def test_skipping_the_first_bars_moves_the_trigger_but_not_the_low_of_day(self):
        rows = [(10.0, 10.6, 9.8)] + [(10.4, 10.5, 10.3)] * 5 + [(10.4, 10.7, 10.35)]
        o5, h5, l5 = bars(rows)
        self.assertEqual(R.first_trigger(o5, h5, l5, 'E2', pdh=10.5, e9p=9.0), (0, 10.5, 9.8))
        self.assertEqual(R.first_trigger(o5, h5, l5, 'E2', pdh=10.5, e9p=9.0, b_start=6), (6, 10.5, 9.8))

    def test_no_trigger_returns_none(self):
        o5, h5, l5 = bars([(10.0, 10.2, 9.9), (10.1, 10.3, 10.0)])
        self.assertIsNone(R.first_trigger(o5, h5, l5, 'E2', pdh=10.5, e9p=9.0))


def tiny(rows, adr=8.0, to20=100e6, turnover=None):
    """A one-stock panel: rows of (open, high, low, close)."""
    a = np.array(rows, float)
    T = len(a)
    A = {k: a[:, i:i + 1] for i, k in enumerate(('open', 'high', 'low', 'close'))}
    A['adr'] = np.full((T, 1), adr)
    A['to20'] = np.full((T, 1), to20)
    A['turnover'] = np.full((T, 1), to20) if turnover is None else np.array(turnover, float)[:, None]
    return A


class EntryTests(unittest.TestCase):
    def test_close_entry_stop_modes(self):
        # cap = min(5%, 0.5 x 8%) = 4%; the day ran from 9.0 to close 10.0, so the low is 10% away
        A = tiny([(9.5, 9.6, 9.4, 9.5), (9.0, 10.1, 9.0, 10.0)])
        m = np.array([[False], [True]])
        self.assertEqual(R.entries_close_stop(A, m, 'skip'), [[], []])
        (e,) = R.entries_close_stop(A, m, 'cap')[1]
        self.assertAlmostEqual(e[4], 9.6)                 # stop moved up to close x (1 - 4%)
        (e,) = R.entries_close_stop(A, m, 'half')[1]
        self.assertAlmostEqual(e[4], 9.8)
        B = tiny([(9.5, 9.6, 9.4, 9.5), (9.8, 10.1, 9.8, 10.0)])   # low 2% away: the low itself
        (e,) = R.entries_close_stop(B, m, 'cap')[1]
        self.assertAlmostEqual(e[4], 9.8)

    def test_stop_cap_ceiling_and_floor(self):
        A = tiny([(9.5, 9.6, 9.4, 9.5), (9.0, 10.1, 9.0, 10.0)], adr=10.0)   # cap min(5%, 5%) = 5%
        m = np.array([[False], [True]])
        (e,) = R.entries_close_stop(A, m, 'cap', cap_max=.03)[1]
        self.assertAlmostEqual(e[4], 9.7)                                   # ceiling 3%
        B = tiny([(9.5, 9.6, 9.4, 9.5), (9.97, 10.1, 9.97, 10.0)], adr=10.0)  # the low is only 0.3% away
        (e,) = R.entries_close_stop(B, m, 'cap', stop_min=.01)[1]
        self.assertAlmostEqual(e[4], 9.9)                                   # floor 1%

    def test_short_stop_is_capped_and_can_be_sized_down(self):
        A = tiny([(10, 10, 10, 10), (11.0, 11.0, 9.9, 10.0)])      # high 10% above the close; cap 4%
        m = np.array([[False], [True]])
        (e,) = R.entries_short_capped(A, m)[1]
        self.assertEqual(e[2], -1)
        self.assertAlmostEqual(e[4], 10.4)
        self.assertIsNone(e[7])
        (e,) = R.entries_short_capped(A, m, size_mult=2.0)[1]
        self.assertAlmostEqual(e[7], .08)                           # sized as if the stop were twice as far

    def test_ep_needs_gap_volume_and_holding_the_open(self):
        rows = [(10, 10, 10, 10), (11.0, 11.5, 10.8, 11.2), (10.2, 10.3, 10.0, 10.1), (11.5, 11.6, 10.9, 11.0)]
        A = tiny(rows, adr=4.0, to20=100e6, turnover=[1e8, 3e8, 1e8, 3e8])
        pool = np.ones((4, 1), bool)
        # day 1: gap 10% >= 5%, volume 3x, close >= open -> EP; day 3: gap from 10.1 to 11.5 but closes below the open
        self.assertEqual(R.ep_signal(A, pool)[:, 0].tolist(), [False, True, False, False])
        self.assertEqual(R.ep_signal(A, pool, gap_min=.12)[:, 0].tolist(), [False] * 4)
        self.assertEqual(R.ep_signal(A, pool, hold_open=False)[:, 0].tolist(), [False, True, False, True])

    def test_climax_needs_the_run_and_a_52_week_dollar_volume_high(self):
        T = 270
        c = np.full(T, 10.0)
        c[-10:] = np.linspace(11, 14, 10)                  # +40% over the last 10 days
        to = np.full(T, 1e8)
        to[-2], to[-1] = 3e8, 2e8                         # the 52-week high is the second-to-last day
        A = {'close': c[:, None], 'turnover': to[:, None]}
        self.assertEqual(np.flatnonzero(R.climax(A, .30)[:, 0]).tolist(), [T - 2])
        self.assertFalse(R.climax(A, .50).any())

    def test_extension_signal_uses_adr_multiples_above_the_ema9(self):
        A = {'close': np.array([[11.0], [12.5]]), 'e9': np.array([[10.0], [10.0]]), 'adr': np.array([[6.0], [6.0]])}
        self.assertEqual(R.named_signal(A, None, 'ext2')[:, 0].tolist(), [False, True])   # needs >= 11.2

    def test_index_risk_scale_is_known_the_next_day(self):
        T = 80
        c = np.linspace(10, 20, T)[:, None]                 # steady rise: index far above its EMA21 late on
        A = {'close': c}
        pool = np.ones((T, 1), bool)
        s = R.index_risk_scale(A, pool, pb=1.0, ext=.5, ext_at=.05)
        self.assertTrue(np.isnan(s[0]))                      # day 0 has no previous close (the engine skips NaN)
        self.assertEqual(s[-1], .5)                          # a 10 -> 20 straight line ends > 5% above its EMA21
        self.assertTrue(np.all(np.isin(s[1:], [1.0, .5])))

    def test_prior_high_excludes_today(self):
        h = np.array([[10.0], [12.0], [11.0], [np.nan], [9.0]])
        self.assertEqual(R.prior_high(h, 2)[:, 0].tolist()[1:], [10.0, 12.0, 12.0, 11.0])
        self.assertEqual(R.prior_low(h, 2)[:, 0].tolist()[1:], [10.0, 10.0, 11.0, 11.0])


class PriorityTests(unittest.TestCase):
    def test_theme_priority_puts_names_that_move_together_first(self):
        rng = np.random.default_rng(0)
        T = 70
        common = rng.normal(0, .03, T)
        r = np.column_stack([common + rng.normal(0, .005, T), rng.normal(0, .03, T), common + rng.normal(0, .005, T)])
        c = 10 * np.cumprod(1 + r, axis=0)
        entries = [[] for _ in range(T)]
        entries[-1] = [(-3e8, 0, 1, 1.0, .9, 'x'), (-2e8, 1, 1, 1.0, .9, 'x'), (-1e8, 2, 1, 1.0, .9, 'x')]
        out = R.theme_priority({'close': c}, entries)[-1]
        order = [e[1] for e in sorted(out, key=lambda e: e[0])]
        self.assertEqual(order, [0, 2, 1])                # the pair first (turnover order inside), the loner last
        self.assertEqual(R.theme_priority({'close': c}, entries)[5], [])


class RotationTests(unittest.TestCase):
    def test_rotation_only_uses_finished_outcomes(self):
        # rising prices; with lag 2 and lookback 3, day d looks at signals from days d-4 .. d-2
        c = np.array([[10.0], [10.5], [11.0], [11.5], [12.0], [12.5], [13.0]])
        A = {'close': c}
        y = np.zeros((7, 1), bool)
        x = np.zeros((7, 1), bool)
        x[[0, 6], 0] = True
        keep = R.rotate(A, {'X': x, 'Y': y}, lookback=3, lag=2)
        self.assertFalse(keep[6, 0])      # day 0 is outside days 2..4: no feedback, family off
        x[5, 0] = True                    # day 5's outcome needs day 7's close: not usable on day 6
        self.assertFalse(R.rotate(A, {'X': x, 'Y': y}, lookback=3, lag=2)[6, 0])
        x[3, 0] = True                    # day 3's outcome uses day 5's close: usable on day 6
        self.assertTrue(R.rotate(A, {'X': x, 'Y': y}, lookback=3, lag=2)[6, 0])


class WeeklyTests(unittest.TestCase):
    def test_inside_week_breakout_fires_once_on_the_first_break(self):
        days = np.array(['2025-01-06', '2025-01-07', '2025-01-13', '2025-01-14', '2025-01-20', '2025-01-21',
                         '2025-01-22'])
        # week 1: 9-12; week 2 (inside): 9.5-11.5; week 3: Mon stays below 11.5, Tue breaks it, Wed breaks again
        rows = [(10, 12, 9, 11), (11, 11.5, 10, 10.5), (10.5, 11.5, 9.5, 10), (10, 11, 9.8, 10.8),
                (10.8, 11.2, 10.5, 11), (11, 11.9, 10.9, 11.8), (11.8, 12.4, 11.6, 12.2)]
        a = np.array(rows, float)
        A = {'days': days, 'open': a[:, :1], 'high': a[:, 1:2], 'low': a[:, 2:3], 'close': a[:, 3:4]}
        w = R.weekly_breakouts(A)
        self.assertEqual(w['EW1'][:, 0].tolist(), [False, False, False, False, False, True, False])

    def test_weekly_pin_bar(self):
        days = np.array(['2025-01-06', '2025-01-07', '2025-01-13'])
        # week 1: open 10, low 8, high 10.3, close 10.2 -> lower wick 2 >= 2 x body 0.2, close in the top third
        rows = [(10, 10.1, 8, 9), (9, 10.3, 9, 10.2), (10.2, 10.5, 10.1, 10.4)]
        a = np.array(rows, float)
        A = {'days': days, 'open': a[:, :1], 'high': a[:, 1:2], 'low': a[:, 2:3], 'close': a[:, 3:4]}
        self.assertEqual(R.weekly_breakouts(A)['EW2'][:, 0].tolist(), [False, False, True])


class MaskTests(unittest.TestCase):
    def test_prev_shifts_one_day(self):
        x = np.array([[True], [False], [True]])
        self.assertEqual(R.prev(x)[:, 0].tolist(), [False, True, False])

    def test_weekly_ema_uses_completed_weeks_plus_the_running_close(self):
        days = np.array(['2025-01-06', '2025-01-07', '2025-01-13', '2025-01-14'])     # Mon, Tue, Mon, Tue
        c = np.array([[10.0], [12.0], [14.0], [16.0]])
        e = R.weekly_ema(c, days, 3)                                                   # alpha = 0.5
        self.assertEqual(e[:, 0].tolist(), [10.0, 12.0, .5 * 14 + .5 * 12, .5 * 16 + .5 * 12])


if __name__ == '__main__':
    unittest.main()


def short_panel(close, high=None, low=None):
    """Weekday panel for the short masks: closes (days x names), EMAs and the tight flag as market_arrays does."""
    import datetime as dt
    c = np.asarray(close, float)
    h = c * 1.01 if high is None else np.asarray(high, float)
    l = c * .99 if low is None else np.asarray(low, float)
    d, days = dt.date(2024, 1, 1), []
    while len(days) < len(c):
        if d.weekday() < 5:
            days.append(d.isoformat())
        d += dt.timedelta(days=1)
    A = dict(close=c, high=h, low=l, days=np.array(days))
    A['e9'], A['e21'], A['e50'] = R.luk.ema(c, 9), R.luk.ema(c, 21), R.luk.ema(c, 50)
    A['tight'] = ((h <= R.luk.lag(h)) & (l >= R.luk.lag(l)))
    return A


class ShortTriggerTests(unittest.TestCase):
    def test_z2_fires_on_the_rejected_rally_day_only(self):
        n = 160
        c = np.linspace(100, 50, n)[:, None]
        h, l = c * 1.005, c * .995
        k = n - 3
        A0 = short_panel(c, h, l)
        e21p, e9p = A0['e21'][k - 1, 0], A0['e9'][k - 1, 0]
        h[k, 0], c[k, 0] = e21p * 1.001, e9p * .995             # spikes into the 21 EMA, closes under the 9
        A = short_panel(c, h, l)
        z = R.short_signals(A, np.ones(c.shape, bool))['Z2'][:, 0]
        self.assertTrue(z[k])
        self.assertFalse(z[k - 1] or z[k + 1])

    def test_short_masks_do_not_read_later_bars(self):
        rng = np.random.default_rng(3)
        c = 50 * np.exp(np.cumsum(rng.normal(0, .03, (260, 20)), axis=0))
        h, l = c * (1 + rng.uniform(0, .04, c.shape)), c * (1 - rng.uniform(0, .04, c.shape))
        full = R.short_signals(short_panel(c, h, l), np.ones(c.shape, bool))
        cut = 200
        part = R.short_signals(short_panel(c[:cut + 1], h[:cut + 1], l[:cut + 1]), np.ones((cut + 1, 20), bool))
        for k in full:
            self.assertTrue(np.array_equal(full[k][:cut + 1], part[k]), k)
        self.assertTrue(any(full[k].any() for k in full))

    def test_rejection_at_the_prior_nine_ema_on_a_red_close(self):
        n = 60
        c = np.full((n, 1), 100.0)
        o, h, l = c.copy(), c * 1.005, c * .995
        k = n - 2
        A0 = short_panel(c, h, l)
        e9p = A0['e9'][k - 1, 0]
        o[k, 0], h[k, 0], c[k, 0] = e9p * .999, e9p * 1.004, e9p * .99    # tags the 9, closes red under it
        A = short_panel(c, h, l)
        A['open'] = o
        keep = R.strength_lists
        R.strength_lists = lambda A, pool: {'K9': np.ones(A['close'].shape, bool)}
        try:
            z = R.rejection_shorts(A, np.ones(c.shape, bool))
        finally:
            R.strength_lists = keep
        self.assertEqual(list(np.flatnonzero(z['Z12'][:, 0])), [k])
        self.assertEqual(list(np.flatnonzero(z['Z11'][:, 0])), [k])
        A['open'][k, 0] = c[k, 0] * .99                                     # a green close is not a rejection
        R.strength_lists = lambda A, pool: {'K9': np.ones(A['close'].shape, bool)}
        try:
            self.assertFalse(R.rejection_shorts(A, np.ones(c.shape, bool))['Z12'][k, 0])
        finally:
            R.strength_lists = keep
