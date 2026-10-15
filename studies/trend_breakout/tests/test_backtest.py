"""TF1 signals and engine: indicators against naive loops, matrix engine against the per-trade reference."""
import math
import unittest
from pathlib import Path

import numpy as np

from studies.trend_breakout import backtest, panel, reference, signals

ALL_RULES = sum(signals.ROUNDS.values(), ())
DATA = Path(__file__).resolve().parents[3] / 'data' / 'trend-breakout-v1'


def synthetic(T=420, N=12, seed=0, holes=True):
    rng = np.random.default_rng(seed)
    ret = rng.normal(0.0008, 0.025, (T, N)) + np.where(rng.random((T, N)) < 0.01, 0.09, 0)
    close = 20 * np.exp(np.cumsum(ret, axis=0))
    open_ = close * np.exp(rng.normal(0, 0.01, (T, N)))
    high = np.maximum(open_, close) * (1 + rng.random((T, N)) * 0.02)
    low = np.minimum(open_, close) * (1 - rng.random((T, N)) * 0.02)
    p = {'open': open_, 'high': high, 'low': low, 'close': close,
         'volume': rng.random((T, N)) * 1e6, 'turnover': rng.random((T, N)) * 1e8}
    if holes:
        gone = rng.random((T, N)) < 0.02
        gone[:30, 0] = True  # a late listing
        for k in p:
            p[k][gone] = np.nan
    for k in ('open', 'high', 'low', 'close'):
        p['raw_' + k] = np.round(p[k], 2)
    return p


def naive_rolling(x, w, fn):
    return np.array([fn(x[t - w + 1:t + 1]) if t >= w - 1 else np.nan for t in range(len(x))])


def bars_of(p, j):
    return [None if np.isnan(p['close'][t, j]) else
            {k: p[k][t, j] for k in ('open', 'close', 'raw_open', 'raw_high', 'raw_close')}
            for t in range(len(p['close']))]


