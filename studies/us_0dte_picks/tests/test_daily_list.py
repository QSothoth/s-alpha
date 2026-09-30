"""Offline OpenD-shaped checks for the daily list; synthetic prices are fixtures only."""
from datetime import date, datetime, timedelta
from types import SimpleNamespace
import unittest

from studies.us_0dte_picks import daily_list, p3

T, T1 = '2026-09-28', '2026-09-25'  # Monday, previous Friday
FT = SimpleNamespace(RET_OK=0, SubType=SimpleNamespace(K_DAY='K_DAY', K_5M='K_5M', K_30M='K_30M'), AuType=SimpleNamespace(QFQ='QFQ'),
                     Market=SimpleNamespace(US='US'), SecurityType=SimpleNamespace(ETF='ETF'),
                     OptionMarket=SimpleNamespace(US_SECURITY='US_SECURITY'),
                     UnderlyingRankSortType=SimpleNamespace(VOLUME='VOLUME'), Session=SimpleNamespace(RTH='RTH'))


def weekdays(end, n):
    day, out = date.fromisoformat(end), []
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day -= timedelta(days=1)
    return sorted(out)


def daily_rows(thrust):
    rows = []
    for day in weekdays(T1, 40):
        for i, clock in enumerate(daily_list.GRID30):
            row = dict(time_key=day + ' ' + clock, open=100, high=101, low=99, close=100, volume=1e6 / 13)
            if thrust and day == T1:
                row.update(high=106, low=99.5, close=105.8, volume=3e6 / 13)
            rows.append(row)
    return rows


def minute_rows(today_volume=2000.0, drift=.1):
    return [dict(time_key=T + ' 10:00:00', open=106, high=107, low=105,
                 close=106 + 6 * drift, volume=6 * today_volume),
            dict(time_key=T + ' 10:30:00', open=1, high=999, low=1, close=999, volume=9e9)]


class Context:
    def __init__(self, thrust=True):
        self.thrust, self.unsubscribed, self.subscriptions = thrust, [], []

    def request_trading_days(self, **kwargs):
        return 0, [{'time': d} for d in weekdays(T, 30)]

    def get_stock_basicinfo(self, market, kind):
        return 0, [{'code': 'US.ETF1'}]

    def get_option_underlying_rank(self, *args, **kwargs):
        rows = [{'code': c, 'price': 50} for c in ('US.ETF1', 'US.AAA', 'US.BBB')] + [{'code': 'US.CHEAP', 'price': 2}]
        return 0, rows, None, 4

    def subscribe(self, codes, subtypes, **kwargs):
        self.subscriptions.append((subtypes, kwargs))
        return 0, None

    def unsubscribe(self, codes, subtypes):
        self.unsubscribed.append(tuple(codes))
        return 0, None

    def get_cur_kline(self, code, num, ktype, autype):
        assert ktype == 'K_30M'
        if num == 1000:
            return 0, daily_rows(self.thrust and code == 'US.AAA') + minute_rows()
        base = (13 * 1e6 / 13 + 3e6 / 13) / 14
        return 0, minute_rows(today_volume=base * 2 / 6)

    def get_option_expiration_date(self, code):
        return 0, [{'strike_time': T}, {'strike_time': '2026-09-30'}]

    def get_option_underlying_his_statistic(self, code, **kwargs):
        return 0, [{'time': T1, 'option_volume': 5000}], None

    def get_option_underlying_his_volatility(self, code, **kwargs):
        return 0, [{'time': T1, 'iv': 40.0}, {'time': '2026-09-24', 'iv': 39.0}], None

    def get_option_chain(self, code, **kwargs):
        return 0, [dict(code='US.AAA260928C%06d' % (k * 1000), strike_time=T, option_type=right, strike_price=k,
                        option_standard_type='STANDARD') for k in (105, 106, 107) for right in ('CALL', 'PUT')]

    def get_market_snapshot(self, codes):
        return 0, [{'code': codes[0], 'bid_price': 1.0, 'ask_price': 1.06, 'volume': 800}]


def client(context):
    return daily_list.Client(context, FT, pause=lambda s: None, clock=lambda: 0.0)


