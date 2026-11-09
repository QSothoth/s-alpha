import unittest
from studies.trader_replication.martin_continue_gj import explain_order, pnl_components


def trade(code, entry, exit_day, pnl, why='stop', kind='n1'):
    return {'code': code, 'kind': kind, 'entry': entry, 'exit': exit_day, 'why': why, 'pnl': pnl, 'r': pnl}


class AttributionTest(unittest.TestCase):
    def test_same_order_ended_before_window_is_not_rejected(self):
        old = trade('A', '2025-01-02', '2025-01-20', .1)
        new = trade('A', '2025-01-02', '2025-01-06', -.1)
        trace = {('2025-01-02', 'n1', 'A'): {'reason': 'opened'}}
        result = explain_order(old, [new], trace, {}, 'L1_hit', '2025-01-10')
        self.assertEqual(result['classification'], 'opened_ended_before_window')
        self.assertEqual(result['other_exit'], '2025-01-06')

    def test_precision_unknown_not_counted_as_cancel(self):
        new = trade('A', '2025-01-02', '2025-01-20', .1)
        order = {('2025-01-02', 'n1', 'A'): {'old_open_stop_precision_unknown': True, 'old_cancel': False}}
        result = explain_order(new, [], {}, order, 'L0', '2025-01-10')
        self.assertEqual(result['classification'], 'old_stop_precision_unknown')

    def test_unclosed_match_not_misclassified_as_unique(self):
        old = [trade('A', '2025-01-02', '2025-01-05', .1),
               trade('B', '2025-01-03', '2025-01-06', -.05)]
        new = [trade('A', '2025-01-02', '2026-10-16', .2, 'end'),
               trade('C', '2025-01-04', '2025-01-08', .3)]
        z = pnl_components(old, new)['2025']
        self.assertEqual(z['end_marked_keys'], 1)
        self.assertAlmostEqual(z['end_marked_old_closed']['net'], .1)
        self.assertAlmostEqual(z['old_only']['net'], -.05)
        self.assertAlmostEqual(z['new_only']['net'], .3)


if __name__ == '__main__':
    unittest.main()
