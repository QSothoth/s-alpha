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

    def test_leverage_estimate(self):
        lev = P.leverage(100, 100, 30 / 365, .3, False)       # ATM 30-day call: about 0.5 x 100 / 3.5
        self.assertTrue(12 < lev < 16)
        self.assertAlmostEqual(P.lever_return(.01, 10, .1, .1), .1)            # no time passed: 10 x 1%
        self.assertAlmostEqual(P.lever_return(0, 10, .1, .025), -.5)           # a quarter of the life left
        self.assertEqual(P.lever_return(-.5, 10, .1, .1), -1.0)                # at most a total loss

    def test_v2_pricing(self):
        iv = np.full((6, 1), .5); iv[2, 0] = .3; iv[4, 0] = .3            # IV drops after reports at 2 and 4
        E = P.implied_event_var(iv, 0, [2, 4], 5)
        self.assertAlmostEqual(E, (.25 - .09) * 30 / 365)
        self.assertIsNone(P.implied_event_var(iv, 0, [2, 4], 3))           # one known report: the fallback
        self.assertAlmostEqual(P.implied_event_var(iv, 0, [2], 5, .01), .01)
        T = 10 / 365
        flat = P.vol_v2(100, 100, T, .5, False, E, near=True, spans=False, k=0)
        self.assertLess(flat, .5)                                          # the report's variance taken out
        self.assertGreater(P.vol_v2(100, 100, T, .5, False, E, True, True, 0), .5)
        self.assertGreater(P.vol_v2(100, 90, T, .5, True, k=.05), P.vol_v2(100, 100, T, .5, True, k=.05))
        self.assertAlmostEqual(P.half_spread(10.0), .01)
        self.assertAlmostEqual(P.half_spread(.5), .04)                     # two cents of a 50-cent option
        self.assertEqual(P.half_spread(.01), .5)

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


class _Bars:
    """Daily bars with their own open / high / low / close (one name)."""
    def __init__(self, o, h, l, c):
        col = lambda x: np.asarray(x, float)[:, None]
        self.o, self.h, self.l, self.c = col(o), col(h), col(l), col(c)
        self.raw = self.c
        self.to20 = np.full_like(self.c, 1e6)

    def get(self, key, f):
        return f()

    def ret(self, n):
        return np.zeros_like(self.c)

    def lo(self, n):
        return np.array([[self.l[max(0, t - n + 1):t + 1].min()] for t in range(len(self.l))])

    def hi(self, n):
        return np.array([[self.h[max(0, t - n + 1):t + 1].max()] for t in range(len(self.h))])


class SamExtensionTests(unittest.TestCase):
    """R7 on: the short is sold when the day's high reaches prior close x (1 + ext) (at the open when it opens
    above), covered at that close unless the stop above the fill is reached first."""

    def entries(self, o, h, l, c):
        from studies.sam_miesse.replicate import Sam
        A = {'F': _Bars(o, h, l, c)}
        cfg = dict(gap=.25, ext=.5, spike=0.0, stop=.3, price=(1.0, 20.0), turnover_max=50e6, max_new=5,
                   locate=0.0, rule_opts=dict(trims=()))
        entries, *_ = Sam().build(A, cfg)
        return [(d, e[3], e[6]) for d, es in enumerate(entries) for e in es]

    def test_sold_at_the_level_covered_at_the_close(self):
        self.assertEqual(self.entries([10, 13], [10, 16], [10, 12], [10, 12.5]), [(1, 15.0, 12.5)])

    def test_opens_above_the_level_sold_at_the_open(self):
        self.assertEqual(self.entries([10, 16], [10, 17], [10, 14], [10, 14.5]), [(1, 16.0, 14.5)])

    def test_stop_first_when_the_high_reaches_it(self):
        (d, f, ex), = self.entries([10, 13], [10, 20], [10, 12], [10, 12.5])
        self.assertAlmostEqual(ex, 19.5)                       # 15 x 1.3

    def test_level_not_reached_no_trade(self):
        self.assertEqual(self.entries([10, 13], [10, 14.9], [10, 12], [10, 12.5]), [])


