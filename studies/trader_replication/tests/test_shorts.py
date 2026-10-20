"""The short side (shorts.py): the stop rule, the day's order (longs before shorts), the market gate's timing, the
wrapper passing a long-only configuration through untouched, and the engine's cover on the next day."""
import unittest
from dataclasses import replace

import numpy as np

from studies.trader_replication import shorts as SH, system as Y


def arrays(rows, n=1):
    """rows: (open, high, low, close) of one name; n copies side by side."""
    a = np.array(rows, float)
    rep = lambda k: np.repeat(a[:, k:k + 1], n, axis=1)
    days = np.array(['2025-01-%02d' % (i + 1) for i in range(len(a))])
    return dict(open=rep(0), high=rep(1), low=rep(2), close=rep(3), raw=rep(3), to20=np.full((len(a), n), 50e6),
                adr=np.full((len(a), n), 5.0), has=np.isfinite(rep(3)), days=days,
                codes=np.array([f'US.S{j}' for j in range(n)]), market='us')


ROWS = [(10, 10.2, 9.8, 10), (10, 10.4, 9.7, 10.0), (10.6, 10.8, 10.1, 10.5), (10.2, 10.3, 9.5, 9.6)]


class FakeStudy:
    """A long system that buys name 0 on day 1; its short setup flags name 1 on day 1."""
    root = None
    ledger = None

    def build(self, A, cfg, trace=None):
        e = [[] for _ in A['days']]
        e[1].append((5.0, 0, 1, 10.0, 9.7, 'long'))
        rules = Y.Rules(buy_cost=0, sell_cost=0, margin_rate=0, trail='', trims=(), risk=.01, max_position=10.0,
                        max_gross=10.0)
        return e, rules, np.zeros(A['close'].shape, bool), np.ones(A['close'].shape, bool)

    def short_setups(self, A, sc):
        m = np.zeros(A['close'].shape, bool)
        m[1, 1] = True
        return {'x': m}, np.ones(A['close'].shape, bool)

    def px(self, A):
        return dict(open=A['open'], high=A['high'], low=A['low'], close=A['close'], dates=A['days'], codes=A['codes'])

    def ema_inputs(self, A, pool, rules):
        return {}


class StopRuleTests(unittest.TestCase):
    def test_stop_is_the_day_high_with_a_one_percent_floor(self):
        A = arrays(ROWS)
        m = np.zeros((4, 1), bool)
        m[1, 0] = True
        (e,) = SH.short_entries(A, {'x': m}, {})[1]
        self.assertEqual((e[2], e[3], e[4], e[5]), (-1, 10.0, 10.4, 's_x'))
        A['high'][1, 0] = 10.02                          # high only 0.2% above the close: the floor takes over
        (e,) = SH.short_entries(A, {'x': m}, {})[1]
        self.assertAlmostEqual(e[4], 10.1)

    def test_cap_moves_a_wide_stop_down(self):
        A = arrays(ROWS)
        m = np.zeros((4, 1), bool)
        m[1, 0] = True
        (e,) = SH.short_entries(A, {'x': m}, {'stop_cap': .02})[1]
        self.assertAlmostEqual(e[4], 10.2)

    def test_risk_mult_sizes_through_size_risk(self):
        A = arrays(ROWS)
        m = np.zeros((4, 1), bool)
        m[1, 0] = True
        (e,) = SH.short_entries(A, {'x': m}, {'risk_mult': .5})[1]
        self.assertAlmostEqual(e[7], .04 / .5)


