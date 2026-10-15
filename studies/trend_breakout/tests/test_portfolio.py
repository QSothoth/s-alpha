"""PB1 accounting, causal execution and bounded indicator reproduction."""
import unittest

import numpy as np

from studies.trend_breakout import backtest, final, portfolio, signals
from studies.trend_breakout.tests.test_backtest import synthetic


def sample(close, open_=None):
    close = np.asarray(close, float)
    if close.ndim == 1:
        close = close[:, None]
    o = close.copy() if open_ is None else np.asarray(open_, float).reshape(close.shape)
    p = {'close': close, 'open': o, 'high': np.fmax(o, close), 'low': np.fmin(o, close)}
    for key in ('open', 'high', 'low', 'close'):
        p['raw_' + key] = p[key].copy()
    p['dates'] = np.datetime_as_string(np.datetime64('2020-01-01') + np.arange(len(close))).astype(str)
    p['codes'] = np.array([f'S{j}' for j in range(close.shape[1])])
    return p


def execute(p, entry, line, *, priority=None, limit=None, slots=10, risk_fraction=.005, position_cap=.1):
    shape = p['close'].shape
    account = portfolio.Account(p, np.ones(shape) if priority is None else priority, (.001, .002),
                                slots=slots, risk_fraction=risk_fraction, position_cap=position_cap)
    trades, _ = backtest.run(p, entry, line, True, np.ones(shape, bool), np.ones(shape),
                             1, len(entry) - 1, (.001, .002), limit, account=account)
    return trades, account


