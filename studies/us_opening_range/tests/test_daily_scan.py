"""Offline SDK-shaped DS1 checks; synthetic prices are unit-test fixtures only."""
import contextlib
from datetime import date, datetime, timedelta
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from custody.models import ET
from custody.opend import OpenDMarket
from studies.us_opening_range import daily_scan as module


DAY = '2026-09-22'  # Tuesday: the chain, never a weekday whitelist, establishes expiry.
NOW = datetime(2026, 9, 22, 9, 45, 10, tzinfo=ET)
OPEN = NOW.replace(hour=9, minute=30, second=0)


def prior_days():
    day, days = date.fromisoformat(DAY), []
    while len(days) < 25:
        day -= timedelta(days=1)
        if day.weekday() < 5:
            days.append(day.isoformat())
    return list(reversed(days))


def raw_daily(code='US.SPY'):
    rows = [dict(code=code, time_key=day + ' 00:00:00', open=100, high=102, low=99,
                 close=100, volume=10) for day in prior_days()]
    rows[-20]['high'] = 106
    rows[-1].update(high=101, low=99.5)
    # The unfinished current candle must never enter the daily levels.
    return rows + [dict(code=code, time_key=DAY+' 00:00:00', open=100, high=999,
                        low=1, close=999, volume=999)]


def raw_minutes(code='US.SPY'):
    return [dict(code=code, time_key=(OPEN+timedelta(minutes=5*(i+1))).isoformat(),
                 open=o, high=h, low=l, close=c, volume=10)
            for i, (o, h, l, c) in enumerate(((100, 100.7, 99.9, 100.5),
                                              (100.5, 101.1, 100.4, 101),
                                              (101, 101.5, 100.9, 101.4),
                                              (101.4, 101.5, 99.8, 100),
                                              (100, 101, 99.5, 100),
                                              (100, 101, 99.5, 100)))]


def chain_row(right='CALL', code='US.SPY', day=DAY, **updates):
    row = dict(code=code+day.replace('-', '')[2:]+right[0]+'100000', stock_owner=code,
               strike_time=day, option_type=right, strike_price=100,
               option_standard_type='STANDARD', suspension=False, option_settlement_mode='PM')
    row.update(updates)
    return row


class Clock:
    def __init__(self):
        self.value, self.pauses = 0., []

    def __call__(self):
        return self.value

    def pause(self, seconds):
        self.pauses.append(seconds)
        self.value += seconds


class Context:
    def __init__(self, clock):
        self.clock, self.calls = clock, []
        self.closed, self.own_used, self.holiday, self.reject_all = False, 0, False, False
        self.daily, self.minutes = raw_daily(), raw_minutes()
        self.expiries = [dict(strike_time=DAY)]
        self.chain = [chain_row(), chain_row('PUT')]
        self.snapshot = {'code': 'US.SPY', 'sec_status': 'NORMAL', 'suspension': False}
        self.fail_expiry = False

    def note(self, name, *args):
        self.calls.append((name, self.clock(), args))

    def request_trading_days(self, **kwargs):
        self.note('calendar', kwargs)
        rows = [dict(time=day, trade_date_type='WHOLE') for day in prior_days()]
        if not self.holiday:
            rows.append(dict(time=DAY, trade_date_type='WHOLE'))
        return 0, rows

    def query_subscription(self, is_all_conn):
        self.note('quota', is_all_conn)
        return 0, {'own_used': self.own_used, 'own_option_used_quota': 0,
                   'total_used': 7, 'remain': 293}

    def subscribe(self, codes, subtypes, **kwargs):
        self.note('subscribe', codes, subtypes, kwargs)
        if self.reject_all and kwargs['session'] == 'ALL':
            return -1, 'extended session unavailable'
        return 0, None

    def unsubscribe(self, codes, subtypes):
        self.note('unsubscribe', codes, subtypes)
        return 0, None

    def get_cur_kline(self, code, count, ktype, autype):
        self.note('current', code, count, ktype, autype)
        rows = self.daily if ktype == 'K_DAY' else self.minutes
        return 0, [dict(row, code=code) for row in rows]

    def get_option_expiration_date(self, code):
        self.note('expiry', code)
        return (-1, 'no option permission') if self.fail_expiry else (0, self.expiries)

    def get_option_chain(self, **kwargs):
        self.note('chain', kwargs)
        return 0, self.chain

    def get_market_snapshot(self, codes):
        self.note('snapshot', codes)
        return 0, [self.snapshot]

    def request_history_kline(self, *args, **kwargs):
        raise AssertionError('DS1 current scan may not request history')

    def unsubscribe_all(self):
        raise AssertionError('DS1 may not unsubscribe other services')

    def close(self):
        self.closed = True