class LevelEntryTests(unittest.TestCase):
    def level(self, rows, lv=10.3, **sc):
        A = arrays(rows)
        armed = np.zeros((len(rows), 1), bool)
        armed[1, 0] = True
        return SH.short_entries(A, {'x': {'armed': armed, 'level': np.full((len(rows), 1), lv)}},
                                dict(stop_w=.02, **sc))[1]

    def test_fills_at_the_level_when_the_day_trades_up_to_it(self):
        (e,) = self.level([(10, 10.2, 9.8, 10), (10.0, 10.4, 9.7, 9.8)])
        self.assertEqual((e[2], e[3], e[5], e[6]), (-1, 10.3, 's_x', None))
        self.assertAlmostEqual(e[4], 10.3 * 1.02)

    def test_no_fill_when_the_day_stays_under_or_opens_above(self):
        self.assertEqual(self.level([(10, 10.2, 9.8, 10), (10.0, 10.2, 9.7, 9.8)]), [])
        self.assertEqual(self.level([(10, 10.2, 9.8, 10), (10.5, 10.6, 9.7, 9.8)]), [])

    def test_sell_stop_below_fills_on_the_way_down(self):
        A = arrays([(10, 10.2, 9.8, 10), (10.0, 10.05, 9.5, 9.6)])
        armed = np.array([[False], [True]])
        m = {'x': {'armed': armed, 'level': np.full((2, 1), 9.8), 'below': True}}
        (e,) = SH.short_entries(A, m, {'stop_w': .03})[1]
        self.assertEqual((e[3], e[6]), (9.8, None))
        self.assertAlmostEqual(e[4], 9.8 * 1.03)
        A['open'][1, 0] = 9.7                                          # opens under the level: the open
        (e,) = SH.short_entries(A, m, {'stop_w': .03})[1]
        self.assertEqual(e[3], 9.7)
        A['open'][1, 0], A['high'][1, 0] = 10.0, 10.2                   # the high also reaches the stop: stopped
        (e,) = SH.short_entries(A, m, {'stop_w': .03})[1]
        self.assertAlmostEqual(e[6], e[4])
        A['low'][1, 0] = 9.9                                           # never trades down to it: nothing
        self.assertEqual(SH.short_entries(A, m, {'stop_w': .03})[1], [])

    def test_open_entry_with_a_stop_line_known_before_the_day(self):
        A = arrays([(10, 10.2, 9.8, 10), (9.9, 10.3, 9.5, 9.6)])
        armed = np.array([[False], [True]])
        line = np.full((2, 1), 10.4)
        (e,) = SH.short_entries(A, {'x': {'armed': armed, 'at_open': True, 'stop_line': line}}, {})[1]
        self.assertEqual((e[3], e[4], e[6]), (9.9, 10.4, None))
        line[:] = 9.92                                                 # under the floor: 1% above the fill
        (e,) = SH.short_entries(A, {'x': {'armed': armed, 'at_open': True, 'stop_line': line}}, {})[1]
        self.assertAlmostEqual(e[4], 9.999)

    def test_stop_wider_than_k_adr_is_skipped(self):
        A = arrays([(10, 10.2, 9.8, 10), (9.9, 10.3, 9.5, 9.6)])     # ADR 5% on the test panel
        armed = np.array([[False], [True]])
        line = np.full((2, 1), 10.8)                                   # 9.1% above the 9.9 open fill
        m = {'x': {'armed': armed, 'at_open': True, 'stop_line': line}}
        self.assertEqual(len(SH.short_entries(A, m, {})[1]), 1)
        self.assertEqual(SH.short_entries(A, m, {'max_width_adr': 1.5})[1], [])   # 9.1% > 7.5%
        self.assertEqual(len(SH.short_entries(A, m, {'max_width_adr': 2.0})[1]), 1)
        mc = np.zeros((2, 1), bool)
        mc[1, 0] = True                                                # a close entry: stop at the high 10.3
        self.assertEqual(SH.short_entries(A, {'x': mc}, {'max_width_adr': 1.5})[1][0][4], 10.3)   # 7.3% <= 7.5%
        self.assertEqual(SH.short_entries(A, {'x': mc}, {'max_width_adr': 1.0})[1], [])

    def test_risk_mult_sizes_level_entries_too(self):
        (e,) = self.level([(10, 10.2, 9.8, 10), (10.0, 10.4, 9.7, 9.8)], risk_mult=.5)
        self.assertAlmostEqual(e[7], .04)

    def test_stopped_the_same_day_when_the_high_reaches_the_stop(self):
        (e,) = self.level([(10, 10.2, 9.8, 10), (10.0, 10.6, 9.7, 10.4)])
        self.assertAlmostEqual(e[6], e[4])

    def test_cap_width_is_half_the_prior_adr_at_most_five_percent(self):
        A = arrays([(10, 10.2, 9.8, 10)] * 3)
        A['adr'][1, 0] = 4.0
        self.assertAlmostEqual(SH.level_width(A, {}, 2, 0), .02)
        A['adr'][1, 0] = 1.0
        self.assertAlmostEqual(SH.level_width(A, {}, 2, 0), .01)          # the 1% floor
        A['adr'][1, 0] = 30.0
        self.assertAlmostEqual(SH.level_width(A, {}, 2, 0), .05)


