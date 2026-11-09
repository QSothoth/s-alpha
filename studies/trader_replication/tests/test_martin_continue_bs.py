import unittest

from studies.trader_replication.martin_continue_bs import key_trades, summarize


class TradeAttributionTests(unittest.TestCase):
    def test_closed_and_open_mark_are_separate_and_returns_are_capital_weighted(self):
        rows = [dict(entry='2025-01-02', code='A', side=1, kind='cand', why='stop', ret=-.1,
                     ret_invested=-.1, pnl=-.02, risk_pct=.05,
                     executions=[dict(price=2., shares=.1)]),
                dict(entry='2025-01-03', code='B', side=1, kind='cand', why='trail', ret=.5,
                     ret_invested=.5, pnl=.05, risk_pct=.03,
                     executions=[dict(price=2., shares=.05)]),
                dict(entry='2025-01-03', code='C', side=1, kind='cand', why='end', ret=1.,
                     ret_invested=1., pnl=.2, risk_pct=.03,
                     executions=[dict(price=2., shares=.1)])]
        result = summarize(rows, {'2025-01-02': 1., '2025-01-03': .9})
        self.assertEqual(result['closed'], 2)
        self.assertEqual(result['open_at_end'], 1)
        self.assertAlmostEqual(result['closed_pnl'], .03)
        self.assertAlmostEqual(result['open_mark_pnl'], .2)
        self.assertAlmostEqual(result['weighted_ret'], .03 / .3)
        self.assertEqual(result['at_least_30pct'], 1)

    def test_duplicate_trade_identity_is_rejected(self):
        t = dict(entry='2025-01-02', code='A', side=1, kind='cand')
        with self.assertRaises(ValueError):
            key_trades([t, t])


if __name__ == '__main__':
    unittest.main()
