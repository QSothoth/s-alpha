import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime, timedelta
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from studies.us_0dte_picks.fetch_sv1 import append_csv, fetch_pair, import_cases, main as fetch_main, option_code, strikes_to_try
from custody.models import ET
from studies.us_0dte_picks.sv1 import VALIDATION_DAYS, diff_bootstrap, first_symbols, gap_side, score, validate_scope


def data(symbol, day, direction='LONG', prev_close=100.0, first_open=101.0):
    case = SimpleNamespace(symbol=symbol, trade_date=day, direction=direction, prev_close=prev_close)
    return SimpleNamespace(case=case, underlying=[SimpleNamespace(open=first_open)])


def trade(minute=None, net_return=None):
    return {'entry': None if minute is None else {'fill_minute': minute}, 'net_return': net_return}


class Sv1Tests(unittest.TestCase):
    def test_quota_failure_does_not_try_another_strike(self):
        with patch('studies.us_0dte_picks.fetch_sv1._bars', return_value=([], '历史K线额度不足')) as history:
            _, legs, attempts = fetch_pair(None, SimpleNamespace(acquire=lambda: None), 'US.AAPL', '2026-09-23', 340)
            self.assertIsNone(legs)
            self.assertEqual(len(attempts), 1)
            history.assert_called_once()

    def test_quota_failure_defers_later_symbols_without_requesting_their_history(self):
        opens = datetime(2026, 9, 23, 9, 30, tzinfo=ET)
        bar = SimpleNamespace(close_time=opens + timedelta(minutes=1), open=100)
        calendar = SimpleNamespace(session=lambda _: SimpleNamespace(opens=opens, closes=bar.close_time))
        attempts = [{'code': 'TEST', 'bars': 0, 'error': '历史K线额度不足'}]
        with TemporaryDirectory() as folder, \
                patch('studies.us_0dte_picks.fetch_sv1.OpenDMarket') as factory, \
                patch('studies.us_0dte_picks.fetch_sv1.OpenDTradingCalendar', return_value=calendar), \
                patch('studies.us_0dte_picks.fetch_sv1.RateLimiter'), \
                patch('studies.us_0dte_picks.fetch_sv1.fetch_pair', return_value=(None, None, attempts)):
            market = factory.return_value.__enter__.return_value
            market.context.get_history_kl_quota.return_value = (0, (2, 298, [{'code': 'US.AAPL'}, {'code': 'US.AMD'}]))
            market.history_bars.return_value = [bar]
            market.request_kline.return_value = []
            with redirect_stdout(StringIO()):
                fetch_main(['--dataset', folder, '--dates', '2026-09-23', '--symbols', 'US.AAPL,US.AMD', '--max-chains', '2'])
            market.history_bars.assert_called_once_with('US.AAPL', 'K_1M', '2026-09-23', '2026-09-23')
            run = json.loads((Path(folder) / 'manifest.json').read_text())['runs'][-1]
            self.assertEqual(run['stop_reason'], 'option_history_quota_exhausted')
            self.assertEqual(run['deferred'], [{'symbol': 'US.AMD', 'trade_date': '2026-09-23'}])

    def test_importing_another_session_preserves_existing_underlying_rows(self):
        with TemporaryDirectory() as folder:
            source, target = Path(folder) / 'source', Path(folder) / 'target'
            for root in (source, target):
                (root / 'underlying').mkdir(parents=True)
                (root / 'option').mkdir()
            old = 'close_time,close\n2026-09-21T09:31:00-04:00,100\n'
            new = 'close_time,close\n2026-09-25T09:31:00-04:00,101\n'
            (target / 'underlying/US.AAPL.csv').write_text(old)
            (source / 'underlying/US.AAPL.csv').write_text(new)
            (source / 'option/TEST.csv').write_text('synthetic fixture\n')
            (source / 'cases.json').write_text(json.dumps({'cases': [
                {'symbol': 'US.AAPL', 'contract': 'TEST', 'trade_date': '2026-09-25'}]}))
            with patch('studies.us_0dte_picks.fetch_sv1.Dataset', return_value=SimpleNamespace(
                    root=source, name='test', fingerprint='test')):
                import_cases(source, target, {'US.AAPL'})
                import_cases(source, target, {'US.AAPL'})
            self.assertEqual((target / 'underlying/US.AAPL.csv').read_text(), old + new.split('\n', 1)[1])

    def test_import_rejects_incompatible_headers_without_changing_existing_tape(self):
        with TemporaryDirectory() as folder:
            source, target = Path(folder) / 'new.csv', Path(folder) / 'old.csv'
            source.write_text('other\n1\n')
            target.write_text('close\n100\n')
            with self.assertRaisesRegex(ValueError, 'incompatible CSV'):
                append_csv(source, target)
            self.assertEqual(target.read_text(), 'close\n100\n')

    def test_incomplete_validation_is_rejected_before_tapes_or_strategies_are_read(self):
        dataset = SimpleNamespace(manifest={'role': 'validation/custody'},
                                  cases=[data('US.AAPL', day).case for day in VALIDATION_DAYS[:-1]])
        with patch('studies.us_0dte_picks.sv1.Dataset', return_value=dataset), \
                patch('studies.us_0dte_picks.sv1.Registry') as registry, \
                patch('studies.us_0dte_picks.sv1.run_strategy') as replay:
            with self.assertRaisesRegex(ValueError, 'missing=.*2026-10-12'):
                score('unused')
            registry.assert_not_called()
            replay.assert_not_called()

    def test_scope_uses_actual_cases_and_accepts_skipped_symbols(self):
        dataset = SimpleNamespace(manifest={'role': 'validation/custody'},
                                  cases=[data('US.AAPL', day).case for day in VALIDATION_DAYS])
        validate_scope(dataset)
        dataset.cases[-1] = data('US.AAPL', '2026-10-14').case
        with self.assertRaisesRegex(ValueError, 'unexpected=.*2026-10-14'):
            validate_scope(dataset)

    def test_wrong_role_or_symbol_cannot_expand_validation_scope(self):
        dataset = SimpleNamespace(manifest={'role': 'train/custody'},
                                  cases=[data('US.AAPL', day).case for day in VALIDATION_DAYS])
        with self.assertRaisesRegex(ValueError, 'validation/custody'):
            validate_scope(dataset)
        dataset.manifest['role'] = 'validation/custody'
        dataset.cases[-1] = data('US.SPY', VALIDATION_DAYS[-1]).case
        with self.assertRaisesRegex(ValueError, 'outside'):
            validate_scope(dataset)

    def test_constructed_codes_match_the_futu_format_and_try_coarser_grids(self):
        self.assertEqual(strikes_to_try('US.AAPL', 336.04), [335.0, 340.0])
        self.assertEqual(strikes_to_try('US.INTC', 101.365), [101.5, 101.0, 102.0])
        self.assertEqual(option_code('US.MU', '2026-09-25', 'PUT', 1095.0), 'US.MU260925P1095000')
        self.assertEqual(option_code('US.AAPL', '2026-08-21', 'CALL', 312.5), 'US.AAPL260821C312500')

    def test_old_flow_side_is_the_opening_gap(self):
        self.assertEqual(gap_side(data('US.X', 'D1', first_open=101.0)), 'LONG')
        self.assertEqual(gap_side(data('US.X', 'D1', first_open=99.0)), 'SHORT')
        self.assertIsNone(gap_side(data('US.X', 'D1', first_open=100.0)))
        self.assertIsNone(gap_side(data('US.X', 'D1', prev_close=None)))

    def test_first_two_symbols_keep_both_sides_of_a_kept_symbol(self):
        datas = [data('US.A', 'D1'), data('US.A', 'D1', 'SHORT'), data('US.B', 'D1'), data('US.C', 'D1'), data('US.D', 'D1')]
        trades = [trade(30, .1), trade(90, .2), trade(10, -.1), trade(200, .5), trade(None)]
        kept = first_symbols(datas, trades)
        self.assertEqual([t['entry'] is not None for t in kept], [True, True, True, False, False])

    def test_bootstrap_needs_two_days_and_brackets_a_constant_difference(self):
        self.assertIsNone(diff_bootstrap({'D1': 5.0}, {}))
        result = diff_bootstrap({'D1': 5.0, 'D2': 5.0}, {'D1': 1.0, 'D2': 1.0}, draws=100)
        self.assertEqual((result['low_95'], result['high_95'], result['share_above_zero']), (8.0, 8.0, 1.0))


if __name__ == '__main__':
    unittest.main()
