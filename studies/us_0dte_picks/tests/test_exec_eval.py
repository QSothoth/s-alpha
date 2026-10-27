"""Execution rule timing on hand-built option bars (mechanics only, not market data)."""
import unittest
from datetime import datetime, timedelta

from custody.evaluate import PRIMARY_FILL
from custody.marketdata import Bar
from custody.models import ET
from studies.us_0dte_picks.exec_eval import Path_, improvement, run_rule

OPEN = datetime(2026, 9, 14, 9, 30, tzinfo=ET)


def bars(prices):
    """Zero-range bars, so every executable price equals the close."""
    return {m: Bar('US.X', OPEN + timedelta(minutes=m), p, p, p, p, 10.0) for m, p in prices.items()}


class ExecRuleTests(unittest.TestCase):
    def path(self, prices, side, start=0, end=60):
        return Path_(bars(prices), side, start, end, PRIMARY_FILL)

    def test_trailing_sell_fills_on_the_bar_after_the_pullback(self):
        prices = {1: 1.0, 2: 1.5, 3: 2.0, 4: 1.7, 5: 1.55, 6: 1.5}     # peak 2.0; -20% = 1.6 reached at minute 5
        p = self.path(prices, 'SELL')
        self.assertEqual(p.window[0][1], 1.0)                           # arrival: first bar after the start
        self.assertEqual(run_rule(p, 'trail', .20, 1.0), (1.5, False))  # decided on 5, filled on 6

    def test_trailing_buy_waits_for_the_rebound(self):
        prices = {1: 1.0, 2: 0.8, 3: 0.6, 4: 0.7, 5: 0.75, 6: 0.8}      # low 0.6; +20% = 0.72 reached at minute 5
        self.assertEqual(run_rule(self.path(prices, 'BUY'), 'trail', .20, 1.0), (0.8, False))

    def test_limit_fills_inside_the_bar_at_the_limit(self):
        prices = {1: 1.0, 2: 1.02, 3: 1.06, 4: 1.2}
        self.assertEqual(run_rule(self.path(prices, 'SELL'), 'limit', .05, 1.0), (1.05, False))

    def test_unfilled_rules_are_forced_at_the_end_and_half_averages(self):
        prices = {m: 1.0 + m / 100 for m in range(1, 61)}               # steady rise: a sell trail never triggers
        p = self.path(prices, 'SELL')
        self.assertEqual(run_rule(p, 'trail', .20, 1.01), (1.6, False))
        self.assertEqual(run_rule(p, 'half', .20, 1.01), ((1.01 + 1.6) / 2, False))
        gappy = {1: 1.0, 2: 1.1, 50: 1.2, 70: 1.3}                      # no trade within 2 minutes of 60
        self.assertEqual(run_rule(self.path(gappy, 'SELL'), 'trail', .20, 1.0), (1.3, True))

    def test_twap_guard_buys_the_rest_once_the_price_runs_away(self):
        prices = {1: 1.0, 2: 1.0, 3: 1.25, 4: 1.3, 5: 1.4}             # +20% guard trips on minute 3
        p = self.path(prices, 'BUY', end=4)
        price, late = run_rule(p, 'twap_guard', .20, 1.0)
        # four slices of 1/4: minutes 1 and 2 at 1.0, the remaining half at minute 4 (1.3)
        self.assertAlmostEqual(price, 0.25 + 0.25 + 0.5 * 1.3)
        self.assertFalse(late)
        flat = {m: 1.0 for m in range(1, 5)}
        self.assertEqual(run_rule(self.path(flat, 'BUY', end=4), 'twap_guard', .20, 1.0), (1.0, False))

    def test_front_twap_sells_within_the_first_minutes(self):
        prices = {m: float(m) for m in range(1, 61)}
        self.assertEqual(run_rule(self.path(prices, 'SELL'), 'front_twap', 15, 1.0), (8.0, False))

    def test_single_fill_timing_rules(self):
        prices = {m: 1.0 for m in range(1, 61)}
        prices.update({30: 0.9, 31: 0.95})
        self.assertEqual(run_rule(self.path(prices, 'BUY'), 'at_fraction', .5, 1.0), (0.95, False))  # due at minute 30.5
        run = {1: 1.0, 2: 1.05, 3: 1.25, 4: 1.3, 60: 0.5}               # +20% reached on 3: buy on 4, not at the end
        self.assertEqual(run_rule(self.path(run, 'BUY'), 'guard_wait', .20, 1.0), (1.3, False))
        calm = {1: 1.0, 2: 1.05, 60: 0.5}
        self.assertEqual(run_rule(self.path(calm, 'BUY'), 'guard_wait', .20, 1.0), (0.5, False))
        drop = {1: 1.0, 2: 0.85, 3: 0.8, 60: 1.5}                        # -10% reached on 2: sell on 3
        self.assertEqual(run_rule(self.path(drop, 'SELL'), 'guard_wait', .10, 1.0), (0.8, False))

    def test_improvement_sign(self):
        self.assertAlmostEqual(improvement('BUY', 1.0, 0.9), 0.1)
        self.assertAlmostEqual(improvement('SELL', 1.0, 0.9), -0.1)


