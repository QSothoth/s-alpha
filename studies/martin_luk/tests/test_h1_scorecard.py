"""A broader public-stock set cannot lose profit share by changing the denominator."""
import unittest

from studies.martin_luk.h1_research import profit_overlap


class ProfitOverlapTests(unittest.TestCase):
    def test_public_losing_trade_keeps_its_positive_slice_and_peer_set_is_nested(self):
        rows = [dict(year='2025', trade=0, pnl=.2), dict(year='2025', trade=0, pnl=-.3),
                dict(year='2025', trade=1, pnl=.5, peer_h=True), dict(year='2025', trade=2, pnl=.3)]
        own, peers, gross = profit_overlap(rows, {0}, '2025')
        self.assertAlmostEqual(own/gross, .2)
        self.assertAlmostEqual((own+peers)/gross, .7)
        # Already-public peer pieces and other years are never counted twice.
        rows[0]['peer_h'] = True
        rows.append(dict(year='2024', trade=0, pnl=100.))
        self.assertEqual(profit_overlap(rows, {0}, '2025'), (own, peers, gross))

    def test_no_positive_pnl_has_no_invented_profit_share(self):
        self.assertEqual(profit_overlap([dict(year='2025', trade=0, pnl=-1.)], {0}, '2025'), (0., 0, 0.))


if __name__ == '__main__':
    unittest.main()
