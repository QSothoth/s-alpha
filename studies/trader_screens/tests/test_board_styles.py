import unittest

from studies.trader_replication import systems as SY
from studies.trader_screens import board, scan


def put(**k):
    return dict(dict(code='US.TSLA', name='Tesla', day='2026-10-27', setup='卖 Put', side=1, price=4.0, stop=None,
                     weight=.05, stage='open', option=dict(strike=400.0, expiry='2026-10-30', premium=4.0, spot=440.0)), **k)


class BoardStyles(unittest.TestCase):
    def test_every_board_system_has_a_style_and_new_styles_are_us_only(self):
        for x in SY.board():
            self.assertTrue(x.style, x.id)
        ids = {x.id for x in SY.board('hk')}
        self.assertNotIn('evan_medeiros', ids)
        self.assertNotIn('alfredo_holguin', ids)
        self.assertTrue({'evan_medeiros', 'alfredo_holguin'} <= {x.id for x in SY.board('us')})
        self.assertEqual([x.id for x in SY.all_()], [x.id for x in SY.board('cn')])   # the comparison set unchanged

    def test_style_column_in_the_overview(self):
        t = dict(id='x', name='Alfredo Holguin', style='卖 Put 收租', version='ERR7', status='research', buys=[put()],
                 sells=[], holdings=[], wanted=[], wanted_n=0, gate_today=None, check=dict(status='missing'),
                 account=dict(exposure=.05, ret=.1, maxdd=.05), forward=dict(days=0, ret=0.0),
                 strategy={'选股与形态': 'a', '入场与止损': 'b', '离场': 'c', '仓位与市况': 'd'})
        r = dict(market='us', last_day='2026-10-27', days=1, state=dict(above_ema20=True, above_ema50=True),
                 traders=[t], common=scan.overlaps([t], {}))
        md = board.render(r)
        self.assertIn('| 交易员 | 流派 | 版本 |', md)
        self.assertIn('| Alfredo Holguin | 卖 Put 收租 |', md)
        self.assertIn('卖 Put（开盘） TSLA Tesla：执行价 400.00（低于现价 9%），10-30 到期', md)
        self.assertIn('卖 Put TSLA', board.today_text(t))
        self.assertIn('权利金是估算值', md)

    def test_puts_are_not_overlaps_and_holdings_read_strike_and_expiry(self):
        a = dict(name='A', buys=[put()], holdings=[], sells=[])
        b = dict(name='B', buys=[dict(put(), option=None)], holdings=[], sells=[])
        c = scan.overlaps([a, b], {})
        self.assertEqual(c['bought'], [])
        self.assertEqual(c['shorted'], [])
        h = dict(put(), close=440.0, entry_day='2026-10-27')
        self.assertIn('执行价 400.00，10-30 到期；现价 440.00（高出执行价 10%）', board.exit_text(h))


if __name__ == '__main__':
    unittest.main()
