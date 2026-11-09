import unittest

from studies.trader_replication.martin_continue_hl import trade_stats


class BigWinnerStatsTest(unittest.TestCase):
    def test_closed_winners_and_loss_speed_preserve_big_winners(self):
        trades = [
            {'code': 'US.A', 'entry': '2025-01-02', 'why': 'trail', 'ret_invested': 1.0, 'r': 12., 'days': 20},
            {'code': 'US.A', 'entry': '2025-02-03', 'why': 'trail', 'ret_invested': .4, 'r': 6., 'days': 8},
            {'code': 'US.B', 'entry': '2025-03-03', 'why': 'stop_day0', 'ret_invested': -.02, 'r': -1., 'days': 0},
            {'code': 'US.C', 'entry': '2025-04-03', 'why': 'end', 'ret_invested': 1.5, 'r': 15., 'days': 10},
        ]
        stats = trade_stats(trades)['2025']
        self.assertEqual((stats['closed'], stats['open_at_end'], stats['wins']), (3, 1, 2))
        self.assertEqual((stats['return_30'], stats['return_30_names'], stats['return_50']), (2, 1, 1))
        self.assertEqual((stats['r5'], stats['r10'], stats['same_day_stop_loss']), (2, 1, 1))
        self.assertEqual((stats['loss_median'], stats['loss_days_median']), (.02, 0))


if __name__ == '__main__':
    unittest.main()
