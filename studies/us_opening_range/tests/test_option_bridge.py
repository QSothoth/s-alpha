"""Synthetic-only bridge tests; no real market data or network."""
import csv
from dataclasses import replace
from datetime import datetime, timedelta
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from custody.marketdata import Bar
from custody.models import ET
from studies.us_opening_range import option_bridge as module
from studies.us_opening_range.tests.test_daily_signals import bars, levels, OPEN


class MarkTests(unittest.TestCase):
    def point(self, minutes, price, volume=1):
        return Bar('US.SPY260918P100000', OPEN + timedelta(minutes=minutes),
                   price, price, price, price, volume)

    def test_put_mark_gain_is_positive_not_direction_signed(self):
        result = module.fixed_marks([self.point(15, 2), self.point(45, 3)], OPEN + timedelta(minutes=15))
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['mark_return_30m'], .5)

    def test_missing_endpoint_does_not_search_nearby_or_fill_zero(self):
        for values, missing in [([self.point(16, 2), self.point(45, 3)], ['reference']),
                                ([self.point(15, 2), self.point(46, 3)], ['future']),
                                ([], ['reference', 'future'])]:
            result = module.fixed_marks(values, OPEN + timedelta(minutes=15))
            self.assertEqual(result['missing'], missing)
            self.assertIsNone(result['mark_return_30m'])

    def test_zero_volume_zero_price_and_duplicate_endpoint_are_missing(self):
        for reference in [[self.point(15, 2, 0)], [self.point(15, 0)],
                          [self.point(15, 2), self.point(15, 2)]]:
            result = module.fixed_marks(reference + [self.point(45, 3)], OPEN + timedelta(minutes=15))
            self.assertEqual(result['missing'], ['reference'])
        self.assertEqual(module.fixed_marks([self.point(15, 2, 0), self.point(45, 3)],
                         OPEN + timedelta(minutes=15), require_volume=False)['mark_return_30m'], .5)

    def test_intermediate_no_print_does_not_create_path_or_missing_endpoint(self):
        result = module.fixed_marks([self.point(15, 2), self.point(25, 99, 0), self.point(45, 1)],
                                    OPEN + timedelta(minutes=15))
        self.assertEqual(result['mark_return_30m'], -.5)
        self.assertNotIn('path_status', result)

    def test_pinned_endpoint_reader_accepts_gaps_and_all_zero_leg(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'option').mkdir()
            path = root / 'option/US.SPY260918P100000.csv'
            dataset = SimpleNamespace(root=root, _pinned={path.resolve()})
            at = OPEN + timedelta(minutes=15)
            for volume in (0, 2):
                with path.open('w', newline='') as handle:
                    writer = csv.writer(handle)
                    writer.writerow(('code', 'close_time', 'interval', 'open', 'high', 'low', 'close', 'volume'))
                    for minutes, price in ((15, 2), (45, 3)):
                        writer.writerow(('US.SPY260918P100000', (OPEN + timedelta(minutes=minutes)).isoformat(),
                                         '1m', price, price, price, price, volume))
                points = module.endpoint_bars(dataset, 'option', 'US.SPY260918P100000', at)
                result = module.fixed_marks(points, at)
                self.assertEqual(result['status'], 'complete' if volume else 'missing')
                self.assertEqual(result['mark_return_30m'], .5 if volume else None)


