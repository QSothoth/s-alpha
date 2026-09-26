import csv
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from custody.dataset import write_checksums
from studies.us_opening_range import context_replay as module


def write_csv(path, days=1, count=78, changes=None, omit_days=()):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=['time_key', 'open', 'high', 'low', 'close', 'volume'])
        writer.writeheader()
        for day in range(days):
            if day in omit_days:
                continue
            start = datetime(2020, 1, 2, 9, 30) + timedelta(days=day)
            for index in range(count):
                row = dict(time_key=str(start + timedelta(minutes=5 * (index + 1))),
                           open=100, high=101, low=99, close=100, volume=10)
                row.update((changes or {}).get(index, {}))
                writer.writerow(row)


class StreamingTests(unittest.TestCase):
    def test_complete_and_incomplete_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'SPY.csv'
            for count, reason in ((78, None), (42, 'short_session'),
                                  (77, 'incomplete_session'), (79, 'too_many_bars')):
                write_csv(path, count=count)
                result = list(module.iter_days(path, 'SPY'))
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0][3], reason)
                self.assertEqual(len(result[0][2]), 78) if reason is None else self.assertIsNone(result[0][2])

    def test_duplicates_disorder_and_invalid_ohlc(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'SPY.csv'
            for stamp in ('2020-01-02 09:35:00', '2020-01-01 09:35:00'):
                write_csv(path, changes={1: {'time_key': stamp}})
                with self.assertRaisesRegex(ValueError, 'unordered'):
                    list(module.iter_days(path, 'SPY'))
            write_csv(path, changes={4: {'close': 110}})
            self.assertEqual(list(module.iter_days(path, 'SPY'))[0][3], 'invalid_ohlcv')
            write_csv(path, changes={77: {'time_key': '2020-01-02 16:01:00'}})
            self.assertEqual(list(module.iter_days(path, 'SPY'))[0][3], 'invalid_session_grid')
            write_csv(path, count=42, changes={41: {'time_key': '2020-01-02 13:01:00'}})
            self.assertEqual(list(module.iter_days(path, 'SPY'))[0][3], 'incomplete_session')

    def test_checksum_and_dataset_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = {'name': 'preopen-us-k5-select-v1', 'role': 'train/preopen-k5',
                        'window': ['2020-01-02', '2024-05-31']}
            (root / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            for symbol in module.SYMBOLS:
                write_csv(root / 'k5' / (symbol + '.csv'))
            write_checksums(root)
            self.assertEqual(len(module.verify_inputs(root)['files_sha256']), 15)
            write_csv(root / 'k5' / 'SPY.csv', count=77)
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                module.verify_inputs(root)
            manifest['role'] = 'validation'
            (root / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'preregistered'):
                module.verify_inputs(root)

    def test_streaming_history_is_past_only_and_days_align(self):
        observed = []

        def trades(bars, history, market):
            self.assertEqual(len(history), 14)
            self.assertTrue(all(previous[-1].close_time < bars[0].close_time for previous in history))
            self.assertEqual(market[0].close_time, bars[0].close_time)
            observed.append(bars[0].code)
            return {name: None for name in module.CANDIDATES}

        def summarize(days):
            return {'selected_eligible': False, 'net_mean_lower_95_bp': None,
                    'n_sessions': sum(day['n_sessions'] for day in days.values())}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for symbol in ('SPY', 'AAPL'):
                write_csv(root / 'k5' / (symbol + '.csv'), days=16)
            with patch.object(module, 'SYMBOLS', ('SPY', 'AAPL')), \
                    patch.object(module, 'verify_inputs', return_value={}), \
                    patch.object(module, 'context_trades', side_effect=trades), \
                    patch.object(module, 'summarize_days', side_effect=summarize):
                result = module.replay(root)
            self.assertEqual(len(observed), 4)
            self.assertEqual(result['coverage_by_symbol']['SPY']['warmup_days'], 14)
            self.assertEqual(result['candidates']['N30']['n_sessions'], 4)
            self.assertIsNone(result['selected_for_further_testing'])

    def test_missing_market_day_is_not_replaced_by_previous_day(self):
        observed = []

        def trades(bars, history, market):
            observed.append((bars[0].code, bars[0].close_time.day, market is None))
            return {name: None for name in module.CANDIDATES}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_csv(root / 'k5' / 'SPY.csv', days=16, omit_days=(14,))
            write_csv(root / 'k5' / 'AAPL.csv', days=16)
            with patch.object(module, 'SYMBOLS', ('SPY', 'AAPL')), \
                    patch.object(module, 'verify_inputs', return_value={}), \
                    patch.object(module, 'context_trades', side_effect=trades), \
                    patch.object(module, 'summarize_days', return_value={'selected_eligible': False}):
                result = module.replay(root)
            self.assertIn(('US.AAPL', 16, True), observed)
            self.assertIn(('US.AAPL', 17, False), observed)
            self.assertEqual(result['coverage_by_symbol']['SPY']['missing_day'], 1)
            self.assertEqual(result['coverage_by_symbol']['AAPL']['market_unavailable_days'], 1)

    def test_existing_report_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'existing.json'
            out.write_text('unchanged', encoding='utf-8')
            with patch.object(module, 'replay') as replay, self.assertRaises(SystemExit):
                module.main(['--out', str(out)])
            replay.assert_not_called()
            self.assertEqual(out.read_text(encoding='utf-8'), 'unchanged')


if __name__ == '__main__':
    unittest.main()
