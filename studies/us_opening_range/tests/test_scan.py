"""Offline SDK-shaped checks for the one-shot opening-range scanner."""
import contextlib
import io
import json
import sys
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from custody.models import ET
from custody.opend import OpenDMarket
from studies.us_opening_range import scan


DAY = '2026-09-22'  # Tuesday: actual expiry metadata, never a weekday whitelist.
OPEN = datetime.fromisoformat(DAY + 'T09:30:00').replace(tzinfo=ET)
NOW = OPEN + timedelta(minutes=20, seconds=10)


def raw_bars(count=20, bearish=False):
    rows = []
    for minute in range(1, count + 1):
        close = 100 if minute <= 15 else 101.2
        high, low = (101, 99) if minute <= 15 else (101.3, 100.8)
        if bearish:
            close, high, low = 200 - close, 200 - low, 200 - high
        rows.append({'code': 'US.SPY', 'time_key': (OPEN + timedelta(minutes=minute)).strftime('%Y-%m-%d %H:%M:%S'),
                     'open': close, 'high': high, 'low': low, 'close': close, 'volume': 10})
    return rows


def chain_row(right, strike=100, day=DAY, symbol='US.SPY', **extra):
    return {'code': symbol + day.replace('-', '')[2:] + right[0] + str(int(strike * 1000)),
            'stock_owner': symbol, 'strike_time': day, 'strike_price': strike, 'option_type': right,
            'option_standard_type': 'STANDARD', 'option_settlement_mode': 'PM',
            'lot_size': 100, 'suspension': False, **extra}


def pair(strike=100, **extra):
    return [chain_row(right, strike, **extra) for right in ('CALL', 'PUT')]


def snapshot(**extra):
    # SDK: contract_size applies to stock options; multiplier is index-specific.
    return {'bid_price': 1.00, 'ask_price': 1.05, 'bid_vol': 3, 'ask_vol': 2,
            'option_contract_size': 100, 'option_contract_multiplier': 'N/A',
            'option_valid': True, 'suspension': False, 'sec_status': 'NORMAL',
            'update_time': NOW.strftime('%Y-%m-%d %H:%M:%S'), **extra}


class QuoteContext:
    """Expose only the SDK methods used by the observation path."""

    def __init__(self, rows=None, expiries=None, chain=None, quote=None):
        self.rows = raw_bars() if rows is None else rows
        self.expiries = [DAY] if expiries is None else expiries
        self.chain = pair() if chain is None else chain
        self.quote = snapshot() if quote is None else quote
        self.calls = []
        self.closed = False

    def request_trading_days(self, *, market, start, end):
        self.calls.append(('calendar', market, start, end))
        return 0, [{'time': start, 'trade_date_type': 'WHOLE'}]

    def get_option_expiration_date(self, code, index_option_type='NORMAL'):
        self.calls.append(('expiry', code))
        return 0, [{'strike_time': day} for day in self.expiries]

    def subscribe(self, code_list, subtype_list, is_first_push=True, subscribe_push=True,
                  is_detailed_orderbook=False, extended_time=False, session='NONE'):
        self.calls.append(('subscribe', code_list, subtype_list, subscribe_push, session))
        return 0, None

    def get_cur_kline(self, code, num, ktype='K_DAY', autype='QFQ'):
        self.calls.append(('current', code, num, ktype, autype))
        return 0, self.rows

    def get_option_chain(self, code, index_option_type='NORMAL', start=None, end=None,
                         option_type='ALL', option_cond_type='ALL', data_filter=None):
        self.calls.append(('chain', code, start, end, option_type, option_cond_type))
        return 0, self.chain

    def get_market_snapshot(self, code_list):
        self.calls.append(('snapshot', code_list))
        return 0, [dict(self.quote, code=code) for code in code_list]

    def request_history_kline(self, *args, **kwargs):
        raise AssertionError('the one-shot scanner must not spend history quota')

    def close(self):
        self.closed = True
        self.calls.append(('close',))


def sdk(context):
    return SimpleNamespace(OpenQuoteContext=lambda **kwargs: context,
                           SubType=SimpleNamespace(K_1M='K_1M'),
                           KLType=SimpleNamespace(K_1M='K_1M'),
                           AuType=SimpleNamespace(NONE='NONE'),
                           Session=SimpleNamespace(RTH='RTH'),
                           OptionType=SimpleNamespace(ALL='ALL', CALL='CALL', PUT='PUT'),
                           OptionCondType=SimpleNamespace(ALL='ALL'))