def sdk(context):
    return SimpleNamespace(OpenQuoteContext=lambda **kwargs: context,
        SubType=SimpleNamespace(K_DAY='K_DAY', K_5M='K_5M'),
        KLType=SimpleNamespace(K_DAY='K_DAY', K_5M='K_5M'), AuType=SimpleNamespace(QFQ='QFQ'),
        Session=SimpleNamespace(ALL='ALL', RTH='RTH'), OptionType=SimpleNamespace(ALL='ALL'),
        OptionCondType=SimpleNamespace(ALL='ALL'))


class DailyScanTests(unittest.TestCase):
    def run_scan(self, out, context=None, now=NOW, symbols=None):
        clock = context.clock if context else Clock()
        context = context or Context(clock)
        with patch.dict(sys.modules, {'futu': sdk(context)}):
            result = module.scan(symbols or ['US.SPY'], out, OpenDMarket(quote_context=context),
                                 now_fn=lambda: now, pause=clock.pause, clock=clock)
        return result, context

    def test_capture_uses_real_chain_qfq_and_preserves_raw_and_checksums(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)/'capture'
            result, context = self.run_scan(out)
            self.assertTrue(result['ok'], result)
            self.assertEqual(result['source_equivalence'], 'unverified')
            row = result['rows'][0]
            self.assertEqual(row['setup']['yesterday_high'], 101)
            self.assertTrue(row['setup']['nr7'])
            self.assertTrue(row['setup']['inside'])
            self.assertEqual(row['signals']['PD_BREAK']['time'], DAY+'T09:45:00-04:00')
            self.assertEqual(result['signal_overlap_count'], 1)
            self.assertTrue(row['option_eligibility']['eligible'])
            self.assertEqual(row['option_eligibility']['available_rights'], ['CALL', 'PUT'])
            self.assertIsNone(row['option_activity']['option_volume'])
            self.assertFalse(row['option_activity']['available'])
            self.assertEqual(row['option_activity']['scope'], 'underlying_all_expiries_not_0dte')
            self.assertEqual(result['history_requests'], 0)
            current = [call[2] for call in context.calls if call[0] == 'current']
            self.assertEqual(current, [('US.SPY', 40, 'K_DAY', 'QFQ'), ('US.SPY', 1000, 'K_5M', 'QFQ')])
            request_paths = {r['path'] for r in result['requests']}
            self.assertEqual(request_paths, {p.relative_to(out).as_posix() for p in (out/'raw').iterdir()})
            for line in (out/'CHECKSUMS.sha256').read_text().splitlines():
                digest, name = line.split('  ', 1)
                self.assertEqual(hashlib.sha256((out/name).read_bytes()).hexdigest(), digest)
            records = [json.loads((out/p).read_text()) for p in request_paths]
            daily = next(r for r in records if r['endpoint'] == 'get_cur_kline' and r['kwargs']['ktype'] == 'K_DAY')
            self.assertEqual(daily['data'][-1]['high'], 999)
            self.assertIn('requested_at', daily)
            self.assertIn('received_at', daily)

    def test_premarket_is_setup_and_facts_only_no_invented_confirmation(self):
        for hour, minute in ((9, 0), (9, 15)):
            with self.subTest(minute=minute), tempfile.TemporaryDirectory() as temp:
                context = Context(Clock())
                context.minutes.insert(0, dict(code='US.SPY', time_key=DAY+' 08:55:00',
                                              open=101, high=102, low=100, close=101.5, volume=4))
                result, _ = self.run_scan(Path(temp)/'out', context, NOW.replace(hour=hour, minute=minute))
                row = result['rows'][0]
                self.assertEqual(row['observation_status'], 'SETUP_ONLY')
                self.assertTrue(row['trigger_band']['LONG'])
                self.assertFalse(any(row['signals'].values()))
                self.assertEqual(row['premarket']['last'], 101.5)
                self.assertIsNone(row['premarket']['volume_ratio'])
                self.assertEqual(row['premarket']['as_of'], DAY+'T08:55:00-04:00')

    def test_no_premarket_or_extended_permission_is_explicit_and_not_a_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            context = Context(Clock())
            context.reject_all = True
            result, _ = self.run_scan(Path(temp)/'out', context)
            self.assertEqual(result['subscription_session'], 'RTH')
            self.assertTrue(result['extended_hours_unavailable'])
            row = result['rows'][0]
            self.assertFalse(row['premarket']['available'])
            self.assertIsNone(row['premarket']['high'])
            self.assertIsNotNone(row['signals']['PD_BREAK'])

    def test_option_ineligible_or_unavailable_does_not_delete_signals(self):
        for kind in ('no_today', 'nonstandard', 'wrong_expiry', 'wrong_owner', 'suspended', 'unavailable'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                context = Context(Clock())
                if kind == 'no_today':
                    context.expiries = [dict(strike_time='2026-09-25')]
                elif kind == 'unavailable':
                    context.fail_expiry = True
                else:
                    field, value = {'nonstandard': ('option_standard_type', 'NONSTANDARD'),
                                    'wrong_expiry': ('strike_time', '2026-09-25'),
                                    'wrong_owner': ('stock_owner', 'US.QQQ'),
                                    'suspended': ('suspension', True)}[kind]
                    context.chain = [dict(r, **{field: value}) for r in context.chain]
                result, _ = self.run_scan(Path(temp)/'out', context)
                row = result['rows'][0]
                self.assertIsNotNone(row['signals']['PD_BREAK'])
                self.assertFalse(row['option_eligibility']['eligible'])
                if kind == 'no_today':
                    self.assertNotIn('chain', [r[0] for r in context.calls])

    def test_future_bars_are_not_seen_and_later_corruption_preserves_first_signal(self):
        with tempfile.TemporaryDirectory() as temp:
            before, _ = self.run_scan(Path(temp)/'before', now=NOW.replace(minute=44))
            self.assertFalse(any(before['rows'][0]['signals'].values()))
            context = Context(Clock())
            context.minutes[3]['close'] = 999  # malformed 09:50 cannot erase 09:45
            after, _ = self.run_scan(Path(temp)/'after', context, NOW.replace(minute=51))
            row = after['rows'][0]
            self.assertIsNotNone(row['signals']['PD_BREAK'])
            self.assertIn('5m_prefix', row['errors'])
            self.assertEqual(row['observation_status'], 'STALE')

    def test_gaps_and_duplicates_are_not_silently_repaired(self):
        for kind in ('daily_gap', 'daily_duplicate', 'minute_gap', 'minute_duplicate'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                context = Context(Clock())
                if kind == 'daily_gap':
                    del context.daily[-2]
                elif kind == 'daily_duplicate':
                    context.daily.insert(-2, dict(context.daily[-3]))
                elif kind == 'minute_gap':
                    del context.minutes[1]
                else:
                    context.minutes.insert(1, dict(context.minutes[0]))
                result, _ = self.run_scan(Path(temp)/'out', context)
                self.assertFalse(any(result['rows'][0]['signals'].values()))
                self.assertTrue(result['rows'][0]['option_eligibility']['eligible'])
                self.assertTrue(result['rows'][0]['errors'] or result['rows'][0]['filter_counts'])

    def test_freshness_uses_completed_five_minute_grid_not_bar_age(self):
        for minute, count, status in ((49, 3, 'SIGNAL_RECORDED'), (50, 3, 'STALE'),
                                      (50, 4, 'SIGNAL_RECORDED')):
            with self.subTest(minute=minute, count=count), tempfile.TemporaryDirectory() as temp:
                context = Context(Clock())
                context.minutes = context.minutes[:count]
                result, _ = self.run_scan(Path(temp)/'out', context, NOW.replace(minute=minute))
                row = result['rows'][0]
                self.assertEqual(row['observation_status'], status)
                self.assertIsNotNone(row['signals']['PD_BREAK'])
                self.assertEqual(row['expected_completed_bar_at'],
                                 DAY + ('T09:45:00-04:00' if minute == 49 else 'T09:50:00-04:00'))

    def test_missing_internal_bar_is_visible_even_with_fresh_latest_bar(self):
        with tempfile.TemporaryDirectory() as temp:
            context = Context(Clock())
            del context.minutes[1]  # 09:40 is missing, but 09:45 is fresh.
            result, _ = self.run_scan(Path(temp) / 'out', context)
            row = result['rows'][0]
            self.assertEqual(row['last_completed_bar_at'], DAY + 'T09:45:00-04:00')
            self.assertEqual(row['observation_status'], 'MISSING_DATA')
            self.assertIn('09:40', row['errors']['5m_grid'])
            self.assertFalse(result['ok'])
            self.assertFalse(any(row['signals'].values()))
            self.assertIn('已完成5m序列缺根：09:40', module.format_observation(result))

    def test_later_internal_gap_keeps_earlier_signal_and_discloses_incomplete_data(self):
        with tempfile.TemporaryDirectory() as temp:
            context = Context(Clock())
            del context.minutes[3]  # An existing 09:45 signal survives missing 09:50.
            result, _ = self.run_scan(Path(temp) / 'out', context, NOW.replace(minute=55))
            row = result['rows'][0]
            self.assertEqual(row['observation_status'], 'MISSING_DATA')
            self.assertIn('09:50', row['errors']['5m_grid'])
            self.assertEqual(row['signals']['PD_BREAK']['time'], DAY + 'T09:45:00-04:00')
            self.assertFalse(result['ok'])
            self.assertIn('PD\\_BREAK', module.format_observation(result))

    def test_calendar_holiday_and_occupied_connection_are_rejected_before_subscription(self):
        for kind in ('holiday', 'occupied'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                context = Context(Clock())
                if kind == 'holiday':
                    context.holiday = True
                else:
                    context.own_used = 1
                result, _ = self.run_scan(Path(temp)/'out', context)
                self.assertFalse(result['ok'])
                self.assertNotIn('subscribe', [c[0] for c in context.calls])
                self.assertNotIn('unsubscribe', [c[0] for c in context.calls])
                self.assertTrue((Path(temp)/'out'/'CHECKSUMS.sha256').exists())

    def test_limits_scoped_cleanup_and_one_minute_hold(self):
        with tempfile.TemporaryDirectory() as temp:
            result, context = self.run_scan(Path(temp)/'out', symbols=['SPY', 'QQQ'])
            calls = context.calls
            self.assertTrue(all(b[1]-a[1] >= 3.1-1e-9 for a, b in zip(calls, calls[1:])))
            sub = next(c for c in calls if c[0] == 'subscribe')
            unsub = next(c for c in calls if c[0] == 'unsubscribe')
            self.assertGreaterEqual(unsub[1]-sub[1], 61)
            self.assertEqual(sub[2][:2], (['US.SPY', 'US.QQQ'], ['K_DAY', 'K_5M']))
            self.assertEqual(unsub[2], (['US.SPY', 'US.QQQ'], ['K_DAY', 'K_5M']))
            self.assertTrue(all(seconds <= 30 for seconds in context.clock.pauses))
            self.assertEqual(len(result['rows']), 2)

    def test_refuses_overwrite_and_invalid_time_without_any_api_call(self):
        with tempfile.TemporaryDirectory() as temp:
            context = Context(Clock())
            for now in (NOW.replace(hour=8), NOW.replace(hour=10, minute=6), NOW.replace(hour=23)):
                with self.assertRaises(ValueError):
                    self.run_scan(Path(temp)/'future', context, now)
            with self.assertRaises(FileExistsError):
                self.run_scan(Path(temp), context)
            with self.assertRaises(ValueError):
                self.run_scan(Path(temp)/'many', context, symbols=['S'+str(i) for i in range(11)])
            self.assertEqual(context.calls, [])

    def test_main_owns_and_closes_connection(self):
        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return NOW
        with tempfile.TemporaryDirectory() as temp:
            context = Context(Clock())
            original = module.scan
            def invoke(symbols, out, market):
                return original(symbols, out, market, now_fn=lambda: NOW,
                                pause=context.clock.pause, clock=context.clock)
            with patch.dict(sys.modules, {'futu': sdk(context)}), patch.object(module, 'datetime', FixedDateTime), \
                    patch.object(module, 'scan', side_effect=invoke), contextlib.redirect_stdout(io.StringIO()):
                code = module.main(['--symbols', 'SPY', '--out', str(Path(temp)/'out')])
            self.assertEqual(code, 0)
            self.assertTrue(context.closed)


class ObservationFormatTests(unittest.TestCase):
    def result(self):
        return {'trade_date': DAY, 'created_at': NOW.isoformat(), 'completed_at': NOW.isoformat(),
                'source_equivalence': 'unverified', 'ok': True, 'errors': [], 'rows': [{
                'symbol': 'US.SPY', 'status': 'UNVALIDATED', 'observation_status': 'SETUP_ONLY',
                'setup': {'yesterday_high': 101, 'yesterday_low': 99, 'range_high20': 106,
                          'range_low20': 98, 'nr7': True, 'inside': False},
                'signals': {name: None for name in module.CANDIDATES},
                'option_eligibility': {'status': 'UNKNOWN', 'eligible': None}, 'errors': {}}]}

    def test_premarket_levels_background_and_unknown_options_without_prediction(self):
        result = self.result()
        original = json.dumps(result, sort_keys=True)
        output = module.format_observation(result)
        self.assertIn('仅形态／价位观察，未确认方向', output)
        self.assertIn('无已记录确认；盘前仅观察形态和价位，不预测方向', output)
        self.assertIn('| 昨高／昨低 | 101／99 |', output)
        self.assertIn('| 20日高／低 | 106／98 |', output)
        self.assertIn('NR7：是；内包：否', output)
        self.assertIn('UNKNOWN；合格：未知', output)
        self.assertIn('可用rights／标准合约数 | 未知／未知', output)
        self.assertNotIn('LONG', output)
        self.assertNotIn('SHORT', output)
        self.assertEqual(json.dumps(result, sort_keys=True), original)

    def test_missing_data_is_unknown_not_zero_and_empty_capture_is_explicit(self):
        result = self.result()
        row = result['rows'][0]
        row.update(setup=None, observation_status='MISSING_DATA', observed_at=None)
        output = module.format_observation(result)
        self.assertIn('数据缺失', output)
        self.assertIn('昨高／昨低 | 未知／未知', output)
        self.assertIn('NR7：未知；内包：未知', output)
        self.assertIn('观察时间 | 未知', output)
        row['option_eligibility'] = {'status': 'NO_STANDARD_0DTE', 'eligible': False,
                                     'standard_contract_count': 0, 'available_rights': []}
        output = module.format_observation(result)
        self.assertIn('合格：否', output)
        self.assertIn('可用rights／标准合约数 | 无／0', output)
        result['rows'] = []
        self.assertIn('暂无标的记录；不能据此推断没有信号或没有0DTE', module.format_observation(result))

    def test_stale_keeps_every_recorded_candidate_and_does_not_approve_liquidity(self):
        result = self.result()
        row = result['rows'][0]
        row.update(observation_status='STALE', last_completed_bar_at=NOW.isoformat(),
                   expected_completed_bar_at=NOW.replace(minute=50).isoformat())
        row['signals'] = {name: {'direction': 'LONG', 'time': NOW.isoformat(), 'reference': 101.4,
                                 'invalidation': 100.7, 'target': 102.8} for name in module.CANDIDATES}
        row['option_eligibility'] = {'status': 'LISTED_STANDARD_0DTE', 'eligible': True,
                                     'available_rights': ['CALL', 'PUT'], 'standard_contract_count': 6}
        output = module.format_observation(result)
        self.assertIn('STALE；行情过时；保留的提示仅作历史观察', output)
        for name in module.CANDIDATES:
            self.assertIn('| ' + name.replace('_', '\\_') + ' | LONG | ' + NOW.isoformat()
                          + ' | 101.4 | 100.7 | 102.8 | 未知 | UNVALIDATED |', output)
        self.assertIn('测量线不是自动退出规则', output)
        self.assertIn('CALL／PUT／6', output)
        self.assertIn('有当日合约链不代表0DTE成交量或流动性通过', output)
        self.assertNotIn('胜率', output)
        self.assertNotIn('预期收益', output)

    def test_room_state_is_display_only_and_beyond_range_is_not_known_target_space(self):
        for state, wording in (('room_to_20d_boundary', '到已观测20日边界满足原空间门槛'),
                               ('beyond_observed_20d_range', '已越过20日范围，外侧空间未知'),
                               (None, '未知'), ('unexpected', '未知')):
            with self.subTest(state=state):
                result = self.result()
                signal = {'direction': 'LONG', 'time': NOW.isoformat(), 'reference': 101.4,
                          'invalidation': 100.7, 'target': 102.8}
                if state is not None:
                    signal['room_state'] = state
                result['rows'][0]['signals']['PD_BREAK'] = signal
                original = json.dumps(result, sort_keys=True)
                output = module.format_observation(result)
                self.assertIn('| 2R测量线 | 空间状态 | 状态 |', output)
                self.assertIn(' | 101.4 | 100.7 | 102.8 | ' + wording + ' | UNVALIDATED |', output)
                self.assertIn('2R测量线不代表期权盈亏比', output)
                self.assertEqual(json.dumps(result, sort_keys=True), original)

    def test_errors_and_external_fields_cannot_inject_markdown_or_html(self):
        result = self.result()
        result['errors'] = ['连接|错误\n# 假标题<script>']
        row = result['rows'][0]
        row['symbol'] = 'US.TEST|`x`\r\n![payload](https://example.invalid)'
        row['errors'] = {'daily|error': '缺数\n## 注入'}
        output = module.format_observation(result)
        self.assertIn('连接\\|错误 \\# 假标题&lt;script&gt;', output)
        self.assertIn('US.TEST\\|\\`x\\` !\\[payload\\]', output)
        self.assertIn('数据错误（daily\\|error）：缺数 \\#\\# 注入', output)
        self.assertNotIn('\n# 假标题', output)
        self.assertNotIn('<script>', output)

    def test_cli_json_default_and_markdown_are_stdout_only_and_keep_scan_arguments(self):
        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return NOW
        with tempfile.TemporaryDirectory() as temp:
            context = Context(Clock())
            actual_scan = module.scan
            def invoke(symbols, out, market):
                return actual_scan(symbols, out, market, now_fn=lambda: NOW,
                                   pause=context.clock.pause, clock=context.clock)
            outputs, manifests = [], []
            for name, args in (('default', []), ('json', ['--format', 'json']), ('markdown', ['--format', 'markdown'])):
                output = io.StringIO()
                with patch.dict(sys.modules, {'futu': sdk(context)}), patch.object(module, 'datetime', FixedDateTime), \
                        patch.object(module, 'scan', side_effect=invoke) as scan, contextlib.redirect_stdout(output):
                    status = module.main(['--symbols', 'SPY', '--out', str(Path(temp) / name), *args])
                self.assertEqual(status, 0)
                self.assertEqual(scan.call_args.args[:2], (['US.SPY'], Path(temp) / name))
                manifest = json.loads((Path(temp) / name / 'manifest.json').read_text())
                self.assertTrue((Path(temp) / name / 'CHECKSUMS.sha256').exists())
                self.assertNotIn('format', manifest)
                outputs.append(output.getvalue())
                manifests.append(manifest)
            self.assertEqual(json.loads(outputs[0]), manifests[0])
            self.assertEqual(json.loads(outputs[1]), manifests[1])
            self.assertEqual(outputs[2].rstrip(), module.format_observation(manifests[2]))
            self.assertTrue(outputs[2].startswith('# DS1 研究观察 · UNVALIDATED'))
            self.assertTrue(context.closed)


if __name__ == '__main__':
    unittest.main()
