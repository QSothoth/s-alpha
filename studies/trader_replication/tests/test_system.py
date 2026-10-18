"""Execution-timing tests of the daily portfolio: which bar exits, at what price, for which reason."""
import unittest

import numpy as np

from studies.trader_replication import system as Y


def px(rows):
    """rows: (open, high, low, close) per day for one name."""
    a = np.array(rows, float)
    T = len(a)
    return {'open': a[:, :1], 'high': a[:, 1:2], 'low': a[:, 2:3], 'close': a[:, 3:4],
            'dates': np.array(['2025-01-%02d' % (i + 1) for i in range(T)]), 'codes': np.array(['US.AAA'])}


def one(T, d, side, fill, stop):
    e = [[] for _ in range(T)]
    e[d].append((0, 0, side, fill, stop, 'x'))
    return e


NOCOST = dict(buy_cost=0, sell_cost=0, margin_rate=0)


class SystemTests(unittest.TestCase):
    def run_(self, rows, entries, ema=None, **kw):
        p = px(rows)
        e = {'e9': np.array(ema, float)[:, None]} if ema is not None else {}
        rules = Y.Rules(trail='e9' if ema is not None else '', **{**NOCOST, **kw})
        return Y.simulate(p, e, rules, entries, p['dates'][0], p['dates'][-1])

    def test_long_stop_next_day_loses_one_r(self):
        rows = [(10, 10, 10, 10), (10, 10.2, 9.4, 9.6)]
        curve, _, tr = self.run_(rows, one(2, 0, 1, 10.0, 9.5))
        self.assertEqual(tr[0]['why'], 'stop')
        self.assertAlmostEqual(tr[0]['r'], -1.0)
        self.assertAlmostEqual(curve[-1], 1 - .005)

    def test_gap_below_stop_fills_at_open(self):
        rows = [(10, 10, 10, 10), (9.0, 9.2, 8.8, 9.1)]
        _, _, tr = self.run_(rows, one(2, 0, 1, 10.0, 9.5))
        self.assertEqual(tr[0]['why'], 'gap_stop')
        self.assertAlmostEqual(tr[0]['r'], -2.0)

    def test_trims_then_trail_exit_at_close(self):
        # R = 0.5; +3R = 11.5, +5R = 12.5; armed when close > e9, exits on the first close below it
        rows = [(10, 10, 10, 10), (10.5, 11.6, 10.4, 11.4), (11.5, 12.6, 11.4, 12.4), (12.3, 12.4, 11.0, 11.1)]
        ema = [9.8, 10.2, 11.0, 11.6]
        _, _, tr = self.run_(rows, one(4, 0, 1, 10.0, 9.5), ema=ema, trims=(3, 5), trim_frac=.15)
        self.assertEqual(tr[0]['why'], 'trail')
        expect = .15 * 1.5 + .15 * 2.5 + .70 * 1.1     # per original share
        self.assertAlmostEqual(tr[0]['r'], expect / .5)

    def test_stop_wins_a_same_day_tie_unless_the_open_is_past_the_trim(self):
        rows = [(10, 10, 10, 10), (10.2, 11.6, 9.4, 9.6)]
        _, _, tr = self.run_(rows, one(2, 0, 1, 10.0, 9.5), trims=(3,))
        self.assertEqual([x for x in tr[0]['why'].split()], ['stop'])
        self.assertAlmostEqual(tr[0]['r'], -1.0)
        rows = [(10, 10, 10, 10), (11.6, 11.7, 9.4, 9.6)]
        _, _, tr = self.run_(rows, one(2, 0, 1, 10.0, 9.5), trims=(3,), trim_frac=.15)
        self.assertAlmostEqual(tr[0]['r'], (.15 * 1.6 - .85 * .5) / .5)

    def test_short_side_mirrors_stop_and_trail(self):
        rows = [(10, 10, 10, 10), (9.9, 10.6, 9.8, 10.2)]
        _, _, tr = self.run_(rows, one(2, 0, -1, 10.0, 10.5))
        self.assertEqual(tr[0]['why'], 'stop')
        self.assertAlmostEqual(tr[0]['r'], -1.0)
        rows = [(10, 10, 10, 10), (9.6, 9.7, 8.4, 8.5), (8.6, 9.3, 8.5, 9.2)]
        ema = [10.2, 9.0, 9.0]
        _, _, tr = self.run_(rows, one(3, 0, -1, 10.0, 10.5), ema=ema, trims=(3,), trim_frac=.15)
        self.assertEqual(tr[0]['why'], 'trail')
        self.assertAlmostEqual(tr[0]['r'], (.15 * 1.5 + .85 * .8) / .5)

    def test_shorts_can_have_their_own_holding_limit(self):
        rows = [(10, 10, 10, 10), (9.9, 10.0, 9.7, 9.8), (9.8, 9.9, 9.6, 9.7), (9.7, 9.8, 9.5, 9.6)]
        _, _, tr = self.run_(rows, one(4, 0, -1, 10.0, 10.5), short_max_days=2)
        self.assertEqual(tr[0]['why'], 'time')
        self.assertEqual(tr[0]['days'], 2)
        self.assertAlmostEqual(tr[0]['r'], .3 / .5)

    def test_position_cap_limits_size(self):
        rows = [(10, 10, 10, 10), (10, 12, 10, 12), (12, 12, 12, 12)]
        curve, _, tr = self.run_(rows, one(3, 0, 1, 10.0, 9.99), max_position=.3, trims=())
        self.assertAlmostEqual(curve[-1], 1 + .3 * .2)

    def test_day_zero_stop_closes_on_the_entry_day(self):
        rows = [(10, 10.5, 9.4, 9.6), (9.6, 9.8, 9.5, 9.7)]
        e = [[(0, 0, 1, 10.0, 9.5, 'x', 9.5)], []]
        curve, _, tr = self.run_(rows, e)
        self.assertEqual(tr[0]['why'], 'stop_day0')
        self.assertEqual(tr[0]['days'], 0)
        self.assertAlmostEqual(tr[0]['r'], -1.0)

    def test_no_follow_through_exits_at_the_next_close(self):
        rows = [(10, 10, 10, 10), (10.1, 10.3, 9.7, 9.8), (9.8, 11, 9.8, 11)]
        _, _, tr = self.run_(rows, one(3, 0, 1, 10.0, 9.5), nft_days=1)
        self.assertEqual(tr[0]['why'], 'no_follow')
        self.assertAlmostEqual(tr[0]['r'], -.4)

    def test_negative_feedback_halves_the_next_risk(self):
        rows = [(10, 10, 10, 10), (10, 10, 9.4, 9.6), (10, 10, 10, 10), (10, 10, 9.4, 9.6)]
        e = [[(0, 0, 1, 10.0, 9.5, 'x')], [], [(0, 0, 1, 10.0, 9.5, 'x')], []]
        curve, _, tr = self.run_(rows, e, feedback=1, risk_low=.0025)
        self.assertAlmostEqual(curve[-1], (1 - .005) * (1 - .0025))

    def test_positive_feedback_raises_the_next_risk(self):
        rows = [(10, 10, 10, 10), (10, 11, 10, 11), (11, 11, 11, 11), (11, 11, 10.4, 10.4)]
        e = [[(0, 0, 1, 10.0, 9.5, 'x')], [], [(0, 0, 1, 11.0, 10.5, 'x')], []]
        rules = dict(feedback=1, risk_low=.0025, risk_high=.01, trims=(), max_days=1)
        curve, _, tr = self.run_(rows, e, **rules)
        first = .005 / .05 * .10                     # 10% of equity, +10%, closed by the 1-day limit
        self.assertEqual([t['why'] for t in tr], ['time', 'stop'])
        self.assertAlmostEqual(tr[1]['r'], -1.0)
        self.assertAlmostEqual(curve[-1], (1 + first) * (1 - .01))   # after a winner the next trade risks 1%

    def test_size_risk_and_position_cap_overrides(self):
        rows = [(10, 10, 10, 10), (10, 11, 10, 11), (11, 11, 11, 11)]
        e = [[(0, 0, 1, 10.0, 9.9, 'x', None, .05)], [], []]          # stop 1% away, sized as if 5%
        curve, _, _ = self.run_(rows, e, trims=(), max_position=1.0)
        self.assertAlmostEqual(curve[-1], 1 + .005 / .05 * .10)       # 10% of equity gains 10%
        e = [[(0, 0, 1, 10.0, 9.9, 'x', None, None, .2)], [], []]     # stop 1% wants 50%, capped at 20%
        curve, _, _ = self.run_(rows, e, trims=(), max_position=.3)
        self.assertAlmostEqual(curve[-1], 1 + .2 * .10)

    def test_open_count_cap_skips_the_second_name(self):
        a = np.array([[10, 10, 10, 10], [10, 11, 10, 11]], float)
        p = {'open': np.repeat(a[:, :1], 2, 1), 'high': np.repeat(a[:, 1:2], 2, 1), 'low': np.repeat(a[:, 2:3], 2, 1),
             'close': np.repeat(a[:, 3:4], 2, 1), 'dates': np.array(['2025-01-01', '2025-01-02']),
             'codes': np.array(['US.AAA', 'US.BBB'])}
        e = [[(0, 0, 1, 10.0, 9.5, 'x'), (1, 1, 1, 10.0, 9.5, 'x')], []]
        _, _, tr = Y.simulate(p, {}, Y.Rules(trail='', max_open=1, **NOCOST), e, '2025-01-01', '2025-01-02')
        self.assertEqual([t['code'] for t in tr], ['US.AAA'])

    def test_exit_signal_closes_a_long_at_that_close(self):
        rows = [(10, 10, 10, 10), (10, 11, 10, 11), (11, 12, 11, 12), (12, 13, 12, 13)]
        sig = np.array([[False], [False], [True], [False]])
        p = px(rows)
        _, _, tr = Y.simulate(p, {'climax': sig}, Y.Rules(trail='', trims=(), exit_signal='climax', **NOCOST),
                              one(4, 0, 1, 10.0, 9.5), p['dates'][0], p['dates'][-1])
        self.assertEqual((tr[0]['why'], tr[0]['exit']), ('signal', '2025-01-03'))
        self.assertAlmostEqual(tr[0]['ret'], .2)

    def test_placebo_draws_from_the_pool(self):
        a = np.array([[10, 10, 10, 10], [10, 11, 10, 11]], float)
        p = {'open': np.repeat(a[:, :1], 2, 1), 'high': np.repeat(a[:, 1:2], 2, 1), 'low': np.repeat(a[:, 2:3], 2, 1),
             'close': np.repeat(a[:, 3:4], 2, 1), 'dates': np.array(['2025-01-01', '2025-01-02']),
             'codes': np.array(['US.AAA', 'US.BBB'])}
        pool = np.array([[False, True], [False, True]])
        e = [[(0, 0, 1, 10.0, 9.5, 'x')], []]
        _, _, tr = Y.simulate(p, {}, Y.Rules(trail='', **NOCOST), e, '2025-01-01', '2025-01-02',
                              placebo=np.random.default_rng(0), pool=pool)
        self.assertEqual(tr[0]['code'], 'US.BBB')
        self.assertAlmostEqual(tr[0]['risk_pct'], .05)


if __name__ == '__main__':
    unittest.main()