class OrderAndGateTests(unittest.TestCase):
    def test_longs_come_before_shorts_whatever_their_priority(self):
        longs = [[(9.0, 0, 1, 10, 9, 'l')]]
        shorts = [[(-1e9, 1, -1, 10, 11, 's_x')]]
        day = sorted(SH.combine(longs, shorts)[0], key=lambda e: e[0])
        self.assertEqual([e[2] for e in day], [1, -1])

    def test_gate_can_require_several_closes_under(self):
        A = arrays([(10, 10, 10, 10)] * 6, n=1)
        A['_short_index'] = np.array([1.0, .5, .5, .5, .5, .5])
        self.assertEqual(list(SH.gate_days(A, 'below3x3')), [False, False, False, False, True, True])

    def test_gate_uses_the_previous_close(self):
        A = arrays([(10, 10, 10, 10)] * 3, n=1)
        A['close'] = np.array([[10.0], [8.0], [8.0]])
        A['raw'] = A['close']
        A['_short_index'] = np.array([1.0, .5, .5])       # the index falls on day 1
        g = SH.gate_days(A, 'below3')
        self.assertEqual(list(g), [False, False, True])  # day 1's fall allows shorts from day 2 on


class WrapperTests(unittest.TestCase):
    def test_long_only_configuration_is_passed_through(self):
        A = arrays(ROWS, n=2)
        st = SH.LongShort(FakeStudy())
        e1, r1, _, p1 = st.build(A, {'x': 1})
        e2, r2, _, p2 = FakeStudy().build(A, {'x': 1})
        self.assertEqual(e1, e2)
        self.assertEqual(r1, r2)

    def test_short_entered_at_the_close_and_covered_at_the_open_above_its_stop(self):
        A = arrays(ROWS, n=2)
        st = SH.LongShort(FakeStudy())
        e, rules, _, pool = st.build(A, {'short': {'setups': ['x'], 'borrow': 0.0}})
        self.assertEqual([x[2] for x in sorted(e[1], key=lambda x: x[0])], [1, -1])
        curve, _, tr = Y.simulate(st.px(A), {}, rules, e, A['days'][0], A['days'][-1], audit=True)
        (s,) = [t for t in tr if t['side'] < 0]
        self.assertEqual((s['entry'], s['fill'], s['stop']), ('2025-01-02', 10.0, 10.4))
        self.assertEqual((s['exit'], s['why']), ('2025-01-03', 'gap_stop'))   # opens 10.6 > 10.4
        self.assertEqual(s['executions'][-1]['price'], 10.6)
        self.assertLess(s['pnl'], 0)

    def test_short_rules_get_their_own_management(self):
        r = SH.short_rules(Y.Rules(), {'trail': 'ema10', 'trims': [2, 4], 'trim_frac': .25, 'max_days': 5}, ['s_x'])
        self.assertEqual(r.management_by_kind['s_x'], {'trail': 'ema10', 'trim_frac': .25})
        self.assertEqual((r.short_trims, r.short_max_days, r.borrow_rate), ((2, 4), 5, SH.BORROW))

    def test_short_only_drops_the_longs(self):
        A = arrays(ROWS, n=2)
        only, _, _ = SH.LongShort(FakeStudy()).short_only(A, {'short': {'setups': ['x']}})
        self.assertEqual([e[2] for lst in only for e in lst], [-1])


if __name__ == '__main__':
    unittest.main()