class KRuleTests(unittest.TestCase):
    """EXEC4 rules on a hand-built underlying path (CALL, so signed = price)."""

    def data(self, closes):
        from custody.dataset import Case, CaseData
        from custody.tests.helpers import path_bars, session
        return CaseData(Case('US.SPY', 'US.SPY260914C600000', '2026-09-14', 'LONG', 600.0), session(),
                        tuple(path_bars(closes)), ())

    def run_k(self, name, closes, option_prices, start=30, end=90, side='BUY'):
        from studies.us_0dte_picks.exec_eval import run_krule, underlying_series
        series = underlying_series(self.data(closes))
        path = Path_(bars(option_prices), side, start, end, PRIMARY_FILL)
        return run_krule(path, name, series, path.window[0][1], start)

    def test_kb1_buys_on_the_first_up_close_after_touching_vwap(self):
        closes = [600 + i * 0.1 for i in range(40)] + [601.0, 600.4, 600.2, 600.3] + [600.3] * 346
        options = {m: 2.0 - m / 1000 for m in range(31, 91)}
        price, late = self.run_k('KB1', closes, options)
        self.assertEqual((price, late), (options[45], False))   # touched by minute 43, up close at 44, filled at 45

    def test_ks3_sells_when_the_ten_bar_low_breaks(self):
        closes = [600 + i * 0.05 for i in range(50)] + [602.5, 600.0] + [600.0] * 338
        options = {m: 1.0 for m in range(31, 91)}
        options[53] = 0.8
        self.assertEqual(self.run_k('KS3', closes, options, side='SELL'), (0.8, False))  # break on 52, sell on 53

    def test_kb3_buys_at_arrival_when_not_extended(self):
        closes = [600.0] * 390
        options = {m: 1.0 + m / 100 for m in range(31, 91)}
        self.assertEqual(self.run_k('KB3', closes, options), (options[31], False))



class HumanOverlayTests(unittest.TestCase):
    def overlay(self, prices, side, start, spike=.10, end=60):
        from studies.us_0dte_picks.exec_eval import base_bar, human_overlay
        path = Path_(bars(prices), side, start, end, PRIMARY_FILL)
        arrival = path.window[0][1]
        return human_overlay(path, base_bar(path, 'immediate'), arrival, spike)

    def test_opening_buffer_moves_the_fill_to_0935(self):
        prices = {m: 1.0 for m in range(1, 61)}
        self.assertEqual(self.overlay(prices, 'SELL', 0), (5, 1.0, False))

    def test_no_dumping_into_a_flush_waits_for_the_first_bounce(self):
        prices = {m: 1.0 for m in range(1, 61)}
        prices.update({17: 1.0, 18: 0.95, 19: 0.9, 20: 0.85, 21: 0.84, 22: 0.86, 23: 0.88})
        # sell intended on 21 (start 20); the 3 bars before fell 15%; first up bar is 22, so sell on 23
        self.assertEqual(self.overlay(prices, 'SELL', 20), (23, 0.88, False))

    def test_protection_and_wait_limit(self):
        prices = {m: 1.0 for m in range(1, 61)}
        prices.update({17: 1.0, 18: 0.9, 19: 0.85, 20: 0.85, 21: 0.84, 22: 0.6, 23: 0.55})
        self.assertEqual(self.overlay(prices, 'SELL', 20)[:2], (23, 0.55))   # 0.6 <= 0.84 x 0.8 on 22: sell on 23
        slide = {m: 1.0 for m in range(1, 61)}
        slide.update({17: 1.0, 18: 0.9, 19: 0.85, 20: 0.84, 21: 0.83, 22: 0.82, 23: 0.81, 24: 0.80, 25: 0.79,
                      26: 0.78, 27: 0.78})
        self.assertEqual(self.overlay(slide, 'SELL', 20), (26, 0.78, False))  # no bounce in 5 minutes: sell on 26

    def test_buy_does_not_chase_a_spike(self):
        prices = {m: 1.0 for m in range(1, 61)}
        prices.update({17: 1.0, 18: 1.1, 19: 1.2, 20: 1.25, 21: 1.26, 22: 1.22, 23: 1.21})
        self.assertEqual(self.overlay(prices, 'BUY', 20), (23, 1.21, False))



