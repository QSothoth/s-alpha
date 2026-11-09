import unittest
from types import SimpleNamespace
import numpy as np
from studies.trader_replication.martin_continue_gh import comparison, preselected_list


class ListReentryTest(unittest.TestCase):
    def test_selects_prior_close_top_six_without_looking_at_next_bar(self):
        d = SimpleNamespace(days=['2025-01-02', '2025-01-03'], A={'codes': np.array([f'US.{i}' for i in range(8)])})
        entries = [(i, i, 1, 100., 90., 'list') for i in range(7, -1, -1)]
        selected = preselected_list(d, [entries, []])
        self.assertEqual(set(selected), {f'US.{i}' for i in range(6)})
        self.assertEqual(selected['US.0'], [('2025-01-02', '2025-01-03')])

    def test_unknown_union_is_not_counted_as_a_closed_comparison(self):
        sample = [{'list_only_days': [], 'core': {'hit': {'status': 'closed', 'sum_pnl': .2, 'additional_entries': 0}},
                   'union': {'hit': {'status': 'order_data_unknown'}}}]
        result = comparison(sample, 'hit')
        self.assertEqual(result['paired_closed'], 0)
        self.assertEqual(result['status'], {'order_data_unknown': 1})
        self.assertIsNone(result['mean_delta'])


if __name__ == '__main__':
    unittest.main()