class Indicators(unittest.TestCase):
    def test_rolling_extremes_match_a_naive_window(self):
        x = np.random.default_rng(1).normal(size=(300, 3))
        for w in (1, 2, 5, 20, 22, 55, 252):
            np.testing.assert_allclose(signals.rolling_max(x, w)[:, 1], naive_rolling(x[:, 1], w, max))
            np.testing.assert_allclose(signals.rolling_min(x, w)[:, 2], naive_rolling(x[:, 2], w, min))

    def test_wilder_atr_and_supertrend_match_scalar_loops(self):
        p = synthetic(holes=False)
        h, l, c = p['high'][:, 3], p['low'][:, 3], p['close'][:, 3]
        tr = [h[0] - l[0]] + [max(h[t] - l[t], abs(h[t] - c[t - 1]), abs(l[t] - c[t - 1])) for t in range(1, len(c))]
        a = [math.nan] * 9 + [sum(tr[:10]) / 10]
        for t in range(10, len(c)):
            a.append((a[-1] * 9 + tr[t]) / 10)
        np.testing.assert_allclose(signals.atr(p['high'], p['low'], p['close'], 10)[:, 3], a)
        up, dn, trend = [], [], [1]
        for t in range(len(c)):
            bu, bd = (h[t] + l[t]) / 2 - 3 * a[t], (h[t] + l[t]) / 2 + 3 * a[t]
            if t and not math.isnan(up[-1]) and c[t - 1] > up[-1]:
                bu = max(bu, up[-1])
            if t and not math.isnan(dn[-1]) and c[t - 1] < dn[-1]:
                bd = min(bd, dn[-1])
            if t:
                tr_ = trend[-1]
                if tr_ < 0 and c[t] > dn[-1]:
                    tr_ = 1
                elif tr_ > 0 and c[t] < up[-1]:
                    tr_ = -1
                trend.append(tr_)
            up.append(bu)
            dn.append(bd)
        got_trend, got_up = signals.supertrend(p['high'], p['low'], p['close'])
        np.testing.assert_allclose(got_up[:, 3], up)
        np.testing.assert_array_equal(got_trend[:, 3], trend)

    def test_rsi2_matches_a_scalar_loop(self):
        c = np.array([10, 11, 10.5, 10.4, 12, 11, 11, 10], float)[:, None]
        p = {'high': c + 0.5, 'low': c - 0.5, 'close': c, 'volume': np.ones_like(c), 'turnover': np.ones_like(c)}
        got = signals.indicators(p)['rsi2'][:, 0]
        up = dn = None
        for t in range(1, len(c)):
            d = c[t, 0] - c[t - 1, 0]
            g, l = max(d, 0), max(-d, 0)
            if t == 1:  # Wilder seed: the mean of the first two changes, the first counted as 0
                up, dn = g / 2, l / 2
            else:
                up, dn = (up + g) / 2, (dn + l) / 2
            self.assertAlmostEqual(got[t], 100 - 100 / (1 + up / dn) if dn > 0 else 100.0)

    def test_momentum_ranks_inside_the_pool_and_fires_on_entry_only(self):
        ret = np.tile(np.arange(30, dtype=float), (4, 1))
        ret[2:, 0] = 100.0  # stock 0 jumps to the top on day 2
        pool = np.ones_like(ret, bool)
        pool[:, 29] = False  # the best stock is outside the pool and must not take a top slot
        top = signals.momentum_top({'ret126': ret}, pool)
        self.assertEqual(list(np.flatnonzero(top[2])), [0])
        self.assertFalse(top[3].any())
        self.assertEqual(set(np.flatnonzero(top[1])), set())  # unchanged ranks: nothing newly entered

    def test_smooth_momentum_keeps_the_less_discrete_half_of_the_top_group(self):
        ret = np.tile(np.arange(40, dtype=float), (2, 1))
        ret[1, :2] = 100.0  # stocks 0 and 1 enter the top 10% (4 of 40) on day 1
        ids = np.zeros_like(ret)
        ids[:, 0], ids[:, 1] = -0.2, 0.3  # stock 0 rose on many small days, stock 1 on a few big ones
        got = signals.smooth_momentum({'ret126': ret, 'id126': ids}, np.ones_like(ret, bool))
        self.assertEqual(list(np.flatnonzero(got[1])), [0])

    def test_reversal_takes_the_pool_bottom_and_low_turnover_half(self):
        ret = np.tile(np.arange(40, dtype=float), (2, 1))
        ret[1, 39] = -100.0  # the best stock collapses to the bottom on day 1
        pool = np.ones_like(ret, bool)
        low = signals.newly(signals.bottom_share({'ret21': ret}, pool, 'ret21'))
        self.assertEqual(list(np.flatnonzero(low[1])), [39])
        turn = np.tile(np.arange(40, dtype=float), (2, 1))
        calm = signals.at_most_pool_median({'abn_turn': turn}, pool, 'abn_turn')
        self.assertEqual(int(calm[0].sum()), 20)
        self.assertFalse(calm[0, 39])

    def test_momentum_calm_is_causal(self):
        p = synthetic(T=420, N=40, seed=5, holes=False)
        ind = signals.indicators(p)
        pool = ~np.isnan(p['close'])
        full = signals.momentum_calm(ind, pool)
        head = signals.momentum_calm({k: v[:350] for k, v in ind.items()}, pool[:350])
        np.testing.assert_array_equal(full[:350], head)
        self.assertTrue(0 < full.sum() < len(full))

    def test_market_state_uses_the_pool_average(self):
        close = np.vstack([np.full((250, 2), 10.0), np.full((10, 2), 9.0)])
        close[:250] *= np.linspace(1, 2, 250)[:, None]
        up = signals.market_up(close, np.ones_like(close, bool))
        self.assertTrue(up[249])
        self.assertFalse(up[255])

    def test_suspended_days_are_skipped_not_counted(self):
        p = synthetic()
        ind = signals.indicators(p)
        j = 0
        keep = ~np.isnan(p['close'][:, j])
        own = {k: p[k][keep, j:j + 1] for k in ('high', 'low', 'close')}
        hh = signals.rolling_max(own['high'], 55)[:, 0]
        np.testing.assert_allclose(ind['hh55_prev'][keep, j][1:], hh[:-1])
        self.assertTrue(np.isnan(ind['chandelier'][~keep, j]).all())
        self.assertEqual(ind['ready'][keep, j].sum(), keep.sum() - signals.MIN_BARS + 1)

    def test_signals_use_no_future_bar(self):
        p = synthetic()
        cut = 330
        full = signals.indicators(p)
        head = signals.indicators({k: v[:cut] for k, v in p.items()})
        for rule in ALL_RULES:
            e1, l1, _ = signals.evaluate(full, rule)
            e2, l2, _ = signals.evaluate(head, rule)
            np.testing.assert_array_equal(e1[:cut], e2)
            np.testing.assert_allclose(l1[:cut], l2)


