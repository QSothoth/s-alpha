import unittest
from types import SimpleNamespace
import numpy as np
from studies.trader_replication import martin_continue_fm as fm, system


class AccountFunnelTests(unittest.TestCase):
    def test_preselected_keeps_precision_unknown_separate_from_gap(self):
        days = ['2024-01-01', '2024-01-02']
        d = SimpleNamespace(days=days, A={'codes': np.array(['A', 'B', 'C', 'D']),
                           'open': np.array([[10, 10, 10, 10], [10, 9.5, 9, np.nan]]),
                           'low': np.array([[10, 10, 10, 10], [9, 9, 8, np.nan]])})
        reg = [[(j, j, 1, 10., 9.5, 'n1') for j in range(4)], []]
        rows = fm.preselected(d, reg)
        self.assertEqual([r['status'] for r in rows], ['fillable', 'precision_unknown', 'gap_cancel', 'missing_open'])
        self.assertTrue(rows[0]['same_day_stop'])

    def test_trace_distinguishes_existing_position_and_slot_limit(self):
        days = ['2024-01-02', '2024-01-03']
        matrix = np.full((2, 2), 10.)
        a = {'open': matrix.copy(), 'high': matrix.copy(), 'low': matrix.copy(), 'close': matrix.copy(),
             'dates': np.array(days), 'codes': np.array(['A', 'B'])}
        d = SimpleNamespace(days=days, A=a, pool=None,
                            base=SimpleNamespace(px=lambda _: a, ema_inputs=lambda *_: {}))
        book = [[(0, 0, 1, 10., 9., 'n1'), (1, 1, 1, 10., 9., 'n1')],
                [(0, 0, 1, 10., 9., 'n1')]]
        rules = system.Rules(trail='', trims=(), max_open=1, buy_cost=0, sell_cost=0, margin_rate=0,
                             intraday_kinds=('n1',))
        targets = {('2024-01-02', 'A'), ('2024-01-02', 'B'), ('2024-01-03', 'A')}
        _, records = fm.trace_account(d, book, rules, targets)
        self.assertEqual(records[('2024-01-02', 'A')]['reason'], 'opened')
        self.assertIn('rules.max_open', records[('2024-01-02', 'B')]['reason'])
        self.assertIn('j in pos', records[('2024-01-03', 'A')]['reason'])
        self.assertEqual(records[('2024-01-03', 'A')]['held_entry'], '2024-01-02')


if __name__ == '__main__':
    unittest.main()