class ScanTests(unittest.TestCase):
    def run_scan(self, context, now=NOW, times=None, candidate='OR15_breakout'):
        clock = Mock(side_effect=times) if times else lambda: now
        with patch.dict(sys.modules, {'futu': sdk(context)}):
            result = scan.scan(['US.SPY'], candidate, OpenDMarket(quote_context=context),
                               now_fn=clock, pause=Mock())
        return result['rows'][0]

    def test_actual_tuesday_expiry_and_sdk_current_bars_only(self):
        context = QuoteContext()
        row = self.run_scan(context)
        self.assertEqual(row['status'], 'OBSERVE')
        self.assertEqual(row['contract'], pair()[0]['code'])
        self.assertEqual(row['paired_contract'], pair()[1]['code'])
        self.assertIn(('subscribe', ['US.SPY'], ['K_1M'], False, 'RTH'), context.calls)
        self.assertIn(('current', 'US.SPY', 1000, 'K_1M', 'NONE'), context.calls)
        self.assertIn(('chain', 'US.SPY', DAY, DAY, 'ALL', 'ALL'), context.calls)

    def test_no_actual_expiry_skips_even_on_friday(self):
        context = QuoteContext(expiries=['2026-09-28'])
        row = self.run_scan(context, now=NOW.replace(day=25))
        self.assertEqual((row['status'], row['reason']), ('SKIP', 'no_0dte_today'))
        self.assertEqual([call[0] for call in context.calls], ['calendar', 'expiry'])

    def test_atm_uses_open_and_requires_both_standard_same_day_contracts(self):
        chain = (pair(101) + pair(99) + pair(100, day='2026-09-23')
                 + pair(100, symbol='US.QQQ') + pair(100, option_standard_type='NON_STANDARD'))
        chosen = scan.atm_pair(chain, 'US.SPY', DAY, 100)
        self.assertEqual(chosen, {r['option_type']: r['code'] for r in pair(99)})
        self.assertIsNone(scan.atm_pair([chain_row('CALL')], 'US.SPY', DAY, 100))
        self.assertIsNone(scan.atm_pair([], 'US.SPY', DAY, 100))
        context = QuoteContext(chain=pair(100) + pair(101), rows=raw_bars(bearish=True))
        row = self.run_scan(context)
        self.assertEqual(row['status'], 'OBSERVE')
        self.assertEqual(row['contract'], pair(100)[1]['code'])

    def test_nearest_strike_cannot_be_replaced_by_farther_usable_pair(self):
        bad_nearest = [[chain_row('CALL', 100)], pair(100, suspension=True),
                       pair(100, option_settlement_mode='AM'), pair(100)+[chain_row('CALL', 100)]]
        for nearest in bad_nearest:
            with self.subTest(nearest=nearest):
                self.assertIsNone(scan.atm_pair(pair(101) + nearest, 'US.SPY', DAY, 100))
        # The lower strike wins an equal-distance tie even if its pair is incomplete.
        self.assertIsNone(scan.atm_pair([chain_row('CALL', 99)]+pair(101), 'US.SPY', DAY, 100))

    def test_quote_stock_contract_size_and_fresh_narrow_sized_market(self):
        checked, reason = scan.quote_check(snapshot(), NOW)
        self.assertIsNone(reason)
        self.assertAlmostEqual(checked['spread_fraction'], .05 / 1.025)
        self.assertEqual(scan.quote_check(snapshot(bid_price=.95, ask_price=1.05), NOW)[1], None)
        self.assertEqual(scan.quote_check(snapshot(update_time=(NOW-timedelta(seconds=60)).isoformat(sep=' ')), NOW)[1], None)

    def test_bad_quotes_are_not_current_candidates(self):
        changes = [({'bid_vol': 0}, 'invalid_bid_ask'), ({'ask_vol': 0}, 'invalid_bid_ask'),
                   ({'bid_price': 0}, 'invalid_bid_ask'), ({'ask_price': .99}, 'invalid_bid_ask'),
                   ({'ask_price': 1.5}, 'wide_spread'), ({'bid_price': float('nan')}, 'missing_quote_fields'),
                   ({'update_time': 'not-a-time'}, 'stale_quote'),
                   ({'update_time': (NOW-timedelta(seconds=61)).strftime('%Y-%m-%d %H:%M:%S')}, 'stale_quote'),
                   ({'update_time': (NOW+timedelta(seconds=1)).strftime('%Y-%m-%d %H:%M:%S')}, 'stale_quote'),
                   ({'option_contract_size': 10}, 'invalid_contract'), ({'option_valid': False}, 'invalid_contract'),
                   ({'suspension': True}, 'invalid_contract'), ({'sec_status': 'DELISTED'}, 'invalid_contract')]
        for change, reason in changes:
            with self.subTest(change=change):
                row = self.run_scan(QuoteContext(quote=snapshot(**change)))
                self.assertEqual((row['status'], row['reason']), ('SKIP', reason))

    def test_no_signal_zero_volume_or_missing_pair_never_displays_observe(self):
        cases = [(QuoteContext(rows=[]), 'WAIT', 'no_completed_bars'),
                 (QuoteContext(rows=raw_bars(15)), 'WAIT', 'no_confirmation'),
                 (QuoteContext(rows=[dict(r, volume=0) for r in raw_bars()]), 'WAIT', 'no_confirmation'),
                 (QuoteContext(chain=[]), 'SKIP', 'no_standard_atm_pair')]
        for context, status, reason in cases:
            now = OPEN + timedelta(minutes=15, seconds=10) if len(context.rows) == 15 else NOW
            with self.subTest(reason=reason):
                row = self.run_scan(context, now=now)
                self.assertEqual((row['status'], row['reason']), (status, reason))
                self.assertFalse(any(call[0] == 'snapshot' for call in context.calls))

    def test_completed_prefix_excludes_current_and_future_minutes(self):
        full = raw_bars()
        early = self.run_scan(QuoteContext(rows=full), now=OPEN+timedelta(minutes=19, seconds=59))
        self.assertEqual((early['status'], early['reason']), ('WAIT', 'no_confirmation'))
        # Even a future crash cannot retract the signal at the observation time.
        future = dict(raw_bars(21)[-1], open=50, high=50, low=50, close=50)
        row = self.run_scan(QuoteContext(rows=full+[future]))
        self.assertEqual(row['status'], 'OBSERVE')
        self.assertEqual(row['signal']['time'], OPEN+timedelta(minutes=20))

    def test_corrupt_raw_completed_rows_are_rejected_not_silently_repaired(self):
        rows = raw_bars()
        invalid = [rows[:5]+rows[4:], [rows[1], rows[0]]+rows[2:], rows[:5]+rows[6:],
                   [dict(rows[0], code='US.QQQ')]+rows[1:],
                   [dict(rows[0], time_key='broken')]+rows[1:],
                   [dict(rows[0], volume=float('nan'))]+rows[1:]]
        for raw in invalid:
            with self.subTest(first=raw[0]):
                row = self.run_scan(QuoteContext(rows=raw))
                self.assertEqual(row['status'], 'ERROR')
                self.assertNotIn('contract', row)

    def test_old_exited_or_chased_signal_is_not_current(self):
        stopped = raw_bars(21)
        stopped[-1].update(open=100, high=100, low=100, close=100)
        chased = raw_bars(21)
        chased[-1].update(open=102, high=102, low=102, close=102)
        cases = [(raw_bars(), NOW+timedelta(minutes=3), 'SKIP', 'stale_underlying'),
                 (raw_bars(26), OPEN+timedelta(minutes=26, seconds=10), 'HISTORICAL', 'signal_older_than_5m'),
                 (stopped, OPEN+timedelta(minutes=21, seconds=10), 'HISTORICAL', 'exit_stop'),
                 (chased, OPEN+timedelta(minutes=21, seconds=10), 'SKIP', 'price_left_entry_zone')]
        for raw, now, status, reason in cases:
            with self.subTest(reason=reason):
                row = self.run_scan(QuoteContext(rows=raw), now=now)
                self.assertEqual((row['status'], row['reason']), (status, reason))

    def test_slow_snapshot_cannot_revive_a_stale_underlying(self):
        later = NOW + timedelta(minutes=3)
        context = QuoteContext(quote=snapshot(update_time=later.strftime('%Y-%m-%d %H:%M:%S')))
        row = self.run_scan(context, times=[NOW, NOW, later])
        self.assertEqual((row['status'], row['reason']), ('SKIP', 'stale_underlying'))

    def test_main_closes_owned_connection_on_success_and_error(self):
        for failed in (False, True):
            with self.subTest(failed=failed):
                context = QuoteContext()
                if failed:
                    context.get_cur_kline = Mock(return_value=(-1, 'no subscription permission'))
                output = io.StringIO()
                with patch.dict(sys.modules, {'futu': sdk(context)}), patch.object(scan, 'datetime') as clock:
                    clock.now.return_value = NOW
                    with contextlib.redirect_stdout(output):
                        result = scan.main(['--symbols', 'SPY,US.SPY', '--candidate', 'OR15_breakout'])
                self.assertEqual(result, 1 if failed else 0)
                self.assertTrue(context.closed)
                self.assertEqual(context.calls[-1], ('close',))
                self.assertEqual(len(json.loads(output.getvalue())['rows']), 1)


if __name__ == '__main__':
    unittest.main()
