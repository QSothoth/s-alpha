"""Synthetic unit cases for the exact OR2 information and execution boundaries."""
from dataclasses import replace
from datetime import datetime, timedelta
import unittest

from custody.marketdata import Bar
from custody.models import ET
from studies.us_opening_range.context_signals import CANDIDATES, context_trades, validate_day


OPEN = datetime(2024, 3, 18, 9, 30, tzinfo=ET)


def day_bars(opening=OPEN, code='US.NVDA', prices=None):
    rows = []
    for index in range(78):
        close = (prices or {}).get(index, 100)
        high, low = (101, 99) if index < 6 else (close + 0.1, close - 0.1)
        rows.append(Bar(code, opening + timedelta(minutes=5 * (index + 1)),
                        100 if index == 0 else close, high, low, close, 10, interval='5m'))
    return rows


def history_for(code='US.NVDA', prices=None):
    days = []
    opening = OPEN
    while len(days) < 14:
        opening -= timedelta(days=1)
        if opening.weekday() < 5:
            days.append(day_bars(opening, code, prices))
    return list(reversed(days))


class ContextSignalTests(unittest.TestCase):
    def test_four_fixed_rules_next_close_fills_and_next_close_exit(self):
        bars = day_bars(prices={6: 101.2, 7: 101.3, 8: 103.7, 9: 103.4})
        market = day_bars(code='US.SPY', prices={6: 100.5})
        trades = context_trades(bars, history_for(), market)
        self.assertEqual(tuple(trades), CANDIDATES)
        self.assertIsNotNone(trades['N30'])
        self.assertIsNotNone(trades['R30'])
        self.assertIsNone(trades['C30'])
        trade = trades['B30']
        self.assertEqual(trade['signal_time'], OPEN+timedelta(minutes=35))
        self.assertEqual(trade['entry_time'], OPEN+timedelta(minutes=40))
        self.assertEqual(trade['entry_price'], 101.3)
        self.assertEqual(trade['exit_reason'], 'target')
        self.assertEqual(trade['exit_time'], OPEN+timedelta(minutes=50))
        self.assertAlmostEqual(trade['gross_return'], 103.4/101.3-1)

    def test_entry_beyond_stop_or_target_still_fills_then_decides_exit(self):
        for entry, following, reason in [(99, 98, 'stop'), (104, 103, 'target')]:
            with self.subTest(reason=reason):
                bars = day_bars(prices={6: 101.2, 7: entry, 8: following})
                trade = context_trades(bars, history_for())['B30']
                self.assertEqual(trade['entry_price'], entry)
                self.assertEqual(trade['entry_time'], trade['exit_decision_time'])
                self.assertEqual(trade['exit_price'], following)
                self.assertEqual(trade['exit_reason'], reason)
                self.assertLess(trade['gross_return'], 0)

    def test_short_return_uses_negative_plain_price_change(self):
        bars = day_bars(prices={6: 98.8, 7: 98.7, 8: 96.3, 9: 96.5})
        market = day_bars(code='US.SPY', prices={6: 99.5})
        trade = context_trades(bars, history_for(), market)['R30']
        self.assertEqual(trade['direction'], 'SHORT')
        self.assertAlmostEqual(trade['gross_return'], -(96.5/98.7-1))
        self.assertEqual(trade['exit_reason'], 'target')

    def test_noise_uses_only_fourteen_previous_days_at_the_same_clock(self):
        bars = day_bars(prices={6: 101.2})
        quiet = context_trades(bars, history_for())
        self.assertIsNotNone(quiet['N30'])
        noisy = history_for(prices={6: 102})
        trades = context_trades(bars, noisy)
        self.assertIsNotNone(trades['B30'])
        self.assertIsNone(trades['N30'])
        # A large prior-day move at a different clock is not today's sigma at 10:05.
        other_clock = history_for(prices={7: 110})
        self.assertIsNotNone(context_trades(bars, other_clock)['N30'])
        for invalid in (noisy[:13], noisy+[bars], noisy[1:]+[bars], list(reversed(noisy))):
            with self.subTest(length=len(invalid)), self.assertRaises(ValueError):
                context_trades(bars, invalid)

    def test_noise_envelope_uses_previous_complete_close_for_gap(self):
        long_bars = day_bars(prices={6: 101.2})
        short_bars = day_bars(prices={6: 98.8})
        self.assertIsNone(context_trades(long_bars, history_for(prices={77: 102}))['N30'])
        self.assertIsNone(context_trades(short_bars, history_for(prices={77: 98}))['N30'])

    def test_market_confirmation_and_spy_self_rules(self):
        bars = day_bars(prices={6: 101.2})
        market = day_bars(code='US.SPY', prices={6: 101.1})
        self.assertIsNotNone(context_trades(bars, history_for(), market)['C30'])
        tied = day_bars(code='US.SPY', prices={6: 101.2})
        self.assertIsNone(context_trades(bars, history_for(), tied)['R30'])
        own = context_trades(tied, history_for('US.SPY'), tied)
        self.assertIsNone(own['R30'])
        self.assertEqual(own['C30'], own['B30'])

    def test_incomplete_wrong_day_or_wrong_symbol_market_disables_market_rules_only(self):
        bars = day_bars(prices={6: 101.2})
        market_cases = [None, day_bars(code='US.SPY')[:-1],
                        day_bars(OPEN-timedelta(days=1), 'US.SPY'), day_bars(code='US.QQQ')]
        for market in market_cases:
            with self.subTest(market_length=len(market) if market else None):
                trades = context_trades(bars, history_for(), market)
                self.assertIsNotNone(trades['B30'])
                self.assertIsNotNone(trades['N30'])
                self.assertIsNone(trades['R30'])
                self.assertIsNone(trades['C30'])

    def test_future_prices_do_not_change_a_signal_or_already_executed_trade(self):
        bars = day_bars(prices={6: 101.2, 7: 99, 8: 98})
        before = context_trades(bars, history_for())
        future = bars[:9] + [replace(bar, open=200, high=201, low=199, close=200) for bar in bars[9:]]
        self.assertEqual(context_trades(future, history_for()), before)

    def test_deadline_includes_1100_and_timeout_starts_at_signal(self):
        prices = {index: 101.2 for index in range(17, 78)}
        trade = context_trades(day_bars(prices=prices), history_for())['B30']
        self.assertEqual(trade['signal_time'], OPEN+timedelta(minutes=90))
        self.assertEqual(trade['exit_decision_time'], OPEN+timedelta(minutes=150))
        self.assertEqual(trade['exit_time'], OPEN+timedelta(minutes=155))
        self.assertEqual(trade['exit_reason'], 'timeout')
        self.assertTrue(all(trade is None for trade in
                            context_trades(day_bars(prices={18: 101.2}), history_for()).values()))

    def test_no_signal_for_zero_volume_zero_range_or_chasing(self):
        ordinary = day_bars(prices={6: 101.2})
        examples = [[replace(bar, volume=0) for bar in ordinary],
                    [replace(bar, open=100, high=100, low=100, close=100) for bar in ordinary],
                    day_bars(prices={6: 101.6})]
        for bars in examples:
            with self.subTest(first=bars[0]):
                self.assertTrue(all(trade is None for trade in context_trades(bars, history_for()).values()))

    def test_day_integrity_rejects_half_day_gap_order_mixed_code_or_interval(self):
        bars = day_bars()
        bad_days = [bars[:42], bars[:-1], bars[:3]+[bars[2]]+bars[4:],
                    [bars[1], bars[0]]+bars[2:], [replace(bars[0], code='US.QQQ')]+bars[1:],
                    [replace(bars[0], interval='1m')]+bars[1:],
                    [replace(bars[0], open=0, low=0)]+bars[1:]]
        for bad in bad_days:
            with self.subTest(length=len(bad)), self.assertRaises(ValueError):
                validate_day(bad)
        validate_day(bars)


if __name__ == '__main__':
    unittest.main()
