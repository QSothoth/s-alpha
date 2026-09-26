"""Offline current-bar capture checks: no historical requests or shared cleanup."""
import contextlib
import io
import json
from datetime import datetime, timedelta
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from custody.dataset import Dataset
from custody.models import ET
from custody.opend import OpenDMarket
from studies.us_opening_range import capture as module


DAY = '2026-09-25'
OPEN = datetime(2026, 9, 25, 9, 30, tzinfo=ET)


def minute_rows(code, count=390):
    price = 100 if code == 'US.SPY' else 2
    return [{'code': code, 'time_key': (OPEN + timedelta(minutes=minute)).isoformat(),
             'open': price, 'high': price + 1, 'low': price - 1, 'close': price, 'volume': 10}
            for minute in range(1, count + 1)]


class Context:
    def __init__(self, minutes=390):
        self.minutes = minutes
        self.closed = False
        self.calls = []
        self.own_used = 0
        self.contract_size = 100
        self.missing = None
        self.chain = [dict(code='US.SPY260925%s100000' % right[0], stock_owner='US.SPY',
                           strike_time=DAY, strike_price=100, option_type=right,
                           option_standard_type='STANDARD', option_settlement_mode='PM',
                           suspension=False) for right in ('CALL', 'PUT')]

    def request_trading_days(self, **kwargs):
        return 0, [{'time': DAY, 'trade_date_type': 'WHOLE' if self.minutes == 390 else 'MORNING'}]

    def query_subscription(self, is_all_conn):
        self.calls.append(('quota', is_all_conn))
        return 0, {'total_used': 10, 'remain': 290, 'own_used': self.own_used,
                   'option_used_quota': 2, 'option_remain_quota': 58, 'own_option_used_quota': 0}

    def subscribe(self, codes, subtypes, **kwargs):
        self.calls.append(('subscribe', tuple(codes), tuple(subtypes), kwargs))
        return 0, None

    def unsubscribe(self, codes, subtypes):
        self.calls.append(('unsubscribe', tuple(codes), tuple(subtypes)))
        return 0, None

    def get_cur_kline(self, code, count, ktype, autype):
        self.calls.append(('current', code, count, ktype, autype))
        if code == self.missing:
            return 0, []
        if ktype == 'K_DAY':
            return 0, [dict(code=code, time_key='2026-09-24 00:00:00', open=99, high=101,
                            low=98, close=100), dict(code=code, time_key=DAY+' 00:00:00',
                                                    open=100, high=105, low=95, close=102)]
        return 0, minute_rows(code, self.minutes)

    def get_option_chain(self, code, **kwargs):
        self.calls.append(('chain', code, kwargs))
        return 0, self.chain

    def get_market_snapshot(self, codes):
        return 0, [dict(code=code, option_contract_size=self.contract_size,
                        option_contract_multiplier='N/A') for code in codes]

    def request_history_kline(self, *args, **kwargs):
        raise AssertionError('capture must never request historical candlesticks')

    def unsubscribe_all(self):
        raise AssertionError('capture must never cancel other services subscriptions')

    def close(self):
        self.closed = True


def sdk(context):
    return SimpleNamespace(OpenQuoteContext=lambda **kwargs: context,
                           SubType=SimpleNamespace(K_1M='K_1M', K_DAY='K_DAY'),
                           KLType=SimpleNamespace(K_1M='K_1M', K_DAY='K_DAY'),
                           AuType=SimpleNamespace(NONE='NONE'), Session=SimpleNamespace(RTH='RTH'),
                           OptionType=SimpleNamespace(ALL='ALL'), OptionCondType=SimpleNamespace(ALL='ALL'))