class PlaybookTests(unittest.TestCase):
    """EXEC7 scenario playbook on hand-built paths (CALL, signed = price)."""

    def run_play(self, closes, side, start=60, end=120, options=None, zero_dte=False):
        from custody.dataset import Case, CaseData
        from custody.tests.helpers import path_bars, session
        from studies.us_0dte_picks.exec_eval import run_playbook, underlying_series
        data = CaseData(Case('US.SPY', 'US.SPY260914C600000', '2026-09-14', 'LONG', 600.0), session(),
                        tuple(path_bars(closes)), ())
        options = options or {m: 1.0 for m in range(1, 391)}
        path = Path_(bars(options), side, start, end, PRIMARY_FILL)
        return run_playbook(path, underlying_series(data), path.window[0][1], start, zero_dte)

    def test_sell_holds_a_trend_and_leaves_below_ema9(self):
        closes = [600 + 0.05 * i for i in range(80)] + [604.0 - 0.3 * i for i in range(310)]   # steady rise, then a fall
        m, price, late, trigger = self.run_play(closes, 'SELL')
        self.assertIn(trigger, ('with', 'stretched'))      # an hour of steady rise sits more than one OR above VWAP
        self.assertTrue(80 <= m <= 83)                     # held through the rise, sold right after it turned

    def test_sell_into_a_spike_on_the_first_bar_that_fails_to_rise(self):
        closes = [600.0] * 60 + [600.5, 601.5, 602.5, 603.5, 603.4] + [603.4] * 325
        m, price, late, trigger = self.run_play(closes, 'SELL', start=62)
        self.assertEqual((trigger, m), ('spike_up', 66))   # 62-64 still rising, 65 fails, fill on 66

    def test_urgency_forces_a_fill_late_in_the_window(self):
        closes = [600 + 0.05 * i for i in range(390)]      # steady trend: a sell keeps holding
        m, price, late, trigger = self.run_play(closes, 'SELL', start=60, end=120)
        self.assertEqual(trigger, 'urgency')
        self.assertLess(m, 120)


class Playbook2Tests(unittest.TestCase):
    """EXEC8 playbook v2 timing on hand-built paths (CALL, signed = price); closes[i] is minute i + 1."""

    def run_play(self, closes, side, start=60, end=120, options=None, zero_dte=False):
        from custody.dataset import Case, CaseData
        from custody.tests.helpers import path_bars, session
        from studies.us_0dte_picks.exec_eval import run_playbook2, underlying_series
        data = CaseData(Case('US.SPY', 'US.SPY260914C600000', '2026-09-14', 'LONG', 600.0), session(),
                        tuple(path_bars(closes)), ())
        options = options or {m: 1.0 for m in range(1, 391)}
        path = Path_(bars(options), side, start, end, PRIMARY_FILL)
        return run_playbook2(path, underlying_series(data), path.window[0][1], start, zero_dte)

    def test_sell_into_a_spike_on_the_first_bar_that_fails_to_rise(self):
        closes = [600.0] * 60 + [600.5, 601.5, 602.5, 603.5, 603.4] + [603.4] * 325
        m, price, late, trigger = self.run_play(closes, 'SELL', start=62)
        self.assertEqual((trigger, m), ('spike_up', 66))   # 62-64 still rising, 65 fails, fill on 66

    def test_sell_into_strength_in_a_trend_at_the_first_pause_after_a_high(self):
        closes = [600 + 0.05 * i for i in range(80)] + [603.95] + [604.0 + 0.05 * i for i in range(309)]
        m, price, late, trigger = self.run_play(closes, 'SELL')
        self.assertIn(trigger, ('with', 'stretched'))
        self.assertEqual(m, 82)                            # minute 80 a new high, 81 fails to rise, fill on 82

    def test_sell_leaves_weakness_at_once_instead_of_waiting_for_a_bounce(self):
        closes = [600.0 + 0.01 * i for i in range(60)] + [600.6 - 0.3 * i for i in range(330)]
        m, price, late, trigger = self.run_play(closes, 'SELL', start=70)
        self.assertEqual(m, 71)                            # first judged bar already weak: sell on the next one
        self.assertIn(trigger, ('stop_low', 'spike_down', 'sunk', 'against', 'lose'))

    def test_sell_stops_below_the_day_low(self):
        closes = [600 + 0.05 * i for i in range(90)] + [599.5] * 300    # a trend that never pauses, then a break
        m, price, late, trigger = self.run_play(closes, 'SELL', start=60)
        self.assertEqual((trigger, m), ('stop_low', 92))   # held through the trend; minute 91 closes under the day low

    def test_buy_guard_is_ten_percent(self):
        rising = {m: 1.0 + 0.011 * max(0, m - 61) for m in range(1, 391)}
        up = [600.0] * 60 + [600.0 + 0.5 * i for i in range(330)]   # a runaway spike never pulls back to EMA9
        m, price, late, trigger = self.run_play(up, 'BUY', start=64, options=rising)
        arrival = rising[65]
        self.assertEqual(trigger, 'protect')
        self.assertGreaterEqual(price, arrival * 1.10)
        self.assertLess(price, arrival * 1.10 + 0.011 * 2)    # bought on the bar after the guard, not at +20%

    def test_buy_after_a_spike_waits_for_a_pullback_to_ema9(self):
        closes = ([600.0] * 60 + [601.0, 602.0, 603.0, 602.8, 602.6, 602.4, 602.2, 602.0, 601.8, 601.6, 601.4,
                                  601.2, 601.3] + [601.3] * 317)
        m, price, late, trigger = self.run_play(closes, 'BUY', start=62)
        self.assertGreaterEqual(m, 66)                     # not on the first red bar (64): only once back near EMA9


if __name__ == '__main__':
    unittest.main()
