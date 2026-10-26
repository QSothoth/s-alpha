"""Execution timing of the 2026-10-25 style additions: the engine's short_exit_signal (a short covers at the close
its signal is true, from the session after entry), an intraday short covered the same day, and the option pricing
helpers (studies/trader_options)."""
import unittest

import numpy as np

from studies.trader_options import pricing as P
from studies.trader_replication import system as Y

NOCOST = dict(buy_cost=0, sell_cost=0, margin_rate=0, trail='', trims=(), risk=.01, max_position=10.0,
              max_gross=10.0)


def run(rows, sig, entry, **kw):
    a = np.array(rows, float)
    p = {'open': a[:, :1], 'high': a[:, 1:2], 'low': a[:, 2:3], 'close': a[:, 3:4],
         'dates': np.array(['2025-01-%02d' % (i + 1) for i in range(len(a))]), 'codes': np.array(['US.AAA'])}
    ema = {'sx': np.array(sig, bool)[:, None]}
    e = [[] for _ in rows]
    e[0].append(entry)
    return Y.simulate(p, ema, Y.Rules(**{**NOCOST, **kw}), e, p['dates'][0], p['dates'][-1], audit=True)[2]


class ShortExitSignalTests(unittest.TestCase):
    def test_off_by_default(self):
        self.assertEqual(Y.Rules().short_exit_signal, '')

    def test_a_short_covers_at_the_signal_close(self):
        rows = [(10, 10, 10, 10), (9.9, 10.0, 9.4, 9.6), (9.5, 9.6, 9.0, 9.1)]
        (t,) = run(rows, [True, True, False], (0, 0, -1, 10.0, 12.0, 'mrs'), short_exit_signal='sx')
        self.assertEqual((t['exit'], t['why']), ('2025-01-02', 'signal'))   # not on the entry day itself
        self.assertAlmostEqual(t['executions'][-1]['price'], 9.6)

    def test_longs_ignore_the_short_signal(self):
        rows = [(10, 10, 10, 10), (10.1, 10.4, 10.0, 10.3)]
        (t,) = run(rows, [True, True], (0, 0, 1, 10.0, 8.0, 'mrl'), short_exit_signal='sx')
        self.assertEqual(t['why'], 'end')

    def test_an_intraday_short_with_a_day_exit_closes_that_day(self):
        rows = [(10, 11, 9, 9.5), (9.4, 9.6, 9.0, 9.1)]                   # sold at 10.5 (a spike), covered at close
        (t,) = run(rows, [False, False], (0, 0, -1, 10.5, 12.6, 'gap', 9.5), intraday_kinds=('gap',))
        self.assertEqual((t['entry'], t['exit']), ('2025-01-01', '2025-01-01'))
        self.assertAlmostEqual(t['executions'][-1]['price'], 9.5)


class PricingTests(unittest.TestCase):
    def test_put_call_parity(self):
        S, K, T, v = 100.0, 95.0, 30 / 365, .4
        c, p = P.bs(S, K, T, v, False), P.bs(S, K, T, v, True)
        self.assertAlmostEqual(c - p, S - K * np.exp(-P.R * T), places=6)

    def test_expired_is_intrinsic(self):
        self.assertEqual(P.bs(90, 100, 0, .5, True), 10)
        self.assertEqual(P.bs(90, 100, 0, .5, False), 0)

    def test_earnings_variance_raises_a_spanning_option(self):
        a = P.vol_for(100, 100, 10 / 365, .3, False, 0, 0)
        b = P.vol_for(100, 100, 10 / 365, .3, False, 0, 0, earn_var=.05 ** 2)
        self.assertGreater(b, a)

    def test_reaction_day(self):
        days = np.array(['2025-01-06', '2025-01-07', '2025-01-08'])
        self.assertEqual(P.reaction_day(days, '2025-01-07', 'BEFORE'), 1)
        self.assertEqual(P.reaction_day(days, '2025-01-07', 'AFTER'), 2)


class _Feat:
    """The few daily-feature members the mean-reversion studies read, on given arrays."""
    def __init__(self, c):
        self.c = self.o = self.h = self.l = self.raw = np.asarray(c, float)[:, None]
        self.to20 = np.full_like(self.c, 1e9)
        self.atr14 = np.full_like(self.c, 1.0)

    def get(self, key, f):
        return f()

    def sma(self, n):
        return self.c.copy()

    def ret(self, n):
        return np.zeros_like(self.c)


class EvanBandTests(unittest.TestCase):
    """The HV band (R4 on) is read at the setup close t; the limit order it arms is for session t+1."""

    def build(self, hv):
        from studies.evan_medeiros.replicate import Evan
        n = len(hv)
        F = _Feat([10.0] * n)
        hv = np.asarray(hv, float)[:, None]
        z = np.zeros((n, 1))

        class E(Evan):
            def feat(self, A):
                return F, z, hv, z + 5, z
        A = {'F': F}
        cfg = dict(sides=['long'], long=dict(rsi=None, down=3, hv=15, hv_max=35, trend=False, limit=0.0),
                   pool=dict(turnover=0, price=0), regime='', stop=.2, rule_opts=dict(trims=()))
        entries, *_ = E().build(A, cfg)
        return [d for d, e in enumerate(entries) if e]

    def test_entry_the_session_after_an_in_band_close(self):
        self.assertEqual(self.build([50, 30, 30, 50, 50]), [2, 3])

    def test_upper_edge_is_exclusive(self):
        self.assertEqual(self.build([35, 35, 34.9, 50]), [3])


class GoalTests(unittest.TestCase):
    def test_part_year_period(self):
        from studies.trader_options import goal as G
        dates = ['2024-12-31', '2025-01-02', '2025-08-29', '2025-09-02']
        r = G.period_returns(np.array([1.0, 1.1, 1.21, 2.0]), dates, {'p': ('2025-01-02', '2025-08-29', .05)})
        self.assertAlmostEqual(r['p'], .21)                      # from the close before the first day

    def test_goal_and_guards(self):
        from studies.trader_options import goal as G
        g, y, b = G.goal_of({'2024': .15}, {'win': .06, 'per_year': .3})
        self.assertAlmostEqual(g, -1.0)                          # exactly on the tolerance
        ref = dict(goal_years=.5, goal_behav=3.0, total=0, placebo={'median': -1})
        worse_years = dict(goal_years=1.2, goal_behav=1.0, total=0, placebo={'median': -1})
        self.assertEqual(G.GoalMixin.passes(worse_years, ref, ['placebo', 'years', 'behav']), ['years'])
        ok = dict(goal_years=.9, goal_behav=2.0, total=0, placebo={'median': -1})
        self.assertEqual(G.GoalMixin.passes(ok, ref, ['placebo', 'years', 'behav']), [])


if __name__ == '__main__':
    unittest.main()
