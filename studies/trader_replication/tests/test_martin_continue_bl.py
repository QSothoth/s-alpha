import unittest

from studies.trader_replication.martin_continue_bl import counts


class ExecutionCounts(unittest.TestCase):
    def test_marks_are_not_orders_and_partial_exits_are_separate(self):
        trades = [
            {'side': 1, 'entry': '2024-12-31', 'exit': '2025-01-05', 'why': 'stop', 'executions': [
                {'time': '2024-12-31', 'action': 'entry'}, {'time': '2025-01-02', 'action': 'add'},
                {'time': '2025-01-03', 'action': 'trim'}, {'time': '2025-01-05', 'action': 'stop'}]},
            {'side': -1, 'entry': '2025-01-02', 'exit': '2025-12-31', 'why': 'end', 'executions': [
                {'time': '2025-01-02', 'action': 'entry'}, {'time': '2025-01-03', 'action': 'target'},
                {'time': '2025-12-31', 'action': 'end'}]}]
        result = counts(trades, '2025')
        self.assertEqual(result['long']['positions_opened'], 0)
        self.assertEqual(result['long']['positions_closed'], 1)
        self.assertEqual(result['long']['exit_legs'], 2)
        self.assertEqual(result['long']['execution_events'], 3)
        self.assertEqual(result['short']['positions_opened'], 1)
        self.assertEqual(result['short']['positions_closed'], 0)
        self.assertEqual(result['short']['mark_end'], 1)
        self.assertEqual(result['short']['execution_events'], 2)