class EmanuelaReclaimTests(unittest.TestCase):
    """R7: with at_reclaim the long is entered at the close of the reclaim session itself."""

    def test_entry_on_the_reclaim_close(self):
        from studies.emanuela_elias.replicate import Emanuela
        c = [10, 10, 10, 10, 9.6, 10.2, 10.3]
        l = [9.9, 9.9, 9.9, 9.9, 9.5, 9.7, 10.1]
        h = [10.1] * 4 + [9.8, 10.3, 10.4]
        F = _Bars(c, h, l, c)

        class E(Emanuela):
            def listed(self, A, cfg):
                return np.ones(F.c.shape, bool)
        cfg = dict(level=3, reclaim=5, window=10, band=.01)
        m, lv = E().setups({'F': F}, dict(cfg, at_reclaim=True), 1)
        self.assertEqual(list(np.flatnonzero(m[:, 0])), [5])  # broke 9.9 on day 4, closed back above on day 5
        self.assertAlmostEqual(lv[5, 0], 9.9)
        m2, _ = E().setups({'F': F}, cfg, 1)
        self.assertFalse(m2[5, 0])                            # the retest version waits


class KarlStatementTests(unittest.TestCase):
    def test_settlement_date_and_amount_check(self):
        from studies.karl_domm.replicate import Karl
        text = ('08/05 Sale Short Sale HD 08/15/2025 CALL HOME DEPOT INC $400 (7.0000) 0.6000 4.65 415.35\n'
                'Purchase Cover Short BIDU 02/14/2025 CALL BAIDU INC $104 EXP 42.0000 0.1900 7.93 (235.93) 224.10\n')
        a, b = Karl.parse_statement(text)
        self.assertEqual((a['date'], a['settle'], a['action'], a['qty']), ('2025-08-04', '2025-08-05', 'open_short', -7.0))
        self.assertEqual((b['action'], b['qty'], b['strike']), ('cover', 12.0, 104.0))   # OCR's 42 is 12 by the amount

    def test_positions_return_on_debit(self):
        from studies.karl_domm.replicate import Karl
        rows = [dict(date='2025-08-04', sym='X', action='open_short', cp='CALL', strike=110.0, exp='', qty=-1, px=1.0),
                dict(date='2025-08-04', sym='X', action='buy', cp='CALL', strike=110.0, exp='', qty=2, px=2.0),
                dict(date='2025-08-06', sym='X', action='sell', cp='CALL', strike=110.0, exp='', qty=-2, px=3.0),
                dict(date='2025-08-06', sym='X', action='cover', cp='CALL', strike=110.0, exp='', qty=1, px=0.5)]
        (p,), open_ = Karl.positions(rows)
        self.assertEqual((p['debit'], p['proceeds'], open_), (300.0, 550.0, []))
        self.assertAlmostEqual(p['ret'], 550 / 300 - 1)


class HolguinVolTests(unittest.TestCase):
    def test_short_vol_reads_the_prior_close(self):
        from studies.alfredo_holguin.replicate import Holguin
        c = np.array([100, 101, 99, 102, 98, 100, 150.0])[:, None]     # the jump is on the last day
        A = {'close': c, 'iv': np.full(c.shape, .2)}
        H = Holguin()
        v_before = H.model_vol(A, 0, 6, {'vol': 'max5'})               # opening on day 6: closes through day 5
        self.assertGreater(v_before, .2)                                # the 5-day HV of days 1-5 is above 20%
        self.assertLess(v_before, 1.0)                                  # ... and does not see day 6's +50%
        self.assertEqual(H.model_vol(A, 0, 6, {'vol': 'iv'}), .2)


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


