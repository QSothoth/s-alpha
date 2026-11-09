import unittest
from studies.trader_replication import martin_continue_fk as fk


def trade(ret, why='trail', days=3):
    return {'entry': '2025-01-02', 'why': why, 'ret': ret, 'pnl': ret,
            'days': days, 'fill': 10., 'stop': 9., 'risk_pct': .1, 'add_tries': 0}


class TradeStatsTests(unittest.TestCase):
    def test_only_closed_trades_contribute_and_r_includes_cost(self):
        stats = fk.trade_stats([trade(.1, days=2), trade(.5, days=4), trade(-.1), trade(2, 'end')],
                               '2025', .0005, .0005)
        self.assertEqual((stats['entries'], stats['closed'], stats['open_end']), (4, 3, 1))
        self.assertAlmostEqual(stats['win_rate'], 2 / 3)
        self.assertAlmostEqual(stats['avg_win'], .3)
        self.assertAlmostEqual(stats['avg_loss'], -.1)
        self.assertAlmostEqual(stats['final_r3'], 1 / 3)
        self.assertEqual(stats['final_r5'], 0)
        self.assertEqual(stats['winner_days_median'], 3)

    def test_missing_winners_are_unknown_not_zero(self):
        stats = fk.trade_stats([trade(-.1)], '2025', .0005, .0005)
        self.assertIsNone(stats['avg_win'])
        self.assertIsNone(stats['payoff'])
        self.assertIsNone(stats['winner_days_mean'])


if __name__ == '__main__':
    unittest.main()
