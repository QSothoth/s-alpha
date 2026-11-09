import unittest

from studies.trader_replication.martin_continue_bm import describe


class ClosedTradeStatistics(unittest.TestCase):
    def test_uses_the_requested_capital_basis(self):
        trades = [{'ret': .4, 'ret_invested': .2, 'days': 10},
                  {'ret': -.1, 'ret_invested': -.1, 'days': 2}]
        initial = describe(trades, 'ret')
        invested = describe(trades, 'ret_invested')
        self.assertEqual((initial['wins'], initial['nonwins']), (1, 1))
        self.assertEqual(initial['zeros'], 0)
        self.assertAlmostEqual(initial['payoff'], 4.)
        self.assertAlmostEqual(invested['payoff'], 2.)
        self.assertAlmostEqual(invested['mean_ret'], .05)
