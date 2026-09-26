import csv
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from custody.marketdata import Bar
from custody.models import ET
from studies.us_opening_range import daily_replay as module


def bars(count=78):
    opening = datetime(2020, 1, 2, 9, 30, tzinfo=ET)
    return [Bar('US.SPY', opening + timedelta(minutes=5 * (i + 1)),
                100, 101, 99, 100, 1, interval='5m') for i in range(count)]


def write_csv(path, count=78, changes=None):
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=('time_key', 'open', 'high', 'low', 'close', 'volume'))
        writer.writeheader()
        for i, bar in enumerate(bars(count)):
            row = {key: getattr(bar, key) for key in ('open', 'high', 'low', 'close', 'volume')}
            row['time_key'] = bar.close_time.replace(tzinfo=None).isoformat(sep=' ')
            row.update((changes or {}).get(i, {}))
            writer.writerow(row)


class StreamTests(unittest.TestCase):
    def test_full_and_half_days_aggregate(self):
        for count in (42, 78):
            day = module.aggregate_daily(bars(count), expected_bars=count)
            self.assertEqual(day.interval, '1d')
            self.assertEqual(day.volume, count)
            self.assertEqual(day.close_time, bars(count)[-1].close_time)
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            module.aggregate_daily(bars(77))
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            module.aggregate_daily(bars(42))

    def test_afternoon_problem_retains_morning_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'SPY.csv'
            write_csv(path, count=77)
            day, symbol, values, complete = next(module.iter_sessions(path, 'SPY'))
            self.assertEqual((day, symbol), ('2020-01-02', 'SPY'))
            self.assertFalse(complete)
            self.assertEqual(values[:6], bars()[:6])
            write_csv(path, changes={70: {'close': 120}})
            _, _, values, complete = next(module.iter_sessions(path, 'SPY'))
            self.assertFalse(complete)
            self.assertEqual(values[:6], bars()[:6])

    def test_duplicate_rejected_and_session_memory_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'SPY.csv'
            write_csv(path, changes={1: {'time_key': '2020-01-02 09:35:00'}})
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                list(module.iter_sessions(path, 'SPY'))
            write_csv(path, count=100)
            _, _, values, complete = next(module.iter_sessions(path, 'SPY'))
            self.assertEqual(len(values), 78)
            self.assertFalse(complete)

    def test_grid_gap_rejected_for_next_day_history(self):
        values = bars(78)
        values[5] = values[4]
        self.assertFalse(module.complete_session(values))

    def test_replay_uses_past_history_and_keeps_incomplete_current_day(self):
        stream, observed = [], []
        for offset in range(23):
            values = [Bar(bar.code, bar.close_time + timedelta(days=offset),
                          bar.open, bar.high, bar.low, bar.close, bar.volume, interval='5m')
                      for bar in bars(77 if offset == 20 else 78)]
            stream.append((values[0].close_time.date().isoformat(), 'SPY', values, offset != 20))

        def levels(history, today):
            observed.append(today.isoformat())
            self.assertEqual(len(history), 20)
            self.assertTrue(all(bar.close_time.date() < today for bar in history))
            return {}

        with patch.object(module, 'SYMBOLS', ('SPY',)), \
                patch.object(module, 'sha256_file', side_effect=lambda path:
                             module.PREREG_SHA256 if Path(path).name == 'DS1_PREREG.md'
                             else module.INPUT_SHA256), \
                patch.object(module, 'verify_inputs', return_value={}), \
                patch.object(module, 'read_calendar', return_value={row[0]: 78 for row in stream}), \
                patch.object(module, 'iter_sessions', return_value=iter(stream)), \
                patch.object(module, 'daily_levels', side_effect=levels), \
                patch.object(module, 'detect_signals', return_value=(dict.fromkeys(module.CANDIDATES), {})):
            result = module.replay(Path('/unused'))
        self.assertEqual(observed, ['2020-01-22'])
        self.assertEqual(result['coverage_by_symbol']['SPY']['history_eligible_days'], 1)
        self.assertEqual(result['candidates']['PD_BREAK']['eligible_sessions'], 1)

    def test_half_day_requires_external_calendar(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'SPY.csv'
            write_csv(path, count=42)
            self.assertFalse(next(module.iter_sessions(path, 'SPY'))[3])
            self.assertTrue(next(module.iter_sessions(path, 'SPY', {'2020-01-02': 42}))[3])
            self.assertFalse(next(module.iter_sessions(path, 'SPY', {'2020-01-02': 78}))[3])


class SummaryTests(unittest.TestCase):
    def test_win_rate_and_payoff_share_same_population(self):
        result = module.metrics([0.02, -0.01, 0])
        self.assertEqual(result['win_rate'], 1 / 3)
        self.assertEqual(result['payoff_ratio'], 2)
        self.assertEqual(result['profit_factor'], 2)
        self.assertEqual(result['zeros'], 1)
        self.assertIsNone(module.metrics([])['win_rate'])
        self.assertIsNone(module.metrics([0.01])['payoff_ratio'])

    def test_date_control_and_zero_signal_dates(self):
        days = {'2021-01-04': {'n_sessions': 2, 'signals': 1, 'returns': [0.01]},
                '2023-01-04': {'n_sessions': 2, 'signals': 1, 'returns': [-0.005]},
                '2023-01-05': {'n_sessions': 2, 'signals': 0, 'returns': []}}
        control = {**days, '2021-01-04': {'returns': [0.005, 0]},
                   '2023-01-04': {'returns': [-0.01, 0]}}
        result = module.summarize(days, control, draws=20)
        self.assertEqual(result['n_dates'], 3)
        self.assertEqual(result['signals_per_100_sessions'], 100 / 3)
        self.assertAlmostEqual(result['same_date_control_lift_bp'], 37.5)
        self.assertFalse(result['development_eligible'])
        self.assertTrue(result['bootstrap']['zero_signal_dates_included'])
        self.assertEqual(result, module.summarize(days, control, draws=20))

    def test_missing_labels_not_winners(self):
        days = {'2021-01-04': {'n_sessions': 2, 'signals': 2, 'returns': [0.01]}}
        result = module.summarize(days, days, draws=5)
        self.assertEqual(result['signals'], 2)
        self.assertEqual(result['labeled_signals'], 1)
        self.assertEqual(result['missing_labels'], 1)
        self.assertEqual(result['win_rate'], 1)
        self.assertFalse(result['development_eligible'])

    def test_no_events_remain_explicit(self):
        days = {'2021-01-04': {'n_sessions': 1, 'signals': 0, 'returns': []}}
        result = module.summarize(days, days, draws=10)
        self.assertEqual(result['signals'], 0)
        self.assertIsNone(result['mean_lower_95_bp'])
        self.assertEqual(result['bootstrap']['undefined_draws'], 10)
        self.assertFalse(result['development_eligible'])

    def test_report_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            path.write_text('unchanged', encoding='utf-8')
            with patch.object(module, 'replay') as replay, self.assertRaises(SystemExit):
                module.main(['--out', str(path)])
            replay.assert_not_called()
            self.assertEqual(path.read_text(encoding='utf-8'), 'unchanged')


if __name__ == '__main__':
    unittest.main()