class EngineMatchesReference(unittest.TestCase):
    def check(self, p, lo, hi, limit=None, cost=(0.001, 0.002)):
        ind = signals.indicators(p)
        eligible = ~np.isnan(p['close'])
        n = 0
        for rule in ALL_RULES:
            entry, line, ratchet = signals.evaluate(ind, rule, eligible)
            trades, _ = backtest.run(p, entry, line, ratchet, eligible, ind['atr22'], lo, hi, cost, limit)
            for j in range(p['close'].shape[1]):
                ref = reference.run_stock(bars_of(p, j), entry[:, j], line[:, j], ratchet, eligible[:, j],
                                          ind['atr22'][:, j], lo, hi, cost, None if limit is None else limit[j])
                mine = trades['stock'] == j
                got = list(zip(*(trades[k][mine] for k in backtest.TRADE_FIELDS[1:])))
                self.assertEqual(len(got), len(ref), (rule, j))
                for g, r in zip(got, ref):
                    self.assertEqual(tuple(g[:3]) + (bool(g[-1]),), tuple(r[:3]) + (r[-1],))
                    np.testing.assert_allclose(g[3:-1], r[3:-1], rtol=1e-12)
                n += len(ref)
        return n

    def test_synthetic_with_suspensions(self):
        self.assertGreater(self.check(synthetic(), 260, 419), 20)

    def test_synthetic_with_time_exits(self):
        p = synthetic(seed=11)
        ind = signals.indicators(p)
        eligible = ~np.isnan(p['close'])
        entry, line, ratchet = signals.evaluate(ind, 'U3', eligible)
        limit = np.where(np.arange(12) % 2, 0.1, 0.2)
        n = 0
        for max_hold, use_stop in ((20, False), (20, True), (60, True)):
            trades, _ = backtest.run(p, entry, line, ratchet, eligible, ind['atr22'], 260, 419, (0.001, 0.002),
                                     limit, max_hold=max_hold, use_stop=use_stop)
            for j in range(12):
                ref = reference.run_stock(bars_of(p, j), entry[:, j], line[:, j], ratchet, eligible[:, j],
                                          ind['atr22'][:, j], 260, 419, (0.001, 0.002), limit[j],
                                          max_hold=max_hold, use_stop=use_stop)
                mine = trades['stock'] == j
                got = list(zip(*(trades[k][mine] for k in backtest.TRADE_FIELDS[1:])))
                self.assertEqual([g[:3] for g in got], [r[:3] for r in ref], (max_hold, use_stop, j))
                n += len(ref)
            if not use_stop:  # pure time exit: never held longer than max_hold days plus waits for suspensions
                closed = trades['at_end'] == 0
                self.assertTrue(((trades['exit'] - trades['entry'])[closed] >= max_hold).all())
        self.assertGreater(n, 20)

    def test_synthetic_with_failed_breakout_exits(self):
        p = synthetic(seed=13)
        ind = signals.indicators(p)
        eligible = ~np.isnan(p['close'])
        entry, line, ratchet = signals.evaluate(ind, 'T2')
        limit = np.where(np.arange(12) % 2, 0.1, 0.2)
        trades, _ = backtest.run(p, entry, line, ratchet, eligible, ind['atr22'], 260, 419, (0.001, 0.002), limit,
                                 fail_level=ind['hh55_prev'], fail_days=10)
        n = 0
        for j in range(12):
            ref = reference.run_stock(bars_of(p, j), entry[:, j], line[:, j], ratchet, eligible[:, j],
                                      ind['atr22'][:, j], 260, 419, (0.001, 0.002), limit[j],
                                      fail_level=ind['hh55_prev'][:, j], fail_days=10)
            mine = trades['stock'] == j
            got = list(zip(*(trades[k][mine] for k in backtest.TRADE_FIELDS[1:])))
            self.assertEqual([g[:3] for g in got], [r[:3] for r in ref], j)
            for g, r in zip(got, ref):
                np.testing.assert_allclose(g[3:-1], r[3:-1], rtol=1e-12)
            n += len(ref)
        self.assertGreater(n, 10)

    def test_synthetic_with_price_limits(self):
        p = synthetic(seed=3)
        self.assertGreater(self.check(p, 260, 419, limit=np.where(np.arange(12) % 2, 0.1, 0.2)), 20)

    @unittest.skipUnless((DATA / 'cn' / 'bars_raw.csv.gz').exists(), 'dataset not on this machine')
    def test_real_stocks_every_market(self):
        for market in ('us', 'hk', 'cn'):
            p = panel.load(DATA / market)
            cols = np.random.default_rng(7).choice(len(p['codes']), 25, replace=False)
            q = {k: p[k][:, cols] for k in p if isinstance(p[k], np.ndarray) and p[k].ndim == 2}
            m = panel.mask(p['dates'], 'train')
            lo, hi = np.flatnonzero(m)[[0, -1]]
            limit = np.full(25, 0.1) if market == 'cn' else None
            self.assertGreater(self.check(q, lo, hi, limit), 10, market)


