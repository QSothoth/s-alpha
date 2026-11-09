import unittest

from studies.trader_replication.martin_continue_ap import group


class WeightedReturn(unittest.TestCase):
    def test_uses_initial_capital_and_excludes_open_and_zero_return(self):
        def trade(ret, pnl, why='stop'):
            return {'ret': ret, 'pnl': pnl, 'why': why, 'days': 1, 'risk_pct': .02}
        result = group([trade(.1, .2), trade(-.1, -.3), trade(0, 0), trade(.5, .5, 'end')])
        self.assertEqual(result['n'], 3)
        self.assertEqual(result['open_at_end'], 1)
        self.assertEqual(result['zero_return'], 1)
        self.assertAlmostEqual(result['initial_capital_sum'], 5.)
        self.assertAlmostEqual(result['weighted_ret'], -.02)