class DailyListTests(unittest.TestCase):
    def test_premarket_finds_thrust_names_with_expiry_and_liquidity(self):
        context = Context()
        result = daily_list.premarket(client(context), date.fromisoformat(T))
        self.assertEqual([row['code'] for row in result['watchlist']], ['US.AAA'])
        row = result['watchlist'][0]
        self.assertEqual((row['side'], row['close_t1'], row['iv_t1']), (1, 105.8, 40.0))  # today's partial bar ignored
        self.assertEqual(result['universe'], 2)  # ETF and sub-$3 names excluded
        self.assertTrue(context.unsubscribed)
        self.assertEqual(row['rvol30_days'], weekdays(T1, 14))
        self.assertAlmostEqual(row['rvol30_base'], sum(row['opening_volumes']) / 14)
        self.assertEqual(context.subscriptions, [(['K_30M'], {'subscribe_push': False, 'session': 'RTH'})])

    def test_complete_days_and_market_day_recency_match_p3(self):
        rows = daily_rows(True)
        days = weekdays(T1, 40)
        # Missing last bar, a half day, and duplicate bar must each exclude the full session.
        bad = set(days[-4:-1])
        rows = [r for r in rows if not (r['time_key'] == days[-4] + ' 16:00:00'
                or r['time_key'][:10] == days[-3] and r['time_key'][11:] > '13:00:00')]
        rows.append(next(r.copy() for r in rows if r['time_key'][:10] == days[-2]))
        sessions = daily_list.complete_sessions(rows + minute_rows(), T)
        self.assertTrue(bad.isdisjoint(sessions))
        self.assertNotIn(T, sessions)
        calendar = weekdays(T, 60)
        record = daily_list.premarket_record(rows, T, calendar)
        self.assertEqual(record['rvol30_days'], [d for d in days if d not in bad][-14:])
        sparse = [r for r in daily_rows(True) if r['time_key'][:10] not in set(days[-9:-2])]
        with self.assertRaisesRegex(ValueError, '20 market days'):
            daily_list.premarket_record(sparse, T, calendar)
        with self.assertRaisesRegex(ValueError, 'T-1'):
            daily_list.premarket_record([r for r in rows if r['time_key'][:10] != T1], T, calendar)

    def test_premarket_matches_p3_on_equivalent_complete_bars(self):
        rows = daily_rows(True)
        sessions = daily_list.complete_sessions(rows, T)
        today = [(clock, 106, 108, 105, 106.6, 100000) for clock in p3.GRID]
        # Split each synthetic 30m bar into six equal-volume 5m bars for a reference.
        fine = {d: [(p3.GRID[i * 6 + j], *bar[1:5], bar[5] / 6)
                    for i, bar in enumerate(bars) for j in range(6)] for d, bars in sessions.items()}
        fine[T] = today
        calendar = weekdays(T, 60)
        candidate = daily_list.premarket_record(rows, T, calendar)
        candidate['iv_t1'] = 40
        opening = [dict(time_key=T + ' 10:00:00', open=106, high=108, low=105, close=106.6, volume=600000)]
        live = daily_list.opening_record(opening, T, candidate)
        reference = p3.features('AAA', fine, calendar,
            ({T1: 105.8}, {T1: 5000}, {'iv_days': [T1], 'iv': [40]}), True, True, set(), None, (T, T))[0]
        for key in ('thrust', 'rvol30', 'drive_z', 'above_c1', 'p10', 'sigma_rem'):
            self.assertAlmostEqual(live[key], reference[key], msg=key)

    def test_premarket_refuses_tuesday(self):
        with self.assertRaises(ValueError):
            daily_list.premarket(client(Context()), date(2026, 9, 29))
        context = Context()
        context.request_trading_days = lambda **kw: (0, [{'time': T1, 'trade_date_type': 'WHOLE'},
                                                         {'time': T, 'trade_date_type': 'MORNING'}])
        with self.assertRaisesRegex(ValueError, 'half-day'):
            daily_list.premarket(client(context), date.fromisoformat(T))

    def test_confirm_applies_p3_a4_rule_and_quotes_the_atm_call(self):
        context = Context()
        watch = daily_list.premarket(client(context), date.fromisoformat(T))
        now = datetime(2026, 9, 28, 10, 1, tzinfo=daily_list.ET)
        result = daily_list.confirm(client(context), watch, now)
        self.assertEqual(len(result['list']), 1)
        pick = result['list'][0]
        self.assertEqual((pick['code'], pick['side']), ('US.AAA', 1))
        self.assertAlmostEqual(pick['rvol30'], 2.0)
        self.assertGreater(pick['target'], pick['p10'])
        self.assertLess(pick['stop'], pick['p10'])
        self.assertEqual(pick['option']['contract'], 'US.AAA260928C107000')  # nearest strike to 106.6
        self.assertEqual(pick['option']['status'], 'OK')
        self.assertEqual(p3.signal(pick, 'A4_THRUST_FOLLOW'), (1, pick['rvol30']))
        self.assertIn('做多', daily_list.render(result))
        self.assertEqual(result['research_status'], 'P5_FAILED')
        self.assertIn('P5 未通过', daily_list.render(result))

    def test_confirm_rejects_before_ten_and_weak_openings(self):
        context = Context()
        watch = daily_list.premarket(client(context), date.fromisoformat(T))
        with self.assertRaises(ValueError):
            daily_list.confirm(client(context), watch, datetime(2026, 9, 28, 9, 55, tzinfo=daily_list.ET))
        candidate = watch['watchlist'][0]
        record = daily_list.opening_record(minute_rows(today_volume=candidate['rvol30_base'] * 1.2 / 6), T, candidate)
        self.assertIsNone(p3.signal(record, 'A4_THRUST_FOLLOW'))  # relative volume 1.2 < 1.5
        with self.assertRaises(ValueError):
            daily_list.confirm(client(context), watch, datetime(2026, 9, 28, 10, 26, tzinfo=daily_list.ET))
        with self.assertRaisesRegex(ValueError, 'rerun premarket'):
            daily_list.confirm(client(context), dict(watch, data_basis=None),
                               datetime(2026, 9, 28, 10, 1, tzinfo=daily_list.ET))
        with self.assertRaisesRegex(ValueError, 'baseline'):
            daily_list.opening_record(minute_rows(), T, dict(candidate, rvol30_days=[]))
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            daily_list.opening_record(minute_rows()[1:], T, candidate)
        for iv in (0, -1, float('nan')):
            broken = dict(watch, watchlist=[dict(candidate, iv_t1=iv)])
            result = daily_list.confirm(client(context), broken, datetime(2026, 9, 28, 10, 1, tzinfo=daily_list.ET))
            self.assertEqual(result['list'], [])
            self.assertIn('US.AAA', result['rejected'])

    def test_wide_spread_is_flagged(self):
        context = Context()
        context.get_market_snapshot = lambda codes: (0, [{'code': codes[0], 'bid_price': 1.0, 'ask_price': 1.5, 'volume': 50}])
        quote = daily_list.atm_quote(client(context), 'US.AAA', T, 106.6, 1)
        self.assertEqual(quote['status'], 'CAUTION')
        self.assertEqual(quote['flags'], ['价差过大', '成交过少'])


