import unittest
from types import SimpleNamespace

import numpy as np

from studies.trader_replication.martin_continue_gp import leader_book, precision_orders


class TestLeaderBook(unittest.TestCase):
    def test_top_group_keeps_original_priority_and_fixed_count(self):
        days = ['2024-01-02', '2024-01-03']
        codes = ['US.A', 'US.B', 'US.C', 'US.D']
        entries = [(0, 0, 1, 10, 9, 'n1'), (1, 1, 1, 10, 9, 'n1'),
                   (2, 2, 1, 10, 9, 'n1'), (3, 3, 1, 10, 9, 'n1')]
        features = {(days[0], 'US.A'): False, (days[0], 'US.B'): True,
                    (days[0], 'US.C'): True, (days[0], 'US.D'): None}
        book, stats = leader_book([(0, entries, 3)], days, codes, features)
        self.assertEqual([e[1] for e in book[0]], [1, 2, 0])
        self.assertEqual((stats['selected'], stats['leader_selected']), (3, 2))

    def test_open_and_low_stop_uncertainty_are_recorded(self):
        days = ['2024-01-02', '2024-01-03']
        d = SimpleNamespace(days=days, A={'codes': ['US.A', 'US.B'],
                            'open': np.array([[10., 10.], [9., 10.]]),
                            'low': np.array([[10., 10.], [8., 9.]])})
        signals = [[(0, 0, 1, 10., 9., 'n1'), (1, 1, 1, 10., 9., 'n1')], []]
        self.assertEqual([r['reason'] for r in precision_orders(signals, d)], ['open_stop', 'low_stop'])