class EmanuelaHourlyTimingTests(unittest.TestCase):
    """studies/emanuela_elias/hourly.py: what each decision may read (notes/PREREG_H1.md)."""

    def setUp(self):
        from studies.emanuela_elias import hourly as EH
        self.EH = EH

    def fake(self, lows, closes, highs=None, opens=None):
        EH = self.EH
        n = len(closes)
        D = type('D', (), {})()
        D.codes = ['US.X']
        D.times = np.array([f'2024-01-{2 + i // 7:02d} {10 + i % 7:02d}:30:00' for i in range(n)])
        D.c = np.array(closes, float)[:, None]
        D.l = np.array(lows, float)[:, None]
        D.h = (np.array(highs, float) if highs is not None else np.maximum(D.c[:, 0], D.l[:, 0]) + .5)[:, None]
        D.o = (np.array(opens, float) if opens is not None else D.c[:, 0])[:, None]
        D.bar_day = np.arange(n) // 7
        D.d_low = D.d_high = D.d_close = np.full((n // 7 + 1, 1), 10.0)
        D.listed = lambda top, mp: np.ones((n // 7 + 1, 1), bool)
        return D

    def test_pivot_is_known_k_bars_later(self):
        lo = np.array([10, 9, 8, 7, 8, 9, 10, 11, 12], float)
        piv = self.EH.pivots(lo, lo + 1, 2)
        low = [p for p in piv if p[2] == 'low']
        self.assertEqual(low[0][3], 3)                 # the pivot bar
        self.assertEqual(low[0][0], 5)                 # confirmed two bars later
        lv = self.EH.Levels(piv, 'low', 70)
        self.assertEqual(lv.at(4), [])
        self.assertEqual(lv.at(5), [7.0])

    def test_entry_at_the_retest_close_after_the_reclaim(self):
        EH = self.EH
        # support 100 (pivot low at bar 3, confirmed at bar 5); break at 8, reclaim close at 9, retest at 11
        lows =   [104, 103, 102, 100, 102, 103, 104, 103, 99, 100.5, 101.5, 100.3, 101, 102, 103, 104, 105, 106]
        closes = [105, 104, 103, 101, 103, 104, 105, 104, 99.5, 101, 102, 100.8, 102, 103, 104, 105, 106, 107]
        D = self.fake(lows, closes)
        cfg = dict(EH.BASE, k=2, sides=['long'], target='2r', hold=5)
        tr = EH.trades(D, cfg, ('2024-01-01', '2024-12-31'))
        self.assertEqual(len(tr), 1)
        self.assertEqual(tr[0]['t'], 11)
        self.assertAlmostEqual(tr[0]['entry'], 100.8)
        self.assertAlmostEqual(tr[0]['level'], 100.0)

    def test_stop_first_and_gaps(self):
        EH = self.EH
        o = np.array([100, 100, 100.0]); h = np.array([100, 103, 101.0]); l = np.array([100, 97, 99.0])
        c = np.array([100, 100, 100.0])
        self.assertEqual(EH.simulate_exit(o, h, l, c, 0, 1, 100.0, 98.0, 102.0, 5, 0)[2], 'stop')   # both: stop
        o2 = np.array([100, 95, 100.0])
        t, px, why, r = EH.simulate_exit(o2, h, l, c, 0, 1, 100.0, 98.0, 102.0, 5, 0)
        self.assertEqual((why, px), ('stop', 95.0))                                                  # gap: the open


class SamStopAtrTests(unittest.TestCase):
    """studies/sam_miesse/replicate.py R11: the ATR stop reads the prior close's ATR only."""

    def test_stop_atr_uses_the_prior_day(self):
        from studies.sam_miesse.replicate import STUDY as SM
        n = 30
        c = np.full((n, 1), 10.0); o = c.copy(); h = c * 1.02; l = c * .98
        o[25] = 13.0; h[25] = 13.0 * 1.10; c[25] = 12.0; l[25] = 11.5       # a 30% gap that runs 10% higher
        h[24] = 10.2
        F = type('F', (), {})()
        F.o, F.h, F.l, F.c, F.raw = o, h, l, c, c
        F.to20 = np.full((n, 1), 1e6)
        F.atr14 = np.full((n, 1), .4)                                        # 4% of the prior close
        F.atr14[25] = 5.0                                                    # today's ATR must not be read
        F.ret = lambda k: np.zeros((n, 1))
        A = {'F': F}
        cfg = dict(SM.base, gap=.25, spike=.05, stop_atr=3.0, rule_opts=dict(SM.base['rule_opts']))
        entries, rules, m, pool = SM.build(A, cfg)
        (pr, j, side, f, st, kind, ex), = entries[25]
        self.assertAlmostEqual(f, 13.0 * 1.05)
        self.assertAlmostEqual(st, f * 1.12)                                 # 3 x 4% = 12% (above the 10% floor)
        self.assertAlmostEqual(ex, float(c[25, 0]))                          # high 14.3 < stop 15.29: out at the close


class HolguinRollTests(unittest.TestCase):
    """studies/alfredo_holguin/replicate.py R9: an in-the-money put at expiry settles, then next week's put."""

    def test_roll_settles_then_sells_next_week(self):
        from studies.alfredo_holguin import replicate as R
        days = np.array(['2025-01-0%d' % d for d in (6, 7, 8, 9)] + ['2025-01-10'] +
                        ['2025-01-1%d' % d for d in (3, 4, 5, 6, 7)])
        n = len(days)
        F = type('F', (), {})()
        F.o = np.full((n, 1), 100.0); F.c = F.o.copy(); F.h = F.o * 1.01; F.l = F.o * .99
        F.c[4] = 90.0                                                        # expiry Friday: 10 under the strike
        F.atr14 = np.full((n, 1), 5.0); F.raw = F.c; F.to20 = np.full((n, 1), 1e10)
        A = dict(F=F, days=days, iv=np.full((n, 1), .4), optvol20=np.full((n, 1), 1e6), earn={}, earn_idx={},
                 expiry=R.week_expiries(days), codes_s=['US.X'], trend=np.full((n, 1), 9.0), close=F.c)
        S = R.Holguin.__new__(R.Holguin)
        S._A = A
        S.hv = lambda A_, k: np.full((n, 1), .4)
        cfg = dict(R.DRAFT, v2=True, k=.05, margin='regt', roll=1, max_new=1, cushion=0.0, trend=0.0, iv_min=0.0,
                   turnover=0.0, optvol=0, price=0.0, min_dte=2)
        curve, dd, tr = S.simulate(cfg, '2025-01-06', '2025-01-17')
        why = [t['why'] for t in tr]
        self.assertIn('rolled', why)
        rolled = next(t for t in tr if t['why'] == 'rolled')
        self.assertEqual(rolled['exit'], '2025-01-10')
        self.assertAlmostEqual(rolled['pay'], 100.0 - 90.0)


class EmanuelaSwingTimingTests(unittest.TestCase):
    """studies/emanuela_elias/swing.py: the pullback entry is the close that reclaims the daily 10 EMA, read from
    nothing after that close."""

    def panel(self, n=330, tail=None):
        from studies.trader_screens import screens as S
        rng = np.random.default_rng(3)
        c = 50 * np.cumprod(1 + .004 + .01 * rng.standard_normal(n))
        c[300:306] = c[299] * np.array([.99, .98, .975, .97, .968, .966])     # a tight pullback
        c[306] = c[305] * 1.03                                                 # the reclaim close
        if tail is not None:
            c[307:] = tail
        h, l = c * 1.01, c * .99
        h[300:306], l[300:306] = c[300:306] * 1.003, c[300:306] * .997
        p = dict(days=np.array([str(np.datetime64('2023-01-02') + i) for i in range(n)]), codes=np.array(['US.X']),
                 open=c[:, None], high=h[:, None], low=l[:, None], close=c[:, None], volume=np.full((n, 1), 1e7),
                 turnover=np.full((n, 1), 5e8), raw_close=c[:, None])
        return {'F': S.Feat(p, 'us')}

    def test_entry_on_the_reclaim_close_and_no_lookahead(self):
        from studies.emanuela_elias.swing import STUDY, SWING
        cfg = dict(SWING, setups=['pullback'], pullback=dict(SWING['pullback'], tight=10.0))
        A = self.panel()
        e, rules, m, pool = STUDY.build(A, cfg)
        days = np.flatnonzero(m[:, 0])
        F = A['F']
        for d in days:                                   # each signal is a close crossing above the 10 EMA
            self.assertTrue(F.c[d, 0] > F.ema(10)[d, 0] and F.c[d - 1, 0] <= F.ema(10)[d - 1, 0])
            (pr, j, side, f, st, kind), = e[d]
            self.assertEqual(f, F.c[d, 0])
            self.assertLess(st, f)
        self.assertIn(306, days)
        B = self.panel(tail=1.0)                         # a crash after day 306 changes nothing up to 306
        e2, _, m2, _ = STUDY.build(B, cfg)
        np.testing.assert_array_equal(m[:307], m2[:307])
