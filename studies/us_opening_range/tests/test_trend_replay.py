import csv
from datetime import datetime, timedelta
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from custody.dataset import sha256_file, write_checksums
from studies.us_opening_range import trend_replay as module


def write_csv(path, days=15, *, incomplete=(), missing=(), trend=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    dates, current = [], datetime(2020, 1, 2, 9, 30)
    while len(dates) < days:
        if current.weekday() < 5:
            dates.append(current)
        current += timedelta(days=1)
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=('time_key', 'open', 'high', 'low', 'close', 'volume'))
        writer.writeheader()
        for day_index, start in enumerate(dates):
            if day_index in missing:
                continue
            for index in range(42 if day_index in incomplete else 78):
                values = dict(open=100, high=101, low=99, close=100, volume=10)
                if trend and day_index == days - 1:
                    if index == 6:
                        values.update(open=101, high=101.5, low=100, close=101.25)
                    elif index > 6:
                        values.update(open=101.5, high=102, low=101, close=102)
                writer.writerow(dict(time_key=str(start + timedelta(minutes=5 * (index + 1))), **values))
    return [day.date().isoformat() for day in dates]


def fixture(root, *, days=15, trend=False):
    manifest = {'name': 'preopen-us-k5-select-v1', 'role': 'train/preopen-k5',
                'window': ['2020-01-02', '2024-05-31']}
    (root / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    for symbol in module.SYMBOLS:
        dates = write_csv(root / 'k5' / (symbol + '.csv'), days, trend=trend)
    write_checksums(root)
    return dates


class TrendReplayTests(unittest.TestCase):
    def test_synthetic_integration_costs_and_all_local_dependency_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dates = fixture(root, trend=True)
            result = module.replay(root)
        self.assertEqual('OR3', result['round'])
        self.assertEqual('DEVELOPMENT_ONLY', result['verdict'])
        self.assertIsNone(result['selected_for_further_testing'])
        self.assertEqual(module.PREREG_SHA256, result['preregistration_sha256'])
        self.assertEqual(15, len(result['inputs']['files_sha256']))
        self.assertEqual(14, result['resources']['history_days_per_symbol'])
        for name in module.CANDIDATES:
            self.assertEqual(14, result['candidates'][name]['n_sessions'])
            self.assertEqual(14, result['candidates'][name]['trades'])
            self.assertAlmostEqual(-10, result['candidates'][name]['net_mean_bp'])
            self.assertEqual({dates[-1]}, set(result['by_day'][name]))
            self.assertEqual(14, result['by_day'][name][dates[-1]]['n_sessions'])
        expected = {
            'studies/us_opening_range/trend_replay.py',
            'studies/us_opening_range/trend_signals.py',
            'studies/us_opening_range/context_replay.py',
            'studies/us_opening_range/context_signals.py',
            'studies/us_opening_range/context_stats.py',
            'custody/__init__.py', 'custody/dataset.py', 'custody/marketdata.py', 'custody/models.py',
        }
        self.assertEqual(expected, set(result['code_sha256']))
        repo = Path(module.__file__).resolve().parents[2]
        for path, digest in result['code_sha256'].items():
            self.assertEqual(sha256_file(repo / path), digest)

    def test_bounded_prior_complete_history_and_zero_trade_sessions(self):
        observed = []

        def trades(bars, history):
            self.assertEqual(14, len(history))
            self.assertTrue(all(len(past) == 78 for past in history))
            self.assertTrue(all(past[-1].close_time < bars[0].close_time for past in history))
            self.assertTrue(all(past[0].code == bars[0].code for past in history))
            observed.append((bars[0].code, bars[0].close_time.date().isoformat()))
            return dict.fromkeys(module.CANDIDATES)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dates = write_csv(root / 'k5' / 'SPY.csv', 18, incomplete=(3,), missing=(5,))
            write_csv(root / 'k5' / 'AAPL.csv', 18)
            with patch.object(module, 'SYMBOLS', ('SPY', 'AAPL')), \
                    patch.object(module, 'verify_inputs', return_value={}), \
                    patch.object(module, 'trend_trades', side_effect=trades):
                result = module.replay(root)
        self.assertEqual(6, len(observed))
        self.assertEqual(14, result['coverage_by_symbol']['SPY']['warmup_days'])
        self.assertEqual(1, result['coverage_by_symbol']['SPY']['short_session'])
        self.assertEqual(1, result['coverage_by_symbol']['SPY']['missing_day'])
        self.assertEqual(2, result['coverage_by_symbol']['SPY']['eligible_days'])
        for name in module.CANDIDATES:
            self.assertEqual(6, result['candidates'][name]['n_sessions'])
            self.assertEqual(0, result['candidates'][name]['trades'])
            self.assertEqual(4, result['candidates'][name]['n_dates'])
            self.assertEqual({'n_sessions': 1, 'returns': []}, result['by_day'][name][dates[14]])

    def test_fixed_selection_gates_ranking_and_tie_priority(self):
        scenarios = ((False, False, 8, 9, None), (True, False, 8, 99, 'O30_VWAP'),
                     (False, True, 99, 8, 'N30_TRAIL'), (True, True, 8, 9, 'N30_TRAIL'),
                     (True, True, 9, 8, 'O30_VWAP'), (True, True, 8, 8, 'O30_VWAP'))
        for first, second, lower_first, lower_second, selected in scenarios:
            with self.subTest(selected=selected, lower=(lower_first, lower_second)), \
                    patch.object(module, 'verify_inputs', return_value={}), \
                    patch.object(module, 'iter_days', return_value=iter(())), \
                    patch.object(module, 'summarize_days', side_effect=[
                        {'selected_eligible': first, 'net_mean_lower_95_bp': lower_first},
                        {'selected_eligible': second, 'net_mean_lower_95_bp': lower_second}]):
                result = module.replay('/unused-synthetic-root')
                self.assertEqual(selected, result['selected_for_further_testing'])

    def test_wrong_dataset_and_changed_prereg_abort_before_reading_bars(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'manifest.json').write_text(json.dumps({
                'name': 'new-etf-holdout', 'role': 'holdout/underlying-context'}), encoding='utf-8')
            with patch.object(module, 'iter_days') as reader, self.assertRaisesRegex(ValueError, 'development'):
                module.replay(root)
            reader.assert_not_called()
            with patch.object(module, 'PREREG_SHA256', 'changed'), \
                    patch.object(module, 'verify_inputs') as verify, self.assertRaisesRegex(ValueError, 'changed'):
                module.replay(root)
            verify.assert_not_called()

    def test_bad_execution_and_candidate_set_abort_without_dropping_session(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_csv(root / 'k5' / 'SPY.csv')
            for effect, message in ((ValueError('no executable exit'), 'no executable'),
                                    ({'O30_VWAP': None}, 'candidate set')):
                options = {'side_effect': effect} if isinstance(effect, Exception) else {'return_value': effect}
                with self.subTest(message=message), patch.object(module, 'SYMBOLS', ('SPY',)), \
                        patch.object(module, 'verify_inputs', return_value={}), \
                        patch.object(module, 'trend_trades', **options), \
                        self.assertRaisesRegex(ValueError, message):
                    module.replay(root)

    def test_out_of_window_data_is_fatal(self):
        with patch.object(module, 'verify_inputs', return_value={}), \
                patch.object(module, 'SYMBOLS', ('SPY',)), \
                patch.object(module, 'iter_days', return_value=iter([('2025-01-02', 'SPY', None, 'short_session')])), \
                self.assertRaisesRegex(ValueError, 'outside preregistered'):
            module.replay('/unused-synthetic-root')

    def test_existing_output_not_overwritten_or_evaluated(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'report.json'
            out.write_text('unchanged', encoding='utf-8')
            with patch.object(module, 'replay') as replay, patch('sys.stderr', io.StringIO()), \
                    self.assertRaises(SystemExit):
                module.main(['--out', str(out)])
            replay.assert_not_called()
            self.assertEqual('unchanged', out.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
