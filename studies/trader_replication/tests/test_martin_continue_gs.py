import unittest
import numpy as np
from studies.trader_replication.martin_continue_gs import opportunity


def arrays(rows):
    a = np.array(rows, dtype=float)
    return tuple(a[:, i] for i in range(4))


class TestBreakoutBounds(unittest.TestCase):
    def test_intraday_low_may_precede_breakout(self):
        px = arrays([(10, 11, 9.5, 10), (10, 11.5, 8.5, 11), (15, 15, 15, 15)])
        x = opportunity(px, 1, 9, 'break')
        self.assertEqual(x['reason'], 'intraday_trigger')
        self.assertEqual((x['outcomes']['hit30']['lower'], x['outcomes']['hit30']['upper']), (False, True))

    def test_gap_trigger_then_stop_has_no_entry_order_ambiguity(self):
        px = arrays([(10, 11, 9.5, 10), (12, 12.2, 8.5, 10)])
        x = opportunity(px, 1, 9, 'break')
        self.assertEqual(x['reason'], 'opening')
        self.assertEqual((x['outcomes']['hit30']['lower'], x['outcomes']['hit30']['upper']), (False, False))

    def test_unreached_and_ambiguous_trigger_are_separate(self):
        px = arrays([(10, 11, 9.5, 10), (10, 10.5, 9.5, 10)])
        self.assertEqual(opportunity(px, 1, 9, 'break')['status'], 'not_triggered')
        px = arrays([(10, 11, 9.5, 10), (10, 11, 9.5, 10)])
        self.assertEqual(opportunity(px, 1, 9, 'break')['reason'], 'high_trigger_precision')

    def test_missing_later_bar_preserves_known_lower_but_unknown_upper(self):
        from studies.trader_replication.martin_continue_gs import bounds_summary
        px = arrays([(10, 11, 9.5, 10), (10, 11.5, 8.5, 11), (np.nan, 15, 12, 14)])
        trade = opportunity(px, 1, 9, 'break')
        event = trade['outcomes']['hit30']
        self.assertEqual((event['lower'], event['upper']), (False, None))
        stats = bounds_summary([{'break': trade}], 'break')['hit30']
        self.assertEqual((stats['lower_hits'], stats['upper_hits_including_unknown'],
                          stats['unresolved_price_or_tail']), (0, 1, 1))

    def test_stop_and_target_same_day_allow_both_orders(self):
        px = arrays([(10, 11, 9.5, 10), (12, 16, 8.5, 12)])
        result = opportunity(px, 1, 9, 'break')['outcomes']['hit30']
        self.assertEqual((result['lower'], result['upper']), (False, True))
        self.assertEqual(result['reason'], 'same_day_both')
