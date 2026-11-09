import unittest
from types import SimpleNamespace

import numpy as np

from studies.trader_replication.martin_continue_hc import make_books
from studies.trader_replication.system import Rules, simulate


class FullBookTest(unittest.TestCase):
    def test_gap_through_order_stays_in_full_book_and_uses_daily_low(self):
        days = ['2025-01-02', '2025-01-03']
        d = SimpleNamespace(days=days, di={x: i for i, x in enumerate(days)},
                            A={'codes': np.array(['US.A']), 'close': np.array([[10.], [8.]]),
                               'open': np.array([[10.], [8.]]), 'low': np.array([[10.], [7.5]])})
        row = {'signal_day': days[0], 'day': days[1], 'code': 'US.A', 'kind': 'n1',
               'priority': [1., 0.], 'close': 10., 'stop': 9., 'size_risk': None,
               'max_position': None, 'risk_mult': None, 'add_mult': None}
        obs = {'day': days[1], 'code': 'US.A', 'kind': 'n1', 'status': 'open_at_or_below_stop',
               'opening': 8., 'low': 7.5}
        full, old, unknown = make_books(d, [row], [obs], True)
        self.assertEqual(full[1][0][6], 7.5)
        self.assertEqual(old[1], [])
        self.assertEqual(unknown, [])

    def test_touch_precision_has_two_frozen_paths(self):
        days = ['2025-01-02', '2025-01-03']
        d = SimpleNamespace(days=days, di={x: i for i, x in enumerate(days)},
                            A={'codes': np.array(['US.A']), 'close': np.array([[10.], [10.]]),
                               'open': np.array([[10.], [10.]]), 'low': np.array([[10.], [9.]])})
        row = {'signal_day': days[0], 'day': days[1], 'code': 'US.A', 'kind': 'n1',
               'priority': [1., 0.], 'close': 10., 'stop': 9., 'size_risk': None,
               'max_position': None, 'risk_mult': None, 'add_mult': None}
        obs = {'day': days[1], 'code': 'US.A', 'kind': 'n1', 'status': 'old_accepted',
               'opening': 10., 'low': 9.}
        hit, _, unknown = make_books(d, [row], [obs], True)
        nohit, _, _ = make_books(d, [row], [obs], False)
        self.assertEqual(hit[1][0][6], 9.)
        self.assertIsNone(nohit[1][0][6])
        self.assertEqual(unknown, [[days[1], 'US.A', 'n1']])


    def test_missing_open_is_reserved_then_expires_without_reallocation(self):
        days = ['2025-01-02', '2025-01-03']
        arr = np.array([[10.], [np.nan]])
        d = SimpleNamespace(days=days, di={x: i for i, x in enumerate(days)},
                            A={'codes': np.array(['US.A']), 'close': np.array([[10.], [10.]]),
                               'open': arr, 'low': np.array([[10.], [10.]])})
        row = {'signal_day': days[0], 'day': days[1], 'code': 'US.A', 'kind': 'n1',
               'priority': [1., 0.], 'close': 10., 'stop': 9., 'size_risk': None,
               'max_position': None, 'risk_mult': None, 'add_mult': None}
        obs = {'day': days[1], 'code': 'US.A', 'kind': 'n1', 'status': 'missing',
               'opening': None, 'low': 10.}
        book, _, _ = make_books(d, [row], [obs], True)
        rules = Rules(trail='', trims=(), risk=.1, max_gross=1., gross_cost=True,
                      intraday_kinds=('n1',), margin_rate=0.)
        px = {'dates': np.array(days), 'codes': d.A['codes'], 'open': arr, 'low': d.A['low'],
              'high': np.array([[10.], [10.]]), 'close': d.A['close']}
        track = {}
        _, _, trades = simulate(px, {}, rules, book, days[1], days[1], audit=True, track=track, preopen=True)
        self.assertEqual(trades, [])
        self.assertEqual(track['preopen_plans'][0]['orders'][0]['execution'], 'missing_open')

    def test_missing_low_blocks_only_an_actual_fill(self):
        days = ['2025-01-02', '2025-01-03']
        def run(opening):
            arr = np.array([[10.], [opening]])
            d = SimpleNamespace(days=days, di={x: i for i, x in enumerate(days)},
                                A={'codes': np.array(['US.A']), 'close': np.array([[10.], [opening]]),
                                   'open': arr, 'low': np.array([[10.], [np.nan]])})
            row = {'signal_day': days[0], 'day': days[1], 'code': 'US.A', 'kind': 'n1',
                   'priority': [1., 0.], 'close': 10., 'stop': 9., 'size_risk': None,
                   'max_position': None, 'risk_mult': None, 'add_mult': None}
            obs = {'day': days[1], 'code': 'US.A', 'kind': 'n1', 'status': 'missing_low',
                   'opening': opening, 'low': None}
            book, _, _ = make_books(d, [row], [obs], True)
            rules = Rules(trail='', trims=(), risk=.1, max_gross=1., gross_cost=True,
                          intraday_kinds=('n1',), margin_rate=0.)
            px = {'dates': np.array(days), 'codes': d.A['codes'], 'open': arr, 'low': d.A['low'],
                  'high': arr, 'close': d.A['close']}
            return simulate(px, {}, rules, book, days[1], days[1], audit=True, preopen=True)
        self.assertEqual(run(11.)[2], [])
        with self.assertRaisesRegex(ValueError, 'no valid same-day low'):
            run(10.)


if __name__ == '__main__':
    unittest.main()