class CaptureTests(unittest.TestCase):
    def run_capture(self, context, out, **kwargs):
        pause = Mock()
        with patch.dict(sys.modules, {'futu': sdk(context)}):
            result = module.capture(['US.SPY'], out, OpenDMarket(quote_context=context),
                                    now_fn=lambda: OPEN + timedelta(minutes=411),
                                    pause=pause, clock=lambda: 0, **kwargs)
        self.assertTrue(all(call.args[0] <= 30 for call in pause.call_args_list))
        return result

    def test_complete_pair_real_metadata_previous_close_and_scoped_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            out, context = Path(temp) / 'fresh', Context()
            result = self.run_capture(context, out)
            self.assertTrue(result['ok'], result)
            data = Dataset(out)
            self.assertEqual(len(data.cases), 2)
            saved_cases = json.loads((out/'cases.json').read_text())['cases']
            self.assertEqual({case['right']: case['direction'] for case in saved_cases},
                             {'CALL': 'LONG', 'PUT': 'SHORT'})
            self.assertEqual({case.selection for case in data.cases}, {'both_sides_atm_at_open'})
            self.assertEqual({case.prev_close for case in data.cases}, {100})
            self.assertEqual(len(data.load(data.cases[0]).underlying), 390)
            self.assertEqual(data.manifest['role'], 'validation/custody')
            chain = json.loads((out/'chain'/'US.SPY.json').read_text())
            self.assertEqual(chain['chain'], context.chain)
            self.assertEqual(chain['opening_reference'], 100)
            self.assertEqual(result['history_requests'], 0)
            minute_calls = [call for call in context.calls if call[0] == 'current' and call[3] == 'K_1M']
            self.assertEqual(len(minute_calls), 3)
            self.assertTrue(all(call[2:] == (1000, 'K_1M', 'NONE') for call in minute_calls))
            unsub = [call for call in context.calls if call[0] == 'unsubscribe']
            self.assertEqual(len(unsub), 2)
            self.assertIn(('unsubscribe', ('US.SPY',), ('K_1M', 'K_DAY')), unsub)
            self.assertTrue(all('OTHER' not in str(call) for call in unsub))

    def test_missing_underlying_or_option_is_recorded_without_partial_cases(self):
        for missing in ('US.SPY', 'US.SPY260925P100000'):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as temp:
                context = Context()
                context.missing = missing
                out = Path(temp) / 'fresh'
                result = self.run_capture(context, out)
                self.assertFalse(result['ok'])
                self.assertEqual(json.loads((out/'cases.json').read_text())['cases'], [])
                self.assertFalse((out/'underlying').exists())
                self.assertTrue(result['errors'])
                self.assertTrue(any(call[0] == 'unsubscribe' for call in context.calls))

    def test_no_same_day_pair_and_nonstandard_size_are_not_fabricated(self):
        for kind in ('no_pair', 'wrong_expiry_metadata', 'small_contract'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                context = Context()
                if kind == 'no_pair':
                    context.chain = context.chain[:1]
                elif kind == 'wrong_expiry_metadata':
                    context.chain[0]['strike_time'] = '2026-09-28'
                else:
                    context.contract_size = 10
                result = self.run_capture(context, Path(temp)/'fresh')
                self.assertFalse(result['ok'])
                self.assertEqual(result['check']['cases'], 0)
                self.assertTrue(result['errors'] or result['skipped'])

    def test_early_close_requires_exact_210_minutes(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)/'fresh'
            result = self.run_capture(Context(minutes=210), out)
            self.assertTrue(result['ok'], result)
            data = Dataset(out)
            self.assertEqual(data.cases[0].session_close, DAY+'T13:00:00-04:00')
            self.assertEqual(len(data.load(data.cases[0]).underlying), 210)

    def test_wrong_date_existing_path_and_borrowed_subscriptions_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)/'fresh'
            with self.assertRaisesRegex(ValueError, 'current US/Eastern'):
                self.run_capture(Context(), out, day='2026-09-24')
            self.assertFalse(out.exists())
            context = Context()
            context.own_used = 1
            with self.assertRaisesRegex(ValueError, 'private connection'):
                self.run_capture(context, out)
            self.assertFalse(out.exists())
            out.mkdir()
            (out/'keep').write_text('unchanged')
            with self.assertRaises(FileExistsError):
                self.run_capture(Context(), out)
            self.assertEqual((out/'keep').read_text(), 'unchanged')

    def test_cli_closes_its_connection_after_capture_error(self):
        context = Context()
        def failure(symbols, out, market, day):
            market.context.query_subscription(is_all_conn=False)
            raise RuntimeError('test failure')
        with tempfile.TemporaryDirectory() as temp, patch.dict(sys.modules, {'futu': sdk(context)}), \
                patch.object(module, 'capture', side_effect=failure), \
                contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            module.main(['--symbols', 'SPY', '--out', str(Path(temp)/'fresh')])
        self.assertTrue(context.closed)

    def test_cli_accepts_26_or_30_symbols_and_rejects_31_without_dropping_any(self):
        symbols = ['A' + chr(65 + index // 26) + chr(65 + index % 26) for index in range(31)]
        with tempfile.TemporaryDirectory() as temp, patch.dict(sys.modules, {'futu': sdk(Context())}):
            for count in (26, 30):
                with self.subTest(count=count), patch.object(module, 'capture', return_value={'ok': True}) as call, \
                        contextlib.redirect_stdout(io.StringIO()):
                    code = module.main(['--symbols', ','.join(symbols[:count]), '--out', str(Path(temp)/'fresh')])
                    self.assertEqual(code, 0)
                    self.assertEqual(call.call_args.args[0], ['US.' + value for value in symbols[:count]])
            with patch.object(module, 'capture') as call, contextlib.redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit):
                module.main(['--symbols', ','.join(symbols), '--out', str(Path(temp)/'fresh')])
            call.assert_not_called()


if __name__ == '__main__':
    unittest.main()