class HistoryTests(unittest.TestCase):
    def write(self, path, values, extra=()):
        with path.open('w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=('code', 'time_key', 'open', 'high', 'low', 'close', 'volume'))
            writer.writeheader()
            for bar in values:
                writer.writerow(dict(code=bar.code, time_key=bar.close_time.strftime('%Y-%m-%d %H:%M:%S'),
                                     **{field: getattr(bar, field) for field in ('open', 'high', 'low', 'close', 'volume')}))
            writer.writerows(extra)

    def test_dates_are_filtered_before_price_conversion(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'SPY.csv'
            values = [replace(bar, close_time=bar.close_time.replace(year=2026, month=7, day=21)) for bar in bars(count=78)]
            self.write(path, values, [{'code': 'US.SPY', 'time_key': '2026-09-25 09:35:00',
                                      **{key: 'MUST NOT PARSE' for key in ('open', 'high', 'low', 'close', 'volume')}}])
            rows = list(module.history_sessions(path, 'SPY', {'2026-07-21': 78}))
            self.assertEqual(len(rows), 1)
            self.assertTrue(rows[0][2])

    def test_later_invalid_bar_keeps_signal_but_invalidates_full_session(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'SPY.csv'
            values = [replace(bar, close_time=bar.close_time.replace(year=2026, month=7, day=21)) for bar in bars(count=6)]
            self.write(path, values, [{'code': 'US.SPY', 'time_key': '2026-07-21 10:05:00',
                                      **{key: 'invalid' for key in ('open', 'high', 'low', 'close', 'volume')}}])
            day, current, complete = next(module.history_sessions(path, 'SPY', {'2026-07-21': 78}))
            self.assertFalse(complete)
            setup = levels(trade_date=day)
            signal = module.detect_signals(current, setup)[0]['PD_BREAK']
            self.assertIsNotNone(signal)
            self.assertEqual(signal['snapshot_minutes'], 15)
            self.assertEqual(module.evaluate_signal_quality(current, signal)['label_status'], 'missing_future')

    def test_duplicate_with_bad_price_cannot_be_dropped_into_valid_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'SPY.csv'
            values = [replace(bar, close_time=bar.close_time.replace(year=2026, month=7, day=21)) for bar in bars(count=2)]
            self.write(path, values, [{'code': 'US.SPY', 'time_key': '2026-07-21 09:40:00',
                                      **{key: 'invalid' for key in ('open', 'high', 'low', 'close', 'volume')}}])
            with self.assertRaisesRegex(ValueError, 'duplicate/unordered'):
                list(module.history_sessions(path, 'SPY', {'2026-07-21': 78}))

    def test_legacy_pinned_csv_without_code_column_and_wrong_explicit_code(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'SPY.csv'
            path.write_text('time_key,open,high,low,close,volume\n2026-07-21 09:35:00,1,1,1,1,1\n')
            day, current, complete = next(module.history_sessions(path, 'SPY', {'2026-07-21': 78}))
            self.assertEqual(current[0].code, 'US.SPY')
            self.assertFalse(complete)
            path.write_text('code,time_key,open,high,low,close,volume\nUS.QQQ,2026-07-21 09:35:00,1,1,1,1,1\n')
            with self.assertRaisesRegex(ValueError, 'unexpected symbol'):
                list(module.history_sessions(path, 'SPY', {'2026-07-21': 78}))

    def test_replay_gap_resets_twenty_day_history_and_never_includes_today(self):
        start = datetime(2026, 7, 21, tzinfo=ET)
        dates = [(start + timedelta(days=index)).date().isoformat() for index in range(97)]
        calendar = dict.fromkeys(dates, 78)
        dataset = SimpleNamespace(name='synthetic')
        pair = {'LONG': SimpleNamespace(session_close=None)}
        cases = {('US.SPY', day): (dataset, pair) for day in dates[20:]}
        stream = []
        for index, day in enumerate(dates):
            if index == 21:
                continue
            stamp = datetime.fromisoformat(day)
            current = [replace(bar, close_time=bar.close_time.replace(year=stamp.year, month=stamp.month, day=stamp.day))
                       for bar in bars(count=78)]
            stream.append((day, current, True))
        observed = []
        def historical(past, today):
            self.assertEqual(len(past), 20)
            self.assertTrue(all(bar.close_time.date() < today for bar in past))
            observed.append(today.isoformat())
            return {}
        with patch.object(module, 'SYMBOLS', ('SPY',)), \
             patch.object(module, 'load_inputs', return_value=(cases, calendar, {})), \
             patch.object(module, 'history_sessions', return_value=iter(stream)), \
             patch.object(module, 'daily_levels', side_effect=historical), \
             patch.object(module, 'detect_signals', return_value=(dict.fromkeys(module.CANDIDATES), {})):
            report, records = module.replay(Path('/unused'))
        self.assertEqual(len(records), 231)
        self.assertEqual(observed[:3], [dates[20], dates[21], dates[42]])
        self.assertEqual(report['candidates']['PD_BREAK']['signals'], 0)
        self.assertEqual(report['candidates']['PD_BREAK']['sessions'], 77)
        missing = [row for row in records if row['trade_date'] == dates[21]]
        self.assertTrue(all(row['status'] == 'MISSING_CURRENT_DATA' for row in missing))
        self.assertEqual(report['candidates']['PD_BREAK']['current_prefix_incomplete_sessions'], 1)


class SummaryTests(unittest.TestCase):
    def test_separate_denominators_missing_and_overlap(self):
        def record(candidate, underlying, option, signal=True):
            return {'candidate': candidate, 'trade_date': '2026-09-18', 'history_eligible': True,
                    'current_prefix_complete': True,
                    'signal': {} if signal else None,
                    'underlying': {'return_30m': underlying, 'path_status': 'neither'},
                    'option': {'mark_return_30m': option}}
        records = [record('PD_BREAK', .01, .5), record('PD_BREAK', -.005, None),
                   record('PD_BREAK', None, -.25), record('PD_BREAK', None, None, False),
                   record('NR7_BREAK', .01, .5)]
        result = module.summarize(records)
        pd = result['PD_BREAK']
        self.assertEqual((pd['sessions'], pd['signals']), (4, 3))
        self.assertEqual(pd['underlying']['labeled_signals'], 2)
        self.assertEqual(pd['option_gross_marks']['labeled_signals'], 2)
        self.assertEqual(pd['option_mark_coverage'], 2 / 3)
        self.assertEqual(pd['underlying']['win_rate'], .5)
        self.assertEqual(pd['option_gross_marks']['payoff_ratio'], 2)
        self.assertEqual(pd['joint_label_counts'], {'positive_underlying__positive_option': 1})
        self.assertIsNone(result['INSIDE_BREAK']['option_mark_coverage'])
        self.assertEqual(result['NR7_BREAK']['signals'], 1)

    def test_cli_refuses_overwrite_or_same_paths_before_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'report.json'
            output.write_text('preserve')
            with patch.object(module, 'replay') as replay, self.assertRaises(SystemExit):
                module.main(['--out', str(output), '--records-out', str(output.with_suffix('.jsonl'))])
            replay.assert_not_called()
            self.assertEqual(output.read_text(), 'preserve')
            output = Path(directory) / 'new.json'
            with patch.object(module, 'replay') as replay, self.assertRaises(SystemExit):
                module.main(['--out', str(output), '--records-out', str(output)])
            replay.assert_not_called()


if __name__ == '__main__':
    unittest.main()