class MarketRules(unittest.TestCase):
    def tiny(self, closes, raw_highs=None, opens=None):
        c = np.array(closes, float)[:, None]
        o = c.copy() if opens is None else np.array(opens, float)[:, None]
        p = {'open': o, 'close': c, 'raw_open': o, 'raw_close': c,
             'raw_high': c.copy() if raw_highs is None else np.array(raw_highs, float)[:, None]}
        return p

    def test_buy_day_cannot_sell_and_limit_down_waits(self):
        # signal day 0, buy day 1 at 10, close below the stop on day 1, days 2-3 locked limit-down, sell day 4
        p = self.tiny([10, 8.5, 7.65, 6.89, 6.5], raw_highs=[10, 10, 7.65, 6.89, 7.0],
                      opens=[10, 10, 7.65, 6.89, 6.6])
        entry = np.array([[True], [False], [False], [False], [False]])
        line = np.full((5, 1), 9.0)
        trades, _ = backtest.run(p, entry, line, False, np.ones((5, 1), bool), np.ones((5, 1)), 1, 4,
                                 limit=np.array([0.1]))
        self.assertEqual((trades['entry'][0], trades['exit'][0], trades['sell'][0]), (1, 4, 6.6))
        self.assertFalse(trades['at_end'][0])

    def test_limit_up_open_cannot_buy(self):
        p = self.tiny([10, 11, 11.5], opens=[10, 11, 11.2])
        entry = np.array([[True], [False], [False]])
        trades, skipped = backtest.run(p, entry, np.full((3, 1), 9.0), True, np.ones((3, 1), bool),
                                       np.ones((3, 1)), 1, 2, limit=np.array([0.1]))
        self.assertEqual(len(trades['r']), 0)
        self.assertEqual(skipped['limit_up'], 1)

    def test_open_trade_settles_at_the_last_close(self):
        p = self.tiny([10, 10.5, 11, 12])
        entry = np.array([[True], [False], [False], [False]])
        trades, _ = backtest.run(p, entry, np.full((4, 1), 9.0), True, np.ones((4, 1), bool),
                                 np.full((4, 1), 0.5), 1, 2)
        self.assertEqual((trades['exit'][0], trades['sell'][0], bool(trades['at_end'][0])), (2, 11.0, True))
        self.assertAlmostEqual(trades['r'][0], (11 - 10.5) / 1.5)



class PointInTime(unittest.TestCase):
    def test_shares_in_force_are_the_latest_change_on_or_before_the_day(self):
        from studies.trend_breakout import pit
        dates = np.array(['2019-12-31', '2020-01-02', '2021-06-30', '2022-01-01'])
        got = pit.shares_asof(dates, [('2020-01-02', 100.0), ('2021-06-30', 150.0)])
        np.testing.assert_array_equal(got, [np.nan, 100.0, 150.0, 150.0])
        self.assertTrue(np.isnan(pit.shares_asof(dates, [])).all())


class Defensive(unittest.TestCase):
    def test_pool_percentile_and_causal_defensive_indicators(self):
        x = np.array([[3.0, 1.0, 2.0] + [np.nan] * 20 + list(range(4, 21))])
        pool = np.ones_like(x, bool)
        pct = signals.pool_percentile(x, pool)
        self.assertEqual(pct[0, 1], 0.0)
        self.assertEqual(np.nanmax(pct), 1.0)
        self.assertTrue(np.isnan(pct[0, 5]))
        p = synthetic(T=420, N=30, seed=9)
        full = signals.defensive_indicators(p)
        head = signals.defensive_indicators({k: v[:330] for k, v in p.items()})
        for k in ('vol21', 'max21', 'abn_turn', 'atr22'):
            np.testing.assert_allclose(full[k][:330], head[k], err_msg=k)
        pool = ~np.isnan(p['close'])
        for rule in ('Y1', 'Y2', 'Y3', 'Y4'):
            np.testing.assert_array_equal(signals.defensive_entry(full, pool, rule)[:330],
                                          signals.defensive_entry(head, pool[:330], rule))


class Universe(unittest.TestCase):
    def test_only_a_share_risk_warning_names_count_as_st(self):
        from studies.trend_breakout import final
        self.assertTrue(final.is_st('*ST闻泰') and final.is_st('ST人福'))
        self.assertFalse(final.is_st('First Solar') or final.is_st('贵州茅台'))


if __name__ == '__main__':
    unittest.main()
