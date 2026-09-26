"""Synthetic checks of OR3's frozen clocks, causal boundaries and single entry."""
from dataclasses import replace
from datetime import datetime, timedelta
import unittest

from custody.marketdata import Bar
from custody.models import ET
from studies.us_opening_range.context_signals import context_trades
from studies.us_opening_range.trend_signals import CANDIDATES, trend_trades


OPEN = datetime(2024, 3, 18, 9, 30, tzinfo=ET)


def day(prices=None, opening=OPEN, code='US.NVDA'):
    bars = []
    for index in range(78):
        close = (prices or {}).get(index, 100)
        opening_price = 100 if index == 0 else close
        high = max(101 if index < 6 else close + .1, opening_price, close)
        low = min(99 if index < 6 else close - .1, opening_price, close)
        bars.append(Bar(code, opening + timedelta(minutes=5 * (index + 1)),
                        opening_price, high, low, close, 10, interval='5m'))
    return bars


def history(prices=None):
    rows, opening = [], OPEN
    while len(rows) < 14:
        opening -= timedelta(days=1)
        if opening.weekday() < 5:
            rows.append(day(prices, opening))
    return list(reversed(rows))


class TrendSignalTests(unittest.TestCase):
    def test_or_entry_matches_b30_and_vwap_exit_is_next_close_for_both_sides(self):
        for prices, direction in [({6: 101.2, 7: 101.3, 8: 99, 9: 98.5}, 'LONG'),
                                  ({6: 98.8, 7: 98.7, 8: 101, 9: 101.5}, 'SHORT')]:
            with self.subTest(direction=direction):
                bars, past = day(prices), history()
                output = trend_trades(bars, past)
                self.assertEqual(tuple(output), CANDIDATES)
                trade, baseline = output['O30_VWAP'], context_trades(bars, past)['B30']
                for key in ('direction', 'signal_time', 'signal_price', 'entry_time', 'entry_price'):
                    self.assertEqual(trade[key], baseline[key])
                self.assertEqual(trade['direction'], direction)
                self.assertEqual(trade['exit_decision_time'], bars[8].close_time)
                self.assertEqual(trade['exit_time'], bars[9].close_time)
                self.assertEqual(trade['exit_reason'], 'vwap')
                sign = 1 if direction == 'LONG' else -1
                self.assertAlmostEqual(trade['gross_return'], sign * (bars[9].close / bars[7].close - 1))

    def test_or_fills_past_exit_boundary_before_checking_that_same_close(self):
        bars = day({6: 101.2, 7: 99, 8: 98})
        trade = trend_trades(bars, history())['O30_VWAP']
        self.assertEqual(trade['entry_time'], trade['exit_decision_time'])
        self.assertEqual(trade['entry_price'], 99)
        self.assertEqual(trade['exit_price'], 98)
        self.assertLess(trade['gross_return'], 0)

    def test_trend_has_no_fixed_profit_target_or_sixty_minute_timeout(self):
        prices = {index: 103 + index / 100 for index in range(7, 78)}
        prices[6] = 101.2
        bars = day(prices)
        trade = trend_trades(bars, history())['O30_VWAP']
        self.assertEqual(trade['exit_reason'], 'flatten')
        self.assertEqual(trade['exit_decision_time'], bars[74].close_time)
        self.assertEqual(trade['exit_time'], bars[75].close_time)
        self.assertIsNone(trade['stop'])
        self.assertIsNone(trade['target'])

    def test_or_midpoint_is_not_an_exit_when_price_remains_above_vwap(self):
        prices = {index: 99 for index in range(6)}
        prices[6] = 101.2
        bars = day(prices)
        trade = trend_trades(bars, history())['O30_VWAP']
        self.assertEqual(trade['entry_price'], 100)
        self.assertEqual(trade['exit_reason'], 'flatten')
        self.assertEqual(trade['exit_time'], bars[75].close_time)

    def test_noise_entry_at_ten_and_exit_only_on_half_hour_even_if_fill_crossed(self):
        for sign in (1, -1):
            with self.subTest(sign=sign):
                prices = {5: 100 + sign * 2, 6: 100 - sign, 7: 100 - sign * 2,
                          11: 100 - sign, 12: 100 - sign * 3}
                bars = day(prices)
                trade = trend_trades(bars, history())['N30_TRAIL']
                self.assertEqual(trade['signal_time'], bars[5].close_time)
                self.assertEqual(trade['entry_time'], bars[6].close_time)
                self.assertEqual(trade['exit_decision_time'], bars[11].close_time)
                self.assertEqual(trade['exit_time'], bars[12].close_time)
                self.assertEqual(trade['exit_reason'], 'trail')

    def test_noise_has_no_or_requirement_chase_limit_or_five_minute_entry(self):
        bars = day({5: 100.5})  # Inside the fixed 99..101 opening range.
        self.assertIsNotNone(trend_trades(bars, history())['N30_TRAIL'])
        bars = day({11: 105})  # Far beyond an OR width / 4 chase limit.
        trade = trend_trades(bars, history())['N30_TRAIL']
        self.assertEqual(trade['signal_time'], bars[11].close_time)
        bars = day({6: 105})  # 10:05 is not an entry grid point.
        self.assertIsNone(trend_trades(bars, history())['N30_TRAIL'])
        bars = day({11: 101})
        bars[:6] = [replace(bar, open=100, high=100, low=100, close=100) for bar in bars[:6]]
        output = trend_trades(bars, history())
        self.assertIsNone(output['O30_VWAP'])
        self.assertIsNotNone(output['N30_TRAIL'])

    def test_noise_dynamic_history_boundary_can_exit_without_crossing_vwap(self):
        for sign in (1, -1):
            with self.subTest(sign=sign):
                bars = day({5: 100 + sign, 11: 100 + sign * 1.5})
                past = history({11: 100 + sign * 2})
                trade = trend_trades(bars, past)['N30_TRAIL']
                self.assertEqual(trade['signal_time'], bars[5].close_time)
                self.assertEqual(trade['exit_decision_time'], bars[11].close_time)
                self.assertEqual(trade['exit_reason'], 'trail')

    def test_noise_vwap_can_exit_while_still_outside_history_boundary(self):
        for sign in (1, -1):
            with self.subTest(sign=sign):
                prices = {index: 100 + sign * 10 for index in range(6, 11)}
                prices.update({5: 100 + sign, 11: 100 + sign * 2})
                bars = day(prices)
                trade = trend_trades(bars, history())['N30_TRAIL']
                self.assertEqual(trade['exit_decision_time'], bars[11].close_time)
                self.assertEqual(trade['exit_reason'], 'trail')

    def test_noise_history_same_clock_previous_close_and_past_only(self):
        bars = day({5: 101})
        self.assertIsNotNone(trend_trades(bars, history())['N30_TRAIL'])
        self.assertIsNone(trend_trades(bars, history({5: 102}))['N30_TRAIL'])
        self.assertIsNotNone(trend_trades(bars, history({6: 110}))['N30_TRAIL'])
        self.assertIsNone(trend_trades(bars, history({77: 102}))['N30_TRAIL'])
        past = history()
        for bad in (past[:-1], past + [bars], past[1:] + [bars], list(reversed(past)),
                    past[:-1] + [past[-1][:-1]], past[:-1] + [day(code='US.QQQ')]):
            with self.subTest(length=len(bad)), self.assertRaises(ValueError):
                trend_trades(bars, bad)

    def test_last_entry_clocks_and_force_flatten_are_inclusive(self):
        for name, index, price in [('O30_VWAP', 17, 101.2), ('N30_TRAIL', 59, 101.2)]:
            with self.subTest(name=name):
                prices = {i: price + (i - index) / 1000 for i in range(index, 78)}
                bars = day(prices)
                trade = trend_trades(bars, history())[name]
                self.assertEqual(trade['signal_time'], bars[index].close_time)
                self.assertEqual(trade['exit_decision_time'], bars[74].close_time)
                self.assertEqual(trade['exit_time'], bars[75].close_time)
                self.assertEqual(trade['exit_reason'], 'flatten')
        self.assertIsNone(trend_trades(day({18: 101.2}), history())['O30_VWAP'])
        self.assertIsNone(trend_trades(day({65: 101.2}), history())['N30_TRAIL'])

    def test_first_signal_is_never_reentered_and_later_prices_cannot_change_closed_trade(self):
        bars = day({5: 101, 6: 101.2, 7: 99, 8: 98, 11: 99, 12: 98})
        result = trend_trades(bars, history())
        future = bars[:13] + [replace(bar, open=200, high=201, low=199, close=200)
                             for bar in bars[13:]]
        self.assertTrue(all(trade is not None for trade in result.values()))
        self.assertEqual(result, trend_trades(future, history()))

    def test_future_before_exit_cannot_replace_a_fixed_signal_or_entry(self):
        bars = day({5: 101, 6: 101.2, 7: 101.3})
        before = trend_trades(bars, history())
        future = bars[:8] + [replace(bar, open=98, high=98.1, low=97.9, close=98)
                            for bar in bars[8:]]
        after = trend_trades(future, history())
        for name in CANDIDATES:
            for key in ('signal_time', 'signal_price', 'entry_time', 'entry_price', 'direction'):
                self.assertEqual(before[name][key], after[name][key])

    def test_zero_volume_and_invalid_day_are_not_silently_tradable(self):
        bars = day({5: 105, 6: 101.2})
        self.assertTrue(all(value is None for value in trend_trades(
            [replace(bar, volume=0) for bar in bars], history()).values()))
        for bad in (bars[:-1], bars[:42], bars[:3] + [bars[2]] + bars[4:]):
            with self.subTest(length=len(bad)), self.assertRaises(ValueError):
                trend_trades(bad, history())


if __name__ == '__main__':
    unittest.main()
