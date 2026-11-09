import unittest

from studies.trader_replication.martin_continue_gl import explain


class TestGapExplanation(unittest.TestCase):
    def setUp(self):
        self.trade = ['US.X', 1, 'n1', '2025-01-02', '2025-01-09', 'stop_day0']
        self.key = ('2025-01-02', 'n1', 'US.X')

    def test_same_order_opened_but_ended_before_window(self):
        target = ['US.X', 1, 'n1', '2025-01-02', '2025-01-03', 'stop']
        result = explain(self.trade, '2025-01-06', {self.key: {'reason': 'opened'}}, {self.key: target})
        self.assertEqual(result['classification'], 'same_order_ended_earlier')
        self.assertEqual(result['target_trade'], target)

    def test_position_limit_and_missing_trace_are_distinct(self):
        reason = 'open_pos: rules.max_open and len(pos) >= rules.max_open'
        self.assertEqual(explain(self.trade, '2025-01-06', {self.key: {'reason': reason}}, {})['classification'], 'position_limit')
        self.assertEqual(explain(self.trade, '2025-01-06', {}, {})['classification'], 'not_traced')

    def test_already_held_retains_target_trade(self):
        held_key = ('2025-01-01', 'list', 'US.X')
        target = ['US.X', 1, 'list', '2025-01-01', '2025-01-03', 'stop']
        trace = {self.key: {'reason': 'already held', 'held_entry': held_key[0], 'held_kind': 'list'}}
        result = explain(self.trade, '2025-01-06', trace, {held_key: target})
        self.assertEqual(result['classification'], 'already_held')
        self.assertEqual(result['target_trade'], target)

    def test_overlapping_target_trade_is_rejected(self):
        target = ['US.X', 1, 'n1', '2025-01-02', '2025-01-07', 'stop']
        with self.assertRaises(AssertionError):
            explain(self.trade, '2025-01-06', {self.key: {'reason': 'opened'}}, {self.key: target})
