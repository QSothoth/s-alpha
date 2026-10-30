import unittest

from studies.trader_screens import board, focus


DAY = '2026-10-28'


def row(**changes):
    return dict(dict(code='US.TEST', name='Test', side=1, day=DAY, entry_day='2026-10-20',
                     setup='brk', stage='close', weight=.1, price=10, stop=9, ret=0, full=True,
                     why='跌破止损', trail=None), **changes)


def trader(name, buys=(), sells=(), holdings=()):
    return dict(id=name, name=name, buys=list(buys), sells=list(sells), holdings=list(holdings),
                version='test', status='frozen', style='test', wanted=[], wanted_n=0,
                account=dict(exposure=.1, ret=0, maxdd=0), gate_today=True, forward=dict(days=0),
                strategy={k: 'test' for k in ('选股与形态', '入场与止损', '离场', '仓位与市况')})


def run(*traders, days=1):
    return dict(market='us', last_day=DAY, days=days, traders=list(traders),
                state=dict(above_ema20=True, above_ema50=True))


class StockFocusTests(unittest.TestCase):
    def test_new_entry_joins_another_traders_old_position_without_double_counting(self):
        g, = focus.stock_groups(run(trader('A', holdings=[row()]),
                                   trader('B', buys=[row()], holdings=[row(entry_day=DAY)])))
        self.assertEqual(g['labels'], ['新开加入老持仓', '共同持多'])
        self.assertEqual(g['trader_count'], 2)
        self.assertEqual(focus.holding_text(g), '持多：A、B')
        self.assertEqual(focus.event_text(g, True), 'B 开多')

    def test_cover_is_an_exit_not_a_long_entry_or_current_short_position(self):
        g, = focus.stock_groups(run(trader('A', sells=[row(side=-1)]),
                                   trader('B', buys=[row()], holdings=[row(entry_day=DAY)])))
        self.assertFalse(g['conflict'])
        self.assertEqual(focus.holding_text(g), '持多：B')
        self.assertEqual(focus.event_text(g, False), 'A 平空')
        self.assertNotIn('A', focus.event_text(g, True))
        self.assertEqual(focus.action(row(side=-1, full=False), False), '平空（部分）')

    def test_current_opposite_positions_and_exit_vs_other_holder_are_distinct(self):
        g, = focus.stock_groups(run(trader('A', holdings=[row(side=-1)]), trader('B', holdings=[row()])))
        self.assertEqual(g['labels'], ['当前多空分歧'])
        g, = focus.stock_groups(run(trader('A', sells=[row()]), trader('B', holdings=[row()])))
        self.assertEqual(g['labels'], ['退出与持有并存'])
        g, = focus.stock_groups(run(trader('A', sells=[row(full=False)], holdings=[row()])))
        self.assertFalse(g['focus'])

    def test_same_day_stop_is_not_reported_as_a_current_holding(self):
        g, = focus.stock_groups(run(trader('A', buys=[row()], sells=[row()]),
                                   trader('B', buys=[row()], holdings=[row(entry_day=DAY)])))
        self.assertIn('同日多人开多', g['labels'])
        self.assertNotIn('共同持多', g['labels'])
        self.assertEqual(focus.holding_text(g), '持多：B')
        self.assertIn('A 开多，现已不持有', focus.event_text(g, True))

    def test_adds_skipped_entries_and_repeated_trades_do_not_create_new_entry_consensus(self):
        for other in (row(setup='加码'), row(limit_up=True)):
            g, = focus.stock_groups(run(trader('A', buys=[row(), row()]), trader('B', buys=[other])))
            self.assertFalse(g['focus'])
        self.assertEqual(focus.action(row(setup='加码', side=-1), True), '加空')
        g, = focus.stock_groups(run(trader('A', buys=[row(limit_up=True)])))
        self.assertIn('涨停跳过', focus.event_text(g, True))
        self.assertNotIn('现已不持有', focus.event_text(g, True))

    def test_multi_day_entries_only_agree_when_dates_match(self):
        g, = focus.stock_groups(run(trader('A', buys=[row(day='2026-10-27')]),
                                   trader('B', buys=[row()]), days=5))
        self.assertFalse(g['focus'])
        self.assertIn('10-27 A', focus.event_text(g, True))
        g, = focus.stock_groups(run(trader('A', buys=[row(side=-1)]),
                                   trader('B', buys=[row()]), days=5))
        self.assertEqual(g['labels'], ['同日多空新开'])

    def test_puts_do_not_create_stock_consensus(self):
        groups = focus.stock_groups(run(trader('A', holdings=[row()]),
                                        trader('B', holdings=[row(option={'strike': 8})])))
        self.assertEqual(len(groups), 2)
        self.assertFalse(any(g['focus'] for g in groups))
        self.assertEqual(groups[1]['labels'], ['期权单列'])
        self.assertEqual(focus.holding_text(groups[1]), '卖 Put：B')

    def test_common_exits_are_separate_from_entries_and_count_distinct_traders(self):
        g, = focus.stock_groups(run(trader('A', sells=[row(), row(full=False)]),
                                   trader('B', sells=[row(full=False)])))
        self.assertEqual(g['labels'], ['共同退出多头'])
        self.assertEqual(focus.event_text(g, True), '—')
        self.assertEqual(focus.holding_text(g), '当前无持仓')
        g, = focus.stock_groups(run(trader('A', sells=[row(side=-1)]),
                                   trader('B', sells=[row(side=-1)])))
        self.assertEqual(g['labels'], ['共同退出空头'])
        for second in (row(side=-1), row(day='2026-10-27')):
            g, = focus.stock_groups(run(trader('A', sells=[row(), row(full=False)]),
                                       trader('B', sells=[second]), days=5))
            self.assertFalse(g['focus'])

    def test_markdown_prioritizes_comparison_and_keeps_full_accounts_expandable(self):
        result = run(trader('A', holdings=[row()]), trader('B', buys=[row()], holdings=[row(entry_day=DAY)]),
                     trader('C', sells=[row(code='US.EXIT', side=-1)]))
        text = board.render(result)
        self.assertLess(text.index('共识与分歧'), text.index('交易员账户概览'))
        self.assertIn('| 股票 | 共性 / 差异 | 当前持仓 | 新开 / 加仓 | 退出 / 减仓 |', text)
        self.assertIn('<details><summary>按交易员查看持仓、成交与离场线', text)
        self.assertIn('C 平空', text)
        self.assertIn('下一交易日离场线', text)
        self.assertIn('平空＝买回股票，结束或减少空头仓位（回补）', text)


if __name__ == '__main__':
    unittest.main()