class Portfolio(unittest.TestCase):
    def test_cash_and_unrealized_profit_reconcile_without_forced_sale(self):
        p = sample([10, 10, 15, 20])
        entry = np.zeros((4, 1), bool)
        entry[0] = True
        tr, a = execute(p, entry, np.full((4, 1), 8.))
        # Risk budget .005 / (10 - 8) -> .0025 shares; fees paid in cash.
        self.assertAlmostEqual(a.cash, 1 - .0025 * 10 * 1.001)
        self.assertAlmostEqual(a.curve[-1]['nav'], a.cash + .0025 * 20)
        self.assertEqual(len(a.positions), 1)
        self.assertTrue(tr['at_end'][0])
        summary = a.summary(p['dates'][0])
        self.assertEqual(summary['realized_pnl'], 0)
        self.assertAlmostEqual(summary['liquidation_nav'], 1 + summary['open_liquidation_pnl'])

    def test_priority_is_from_signal_day_and_cash_never_borrows(self):
        p = sample([[10, 10], [10, 10], [10, 10]])
        entry = np.zeros((3, 2), bool)
        entry[0] = True
        priority = np.array([[1, 2], [100, 0], [100, 0]])
        tr, a = execute(p, entry, np.full((3, 2), 9.), priority=priority, slots=1,
                        risk_fraction=1, position_cap=1)
        self.assertEqual(list(tr['stock']), [1])
        self.assertAlmostEqual(a.cash, 0)
        self.assertEqual(a.skipped['slots'], 1)
        self.assertLessEqual(a.curve[0]['positions'], 1)

    def test_limit_down_open_waits_even_if_later_high_recovers(self):
        p = sample([10, 10, 8, 8, 9], [10, 10, 8, 7.2, 9])
        entry = np.zeros((5, 1), bool)
        entry[0] = True
        tr, a = execute(p, entry, np.full((5, 1), 9.), limit=np.array([.1]))
        # Close on day 2 triggers a sale; day 3 opens limit down but later trades at 8.
        self.assertEqual(list(tr['exit']), [4])
        self.assertFalse(tr['at_end'][0])
        self.assertEqual(len(a.positions), 0)
        a.summary(p['dates'][0])

    def test_stop_uses_previous_close_and_sell_has_next_open_gap(self):
        p = sample([10, 10, 8, 7])
        entry = np.zeros((4, 1), bool)
        entry[0] = True
        tr, a = execute(p, entry, np.full((4, 1), 9.))
        self.assertEqual(list(tr['entry']), [1])
        self.assertEqual(list(tr['exit']), [3])
        self.assertAlmostEqual(tr['sell'][0], 7)
        self.assertLess(tr['r'][0], -1)
        a.summary(p['dates'][0])

    def test_suspension_marks_last_price_and_preserves_months_of_holding(self):
        p = sample(np.linspace(10, 20, 100))
        for key in ('open', 'high', 'low', 'close', 'raw_open', 'raw_high', 'raw_low', 'raw_close'):
            p[key][50] = np.nan
        entry = np.zeros((100, 1), bool)
        entry[0] = True
        tr, a = execute(p, entry, np.full((100, 1), 1.))
        self.assertEqual(tr['exit'][0] - tr['entry'][0], 98)
        self.assertEqual(a.curve[49]['stale_positions'], 1)
        self.assertAlmostEqual(a.curve[49]['nav'], a.curve[48]['nav'])
        self.assertEqual(a.summary(p['dates'][0])['held_60_sessions'], 1)

    def test_unconstrained_account_matches_original_trades(self):
        p = synthetic(T=420, N=6)
        p['dates'] = np.datetime_as_string(np.datetime64('2020-01-01') + np.arange(420)).astype(str)
        p['codes'] = np.array([f'S{j}' for j in range(6)])
        ind = signals.indicators(p)
        entry, line, ratchet = signals.evaluate(ind, 'T1')
        args = (p, entry, line, ratchet, ~np.isnan(p['close']), ind['atr22'], 253, 419, (.001, .002))
        expected, _ = backtest.run(*args)
        a = portfolio.Account(p, np.ones_like(line), (.001, .002), slots=6,
                              risk_fraction=.0001, position_cap=.001)
        actual, _ = backtest.run(*args, account=a)
        self.assertGreater(len(actual['r']), 0)
        for key in expected:
            np.testing.assert_allclose(actual[key], expected[key])
        a.summary(p['dates'][252])

    def test_future_prices_do_not_change_earlier_account_path(self):
        p = sample(np.linspace(10, 20, 100))
        entry, line = np.zeros((100, 1), bool), np.full((100, 1), 8.)
        entry[0] = True
        _, first = execute(p, entry, line)
        p['close'][80:] *= 3
        p['high'][80:] *= 3
        _, second = execute(p, entry, line)
        self.assertEqual(first.curve[:79], second.curve[:79])

    def test_drawdown_recovery_and_calendar_returns(self):
        rows = [{'date': d, 'nav': n, 'exposure': .5, 'positions': 1, 'largest_weight': .5,
                 'stale_positions': 0} for d, n in zip(
                     ['2020-12-30', '2020-12-31', '2021-01-01', '2021-01-02', '2021-01-03'],
                     [1.2, .9, 1.0, 1.2, 1.1])]
        d = portfolio.nav_summary(rows, '2020-12-29')
        self.assertAlmostEqual(d['max_drawdown'], -.25)
        self.assertEqual(d['drawdown_recovery'], '2021-01-02')
        self.assertEqual(d['longest_underwater_sessions'], 2)
        self.assertEqual(d['current_underwater_sessions'], 1)
        self.assertAlmostEqual(d['years']['2020']['return'], -.1)
        self.assertAlmostEqual(d['years']['2021']['return'], 1.1 / .9 - 1)

    def test_blocked_pool_matches_full_liquidity_filter(self):
        p = synthetic(T=420, N=6)
        p['codes'] = np.array([f'US.S{j}' for j in range(6)])
        np.testing.assert_array_equal(final.pool(p, 'us', block=2), signals.liquid(p, 50e6, 5.))

    def test_looser_trailing_line_preserves_initial_risk_and_delays_exit(self):
        p = sample([10, 10, 12, 10.5, 9, 8.5])
        entry = np.zeros((6, 1), bool)
        entry[0] = True
        line = np.array([9, 9, 11, 9.5, 8, 7.5])[:, None]
        args = (p, entry, line, True, np.ones_like(entry), np.ones_like(line), 1, 5)
        base, _ = backtest.run(*args)
        loose, _ = backtest.run(p, entry, line - 1, True, np.ones_like(entry), np.ones_like(line), 1, 5,
                                initial_line=line)
        self.assertEqual(base['exit'][0], 4)
        self.assertEqual(loose['exit'][0], 5)
        for key in ('buy', 'stop0', 'risk'):
            np.testing.assert_allclose(base[key], loose[key])


if __name__ == '__main__':
    unittest.main()
