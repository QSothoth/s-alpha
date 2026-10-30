"""Board, scan and snapshot fixes of the 2026-10-25 strategy review (reports/STRATEGY_REVIEW_20261025_CN.md)."""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from studies.trader_screens import board, intraday as I, scan

NY = ZoneInfo('America/New_York')
STRATEGY = {k: '' for k in ('选股与形态', '入场与止损', '离场', '仓位与市况')}


def trader(name, **kw):
    return dict(dict(id=name, name=name, version='toy', status='research', gate_today=None,
                     account=dict(exposure=0, ret=0, maxdd=0), forward=dict(days=0), buys=[], sells=[], holdings=[],
                     wanted=[], wanted_n=0, strategy=STRATEGY), **kw)


def result(traders, days=1):
    return dict(days=days, market='us', last_day='2026-10-23', state=dict(above_ema20=True, above_ema50=True),
                traders=traders, common={})


class Board(unittest.TestCase):
    def test_missing_reference_is_not_reported_as_all_consistent(self):
        """R10."""
        text = board.render(result([trader('A', check=dict(ok=True, status='passed')),
                                    trader('B', check=dict(ok=None, status='missing'))]))
        self.assertNotIn('全部一致', text)
        self.assertIn('美股 B 没有同配置、同代码的比对表参考', text)
        text = board.render(result([trader('A', check=dict(ok=True, status='passed'))]))
        self.assertIn('全部一致', text)

    def test_short_plan_shows_every_rule(self):
        """R09: the day partial and the holding limit of a short, a long's signal trim and breakeven."""
        h = dict(code='US.A', side=-1, stop=11, trail=None, trail_name='', next_trim=None, next_target=None,
                 day_trim_pending=False, days=0, short_trim_day_pending=True, short_trim_day=1, short_trim_day_frac=.5,
                 max_days=5)
        text = board.exit_text(h)
        self.assertIn('第1天收盘盈利平空50%（明天）', text)
        self.assertIn('第5天收盘平空（5天后）', text)
        h = dict(code='US.A', side=1, stop=9, trail=None, trail_name='', next_trim=None, next_add=None,
                 day_trim_pending=False, days=2, trim_signal='ext10_30', trim_signal_frac=1 / 3, breakeven=12.0,
                 max_days=0)
        text = board.exit_text(h)
        self.assertIn('收盘高出 10 日线 30%卖33%', text)
        self.assertIn('到 12.00 止损移到成本', text)

    def test_intraday_fills_are_not_closing_orders(self):
        """R09: a short sold at the open is listed as already filled in the simulation, not as a closing order."""
        t = trader('A', buys=[dict(code='US.X', day='2026-10-23', setup='s_ptop', side=-1, price=10., stop=11.,
                                   weight=.1, stage='intraday'),
                              dict(code='US.Y', day='2026-10-23', setup='ep', side=1, price=20., stop=19.,
                                   weight=.1, stage='close')])
        r = dict(result([t]), provisional=dict(now='2026-10-23T15:45:00', snapshot_names=10))
        lines = board.orders(r)
        cut = lines.index('今天盘中已在模拟里成交（开盘或盘中价位，不是尾盘要下的单）：')
        self.assertTrue(any('Y' in x for x in lines[:cut]))
        self.assertFalse(any('X' in x and '开空' in x for x in lines[:cut]))
        self.assertTrue(any('X' in x for x in lines[cut:]))
        self.assertIn('开空（盘中） X', '\n'.join(board.trader(t, 1)))


class Overlaps(unittest.TestCase):
    def test_window_overlap_keeps_each_traders_days(self):
        """R12: bought by both inside the window, not on the same day."""
        traders = [dict(name='A', buys=[dict(code='US.X', day='2026-10-19', side=1)], holdings=[]),
                   dict(name='B', buys=[dict(code='US.X', day='2026-10-23', side=1)], holdings=[]),
                   dict(name='C', buys=[dict(code='US.X', day='2026-10-23', side=1)], holdings=[])]
        row = scan.overlaps(traders, {})['bought'][0]
        self.assertEqual(row['days'], {'A': ['2026-10-19'], 'B': ['2026-10-23'], 'C': ['2026-10-23']})
        self.assertEqual(row['same_day'], ['B', 'C'])
        row = scan.overlaps(traders[:2], {})['bought'][0]
        self.assertEqual(row['same_day'], [])


class QuoteAge(unittest.TestCase):
    def test_dated_snapshot_older_than_the_age_limit_is_refused(self):
        """R07: an OpenD snapshot whose newest quote is hours old is not today's price."""
        snap = {'US.A': dict(trading=True, time='2026-10-23 09:30:00')}
        with self.assertRaisesRegex(I.Refused, 'older than'):
            I.check_time('us', snap, '2026-10-23', datetime(2026, 10, 23, 15, 50, tzinfo=NY))
        snap = {'US.A': dict(trading=True, time='2026-10-23 15:49:00'),
                'US.B': dict(trading=True, time='2026-10-23 11:00:00')}      # one quiet name is fine
        self.assertEqual(I.check_time('us', snap, '2026-10-23', datetime(2026, 10, 23, 15, 50, tzinfo=NY))['newest'],
                         '2026-10-23 15:49:00')

    def test_after_the_close_the_age_counts_to_the_close(self):
        snap = {'US.A': dict(trading=True, time='2026-10-23 15:59:59')}
        I.check_time('us', snap, '2026-10-23', datetime(2026, 10, 23, 16, 40, tzinfo=NY))


if __name__ == '__main__':
    unittest.main()