class ReviewTests(unittest.TestCase):
    def test_review_scores_first_touch_and_hold_to_close(self):
        context = Context()
        watch = daily_list.premarket(client(context), date.fromisoformat(T))
        listed = daily_list.confirm(client(context), watch, datetime(2026, 9, 28, 10, 1, tzinfo=daily_list.ET))
        pick = listed['list'][0]
        full = [dict(time_key='%s %s' % (T, clock), open=pick['p10'], high=pick['p10'] * (1.05 if i == 10 else 1.0001),
                     low=pick['p10'] * .9999, close=pick['p10'] * (1.03 if i >= 10 else 1.0), volume=1000.0)
                for i, clock in enumerate(p3.GRID)]
        context.get_cur_kline = lambda code, num, ktype, autype: (0, full)
        result = daily_list.review(client(context), listed, datetime(2026, 9, 28, 16, 10, tzinfo=daily_list.ET))
        row = result['rows'][0]
        self.assertEqual(row['status'], 'OK')
        self.assertTrue(row['target_first'])
        self.assertEqual(row['exit_time'], p3.GRID[10])
        expected = max(0.0, pick['p10'] * 1.03 - pick['option']['strike']) / pick['option']['ask'] - 1
        self.assertAlmostEqual(row['option']['hold_to_close_return'], expected)
        with self.assertRaises(ValueError):
            daily_list.review(client(context), listed, datetime(2026, 9, 28, 15, 59, tzinfo=daily_list.ET))


if __name__ == '__main__':
    unittest.main()
