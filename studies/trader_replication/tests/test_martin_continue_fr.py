import unittest
from studies.trader_replication.martin_continue_fr import overlapping


class WinnerWindowTests(unittest.TestCase):
    def test_both_boundary_days_count_and_shorts_do_not(self):
        keys = [['A', 1, 'n1', '2025-01-01', '2025-01-05', 'trail_open'],
                ['A', 1, 'list', '2025-01-10', '2025-01-12', 'stop'],
                ['A', -1, 'short', '2025-01-06', '2025-01-07', 'stop'],
                ['A', 1, 'n1', '2025-01-01', '2025-01-04', 'stop']]
        self.assertEqual(overlapping(keys, 'A', '2025-01-05', '2025-01-10'), keys[:2])


if __name__ == '__main__':
    unittest.main()
