"""Execution-timing tests on tiny synthetic paths (which bar fills, at what price, for which reason)."""
import unittest

import numpy as np

from studies.martin_luk import luk


def panel(rows, code='US.AAA'):
    """rows: list of (open, high, low, close) for one stock; dates 2025-01-01.."""
    a = np.array(rows, float)
    T = len(a)
    dates = np.array([f'2025-01-{i + 1:02d}' for i in range(T)])
    p = {'dates': dates, 'codes': np.array([code])}
    for k, name in enumerate(('open', 'high', 'low', 'close')):
        p[name] = a[:, k:k + 1]
    p['raw_close'] = p['close']
    return p


def ind_for(p, e9=None, adr=10.0):
    T = len(p['dates'])
    return {'e9': np.full((T, 1), np.nan) if e9 is None else np.array(e9, float)[:, None],
            'adr': np.full((T, 1), adr), 'leader': np.ones((T, 1), bool),
            'market_up': np.ones(T, bool), 'ew_ret': np.zeros(T), '_close': p['close']}


def run(p, ind, orders=None, closes=None, **cfg):
    T = len(p['dates'])
    orders = orders or [[] for _ in range(T)]
    closes = closes or [[] for _ in range(T)]
    c = luk.Config(**cfg)
    return luk.simulate(p, ind, c, p['dates'][0], p['dates'][-1], orders, closes)


def order(T, d, trig, stop):
    o = [[] for _ in range(T)]
    o[d].append((0, 0, trig, stop, 'bo'))
    return o


class Timing(unittest.TestCase):
    def test_breakout_fills_at_trigger_and_exits_at_close_without_follow_through(self):
        p = panel([(100, 101, 99, 100), (100, 103, 99.6, 101.5), (101, 102, 100, 101)])
        _, _, tr = run(p, ind_for(p), order(3, 1, 102.0, 99.5))
        t = tr[0]
        self.assertEqual((t['entry'], t['exit'], t['fill'], t['why']), ('2025-01-02', '2025-01-02', 102.0, 'nft'))

    def test_gap_above_trigger_fills_at_open(self):
        p = panel([(100, 101, 99, 100), (103, 105, 102.9, 104.5), (104, 105, 103.5, 104)])
        _, _, tr = run(p, ind_for(p, e9=[np.nan, 100, 104.5]), order(3, 1, 101.0, 98.5))
        self.assertEqual(tr[0]['fill'], 103.0)

    def test_entry_day_low_through_stop_is_stopped_conservatively_only(self):
        rows = [(100, 101, 99, 100), (100, 103, 99.0, 102.5), (102.5, 103, 102, 102.8)]
        p = panel(rows)
        _, _, tr = run(p, ind_for(p), order(3, 1, 101.0, 99.5))
        self.assertEqual((tr[0]['exit'], tr[0]['why']), ('2025-01-02', 'stop_entry_day'))
        _, _, tr = run(p, ind_for(p), order(3, 1, 101.0, 99.5), conservative=False)
        self.assertEqual(tr[0]['why'], 'end')

    def test_trim_at_3r_then_gap_stop(self):
        # fill 100, stop 98 -> 3R = 106; day 3 high 107 trims 15% at 106; day 4 opens below stop
        rows = [(99, 99.5, 98, 99), (100, 101, 99.5, 100.5), (101, 107, 100.5, 105), (97, 98, 96, 97)]
        p = panel(rows)
        ind = ind_for(p)
        o = order(4, 1, 100.0, 98.0)
        ind['adr'][:] = 10
        _, _, tr = run(p, ind, o)
        self.assertEqual(tr[0]['why'], 'gap_stop')
        # 15% sold at 106, 85% at the 97 open, 0.05% per side
        self.assertEqual(tr[0]['exit'], '2025-01-04')
        self.assertAlmostEqual(tr[0]['ret'], (.15 * 106 + .85 * 97) * .9995 / (100 * 1.0005) - 1, places=9)

    def test_trail_needs_a_close_above_ema9_first(self):
        # entry day closes below e9 (no flag); day 3 closes above (flag); day 4 closes below -> exit at close
        rows = [(99, 99.5, 98, 99), (100, 101, 99.5, 100.5), (101, 103, 100.5, 102.5),
                (102, 102.5, 100.8, 101), (101, 101, 100, 100.5)]
        p = panel(rows)
        e9 = [99, 101, 102, 101.5, 101]
        _, _, tr = run(p, ind_for(p, e9=e9), order(5, 1, 100.0, 99.0), stop_cap=.05)
        self.assertEqual((tr[0]['exit'], tr[0]['why']), ('2025-01-04', 'ema9'))

    def test_cn_t1_cannot_sell_on_entry_day(self):
        rows = [(100, 101, 99, 100), (100, 103, 99.0, 99.8), (99.5, 100, 99.2, 99.6)]
        p = panel(rows, code='SH.600000')
        _, _, tr = run(p, ind_for(p), order(3, 1, 101.0, 99.5), market='cn')
        self.assertEqual((tr[0]['exit'], tr[0]['why']), ('2025-01-03', 'nft'))

    def test_risk_wider_than_half_adr_is_skipped(self):
        p = panel([(100, 101, 99, 100), (100, 103, 99.5, 102.5), (102, 103, 101, 102)])
        ind = ind_for(p, adr=4.0)                     # cap = min(5%, 2%) and risk is 3%
        _, _, tr = run(p, ind, order(3, 1, 101.0, 98.0))
        self.assertEqual(tr, [])

    def test_close_entry_is_not_stopped_on_its_own_day(self):
        p = panel([(100, 101, 97, 100.5), (100.4, 101, 99.8, 100.8)])
        cl = [[(0, 0, 100.5, 99.0, 'pb')], []]
        _, _, tr = run(p, ind_for(p), closes=cl)
        self.assertEqual((tr[0]['entry'], tr[0]['why']), ('2025-01-01', 'end'))

    def test_sizing_risks_half_percent_of_equity(self):
        p = panel([(100, 101, 99, 100), (100, 103, 99.5, 102.5), (102.5, 104, 102, 103.5)])
        curve, _, tr = run(p, ind_for(p), order(3, 1, 101.0, 99.5))
        q = tr[0]
        shares_value = .005 / ((101 - 99.5) / 101)     # 0.5% risk / 1.485% stop = 33.7% of equity
        self.assertAlmostEqual(q['pnl'] / (shares_value / 101) / (q['fill'] - q['stop']), q['r'], places=6)


class D4(unittest.TestCase):
    def test_close_confirmed_entries_use_todays_close_and_low(self):
        # day 1 is a +12% burst closing at its high on 3x volume; day 2 closes above day 1 high -> entry at day 2 close
        rows = [(100, 101, 99, 100)] * 25 + [(100, 112.5, 99.5, 112), (112, 114, 111, 113.5), (113, 114, 112, 113)]
        p = panel(rows)
        p['turnover'] = np.full((len(rows), 1), 1e8)
        p['turnover'][25] = 3e8
        T = len(rows)
        ind = ind_for(p)
        ind.update(e21=np.full((T, 1), 99.0), r63=np.zeros((T, 1)), tradeable=np.ones((T, 1), bool),
                   adr=np.full((T, 1), 5.0), leader=np.zeros((T, 1), bool))
        cfg = luk.Config(d4=True)
        _, closes = luk.d4_signals(p, ind, cfg)
        self.assertEqual([(d, x[2], x[3], x[4]) for d in range(T) for x in closes[d]], [(26, 113.5, 111.0, 'cburst')])


if __name__ == '__main__':
    unittest.main()
