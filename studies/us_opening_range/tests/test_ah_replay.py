"""AH1 synthetic-only acceptance checks; no downloaded data or real labels."""
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from custody.dataset import sha256_file
from custody.marketdata import Bar
from custody.models import ET
from studies.us_opening_range import ah_replay as module


DAY = '2024-03-18'


def values(close=100, volume=10, width=1):
    return tuple(Decimal(str(value)) for value in (close, close + width, close - width, close, volume, 1000))


def trading_days(count, start=date(2020, 1, 2)):
    result = []
    while len(result) < count:
        if start.weekday() < 5:
            result.append(start.isoformat())
        start += timedelta(days=1)
    return result


def bars(symbol='AAPL', day=DAY, count=78, reference=99, terminal=98):
    opening = datetime.combine(date.fromisoformat(day), time(9, 30), ET)
    result, previous = [], 100
    for index in range(1, count + 1):
        close = reference if index <= 3 else terminal
        result.append(Bar('US.' + symbol, opening + timedelta(minutes=5 * index), previous,
                          max(previous, close) + 1, min(previous, close) - 1, close, 10, '5m'))
        previous = close
    return result


def ah(day='2024-03-15', close=103, stamps=('16:30:00', '20:00:00'), volume=0):
    return [(day + ' ' + stamp, values(close, volume, width=0), ('synthetic/ext.csv',)) for stamp in stamps]


def context():
    return {'atr20_pct': .02, 'previous_close': 100, 'history_first_date': '2024-02-15', 'previous_date': '2024-03-15'}


def background():
    return module.ah_background(ah(), context(), False)


def write_csv(path, kind, rows):
    key = 'date' if kind == 'daily' else 'time_key'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(','.join((key,) + module.FIELDS) + '\n' + '\n'.join(
        stamp + ',' + ','.join(str(value) for value in row) for stamp, row in rows) + '\n', encoding='utf-8')


class InputTests(unittest.TestCase):
    def test_decimal_dedup_ignores_format_but_rejects_any_numeric_conflict(self):
        with tempfile.TemporaryDirectory() as folder:
            left, right = Path(folder) / 'left.csv', Path(folder) / 'right.csv'
            write_csv(left, 'ext30', [('2024-03-15 20:00:00', values())])
            write_csv(right, 'ext30', [('2024-03-15 20:00:00', [str(v) + '.0' for v in values()])])
            count = module.Counter()
            rows = list(module.joined_rows([left, right], 'ext30', count))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][2], (str(left), str(right)))
            self.assertEqual(count, {'input_rows': 2, 'unique_rows': 1, 'duplicates_removed': 1})
            altered = list(values())
            altered[-1] += 1
            write_csv(right, 'ext30', [('2024-03-15 20:00:00', altered)])
            with self.assertRaisesRegex(ValueError, 'conflicting ext30'):
                list(module.joined_rows([left, right], 'ext30'))

    def test_source_time_domain_and_order_are_strict_and_history_stops_may30(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'raw.csv'
            for stamp in ('2024-03-15 20:30:00', '2024-03-15 03:30:00', '2024-03-15 17:15:00'):
                write_csv(path, 'ext30', [(stamp, values())])
                with self.assertRaisesRegex(ValueError, 'time domain'):
                    list(module.numeric_rows(path, 'ext30'))
            write_csv(path, 'ext30', [('2024-03-15 20:00:00', values()), ('2024-03-15 17:00:00', values())])
            with self.assertRaisesRegex(ValueError, 'unordered'):
                list(module.numeric_rows(path, 'ext30'))
            write_csv(path, 'daily', [('2024-05-30', values()), ('2024-05-31', ('bad',) * 6)])
            self.assertEqual(len(list(module.numeric_rows(path, 'daily'))), 1)

    def test_only_white_list_files_are_opened_and_each_raw_is_rehashed(self):
        with tempfile.TemporaryDirectory() as folder:
            root, calendar = Path(folder), Path(folder) / 'calendar.csv'
            base = root / 'package'
            write_csv(base / 'daily/AAPL.csv', 'daily', [('2024-03-15', values())])
            (base / 'manifest.json').write_text('{}', encoding='utf-8')
            checksum = base / 'CHECKSUMS.sha256'
            digest = sha256_file(base / 'daily/AAPL.csv')
            checksum.write_text(digest + '  daily/AAPL.csv\n' + '0' * 64 + '  daily/UNREGISTERED.csv\n', encoding='utf-8')
            calendar.write_text('metadata only', encoding='utf-8')
            sources = (('package', 'daily', sha256_file(checksum), sha256_file(base / 'manifest.json')),)
            with patch.object(module, 'SOURCES', sources), patch.object(module, 'SYMBOLS', ('AAPL',)), \
                    patch.object(module, 'CALENDAR_SHA256', sha256_file(calendar)):
                result = module.verify_sources(root, calendar)
                self.assertEqual(len(result), 4)
                self.assertEqual(result[str(base / 'daily/AAPL.csv')], digest)
                self.assertFalse(any('UNREGISTERED' in key for key in result))
                write_csv(base / 'daily/AAPL.csv', 'daily', [('2024-03-15', values(101))])
                with self.assertRaisesRegex(ValueError, 'raw checksum'):
                    module.verify_sources(root, calendar)

    def test_calendar_includes_warmup_and_only_explicit_half_day(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'calendar.csv'
            header = 'date,rows,first_close,last_close,missing_before_or_between\n'
            path.write_text(header + '2019-11-01,78,09:35:00,16:00:00,0\n2020-11-27,42,09:35:00,13:00:00,0\n')
            self.assertEqual(module.read_calendar(path), {'2019-11-01': 78, '2020-11-27': 42})
            path.write_text(header + '2020-11-27,42,09:35:00,16:00:00,0\n')
            with self.assertRaisesRegex(ValueError, 'calendar'):
                module.read_calendar(path)


class FeatureTests(unittest.TestCase):
    def test_original_atr_is_mean_twenty_percentage_trs_not_dollar_atr(self):
        dates = trading_days(21)
        history = [(day, values(100 + index)) for index, day in enumerate(dates)]
        result = module.history_context(history, '2021-01-01')
        expected = sum(2 / (100 + index) for index in range(20)) / 20
        self.assertAlmostEqual(result['atr20_pct'], expected)
        self.assertNotAlmostEqual(result['atr20_pct'], 2 / 120)
        self.assertEqual(result['previous_close'], 120)
        self.assertIsNone(module.history_context(history[:-1], '2021-01-01'))
        with self.assertRaisesRegex(ValueError, 'prior days'):
            module.history_context(history, dates[-1])

    def test_ah_keeps_original_zero_volume_endpoint_without_completeness_gate(self):
        result = module.ah_background(ah(stamps=('16:30:00', '17:00:00')), context(), True)
        self.assertEqual(result['status'], 'pass')
        flags = result['quality']
        self.assertEqual(flags['ah_last_time'], '2024-03-15 17:00:00')
        self.assertFalse(flags['ah_endpoint_2000'])
        self.assertFalse(flags['ah_grid_complete_8'])
        self.assertEqual(len(flags['ah_missing_expected_bars']), 6)
        for key in ('ah_last_zero_volume', 'ah_any_zero_volume', 'ah_all_zero_volume',
                    'ah_last_flat_zero_volume', 'previous_session_half_day'):
            self.assertTrue(flags[key])
        self.assertEqual(module.ah_background([], context(), False)['status'], 'unknown')
        self.assertEqual(module.ah_background(ah(close=97), context(), False)['status'], 'pass')
        self.assertEqual(module.ah_background(ah(close=101), context(), False)['status'], 'fail')
        broken = ah() + [('2024-03-15 20:00:00', values(0, width=0), ('bad',))]
        self.assertEqual(module.ah_background(broken, context(), False)['status'], 'unknown')

    def test_missing_reference_retains_base_and_equal_open_never_confirms_down(self):
        contexts, backgrounds = {'AAPL': context()}, {'AAPL': background()}
        pending = module.freeze_events(DAY, contexts, backgrounds, {'AAPL': bars()[1:]})
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]['candidate'], 'Q2_BASE_945')
        self.assertEqual(pending[0]['reference_status'], 'missing_reference')
        self.assertEqual(pending[0]['down_confirmation'], 'unknown')
        self.assertIsNone(pending[0]['reference'])
        pending = module.freeze_events(DAY, contexts, backgrounds, {'AAPL': bars(reference=100)})
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]['down_confirmation'], 'fail')

    def test_peer_list_needs_history_and_prefix_but_not_ah_or_future(self):
        contexts = {symbol: context() for symbol in ('AAPL', 'MSFT', 'NVDA', 'TSLA')}
        backgrounds = {symbol: background() if symbol == 'AAPL' else {'status': 'unknown'} for symbol in contexts}
        current = {symbol: bars(symbol) for symbol in contexts}
        current['TSLA'] = bars('TSLA', reference=101)
        pending = module.freeze_events(DAY, contexts, backgrounds, current)
        self.assertEqual(len(pending), 2)
        self.assertEqual(pending[0]['peers'], ['MSFT', 'NVDA'])
        changed = {symbol: rows[:3] + [replace(bar, code='US.BAD', low=0) for bar in rows[3:]]
                   for symbol, rows in current.items()}
        with patch.object(module, 'terminal_label', side_effect=AssertionError('future read')):
            self.assertEqual(module.freeze_events(DAY, contexts, backgrounds, changed), pending)
        del contexts['NVDA']
        self.assertEqual(module.freeze_events(DAY, contexts, backgrounds, current)[0]['peers'], ['MSFT'])


class LabelTests(unittest.TestCase):
    def test_window_endpoint_is_terminal_close_and_not_same_bar_or_extreme(self):
        rows = bars()
        rows[3] = replace(rows[3], high=200, low=1)
        rows[8] = replace(rows[8], close=97, low=96)
        result = module.terminal_label(rows, 'AAPL', DAY, 9)
        self.assertEqual(result['status'], 'complete')
        self.assertAlmostEqual(result['return'], 1 - 97 / 99)
        rows[9] = replace(rows[9], close=50, low=49)
        self.assertEqual(module.terminal_label(rows, 'AAPL', DAY, 9), result)
        self.assertEqual(module.terminal_label(rows[:8], 'AAPL', DAY, 9)['status'], 'missing_future')

    def test_full_future_grid_and_halfday_are_required_independently(self):
        rows = bars(count=42)
        self.assertEqual(module.terminal_label(rows, 'AAPL', DAY, 9)['status'], 'complete')
        self.assertEqual(module.terminal_label(rows, 'AAPL', DAY, 42)['status'], 'complete')
        self.assertEqual(module.terminal_label(rows, 'AAPL', DAY, 78)['status'], 'missing_future')
        hole = rows[:20] + rows[21:]
        self.assertEqual(module.terminal_label(hole, 'AAPL', DAY, 9)['status'], 'complete')
        self.assertEqual(module.terminal_label(hole, 'AAPL', DAY, 42)['status'], 'missing_future')
        invalid = rows[:3] + [replace(rows[3], code='US.BAD')] + rows[4:]
        self.assertEqual(module.terminal_label(invalid, 'AAPL', DAY, 9)['status'], 'missing_future')

    def test_all_peers_are_fixed_and_missing_in_one_window_does_not_spoil_other(self):
        event = {'symbol': 'US.AAPL', 'peers': ['MSFT', 'NVDA']}
        labels = {symbol: {'30m': module.terminal_label(bars(symbol, count=count), symbol, DAY, 9),
                           'to_close': module.terminal_label(bars(symbol, count=count), symbol, DAY, 78)}
                  for symbol, count in (('AAPL', 78), ('MSFT', 78), ('NVDA', 9))}
        result = module.evaluate_event(event, labels)
        self.assertEqual(result['30m']['paired_status'], 'complete')
        self.assertAlmostEqual(result['30m']['paired_lift'], 0)
        self.assertEqual(result['to_close']['paired_status'], 'missing_peer')
        self.assertIsNone(result['to_close']['paired_lift'])
        self.assertEqual(set(result['to_close']['peer_labels']), {'MSFT', 'NVDA'})
        labels['NVDA']['30m'] = {'return': None, 'status': 'missing_future'}
        self.assertEqual(module.evaluate_event(event, labels)['30m']['paired_status'], 'missing_peer')
        event['peers'] = []
        self.assertEqual(module.evaluate_event(event, labels)['30m']['paired_status'], 'no_peers')


class SummaryTests(unittest.TestCase):
    def test_all_four_labels_share_same_date_draw_with_zero_dates_and_quantiles(self):
        days = {day: module.day_record() for day in ('2021-01-04', '2023-01-04', '2023-01-05')}
        days['2021-01-04'].update(signals=2, returns=[.01], paired=[.002], close_returns=[.02], close_paired=[.004])
        days['2023-01-04'].update(signals=2, returns=[-.03, .01], paired=[-.004, .002], close_returns=[-.06, .02], close_paired=[-.008, .004])
        first = ((.01, 1), (.002, 1), (.02, 1), (.004, 1))
        second = ((-.02, 2), (-.002, 2), (-.04, 2), (-.004, 2))
        zero = ((0, 0),) * 4
        rng = Mock()
        rng.choice.side_effect = [first] * 3 + [second] * 3 + [zero] * 3 + [first, second, zero]
        with patch.object(module.random, 'Random', return_value=rng) as seeded, \
                patch.object(module, 'quantile', wraps=module.quantile) as quantile:
            result = module.summarize(days, draws=4)
        seeded.assert_called_once_with(20260926)
        self.assertEqual(rng.choice.call_count, 12)
        self.assertEqual([call.args[1] for call in quantile.call_args_list], [.025, .05, .05, .05])
        for call in rng.choice.call_args_list:
            self.assertEqual(len(call.args[0]), 3)
            self.assertEqual(call.args[0][-1], zero)
        self.assertEqual((result['signals'], result['active_dates'], result['n_dates']), (4, 2, 3))
        main = result['primary']
        self.assertEqual(main['paired_coverage'], .75)
        self.assertEqual(main['missing_labels'], 1)
        self.assertEqual(main['bootstrap']['undefined_raw_draws'], 1)
        self.assertEqual(main['bootstrap']['undefined_paired_draws'], 1)
        self.assertEqual(main['halves']['before_2022_06_01']['raw']['labeled_signals'], 1)
        self.assertAlmostEqual(main['raw']['mean_lower_bp'], -100 + (200 / 3) * .05)
        self.assertAlmostEqual(main['paired']['mean_lower_bp'], -9)

    def test_zero_labels_pf_without_loss_halves_and_eod_cannot_rescue(self):
        days = {day: module.day_record() for day in trading_days(60, date(2022, 5, 2))}
        for row in days.values():
            row.update(signals=2, returns=[.01, 0], paired=[.005, 0], close_returns=[-.1, -.1], close_paired=[-.1, -.1])
        result = module.summarize(days, draws=5)
        self.assertTrue(result['development_eligible'])
        self.assertIsNone(result['primary']['raw']['profit_factor'])
        self.assertEqual(result['primary']['raw']['wins'], 60)
        self.assertEqual(result['primary']['raw']['zeros'], 60)
        self.assertLess(result['to_close_descriptive']['raw']['mean_bp'], 0)
        for row in days.values():
            row['returns'] = [0, 0]
            row['close_returns'] = [.1, .1]
        result = module.summarize(days, draws=5)
        self.assertFalse(result['development_eligible'])
        self.assertFalse(result['gates']['profit_factor_at_least_1_2'])
        empty = module.summarize({'2024-03-18': module.day_record()}, draws=5)
        self.assertEqual(empty['primary']['bootstrap']['undefined_raw_draws'], 5)
        self.assertEqual(empty['primary']['paired_coverage'], 0)
        self.assertFalse(empty['development_eligible'])


class ReplayTests(unittest.TestCase):
    def test_today_daily_missing_never_erases_known_background_and_next_day_resets(self):
        dates = trading_days(24)
        calendar = {day: 78 for day in dates}
        events = []

        def historical(root, symbol, kind):
            for index, day in enumerate(dates):
                if kind == 'daily':
                    if symbol == 'AAPL' and index == 21:
                        continue
                    yield day, [(day, values(), ('daily',))]
                else:
                    yield day, ah(day) if symbol == 'AAPL' else []

        def sessions(path, symbol, calendar):
            for day in dates:
                yield day, symbol, bars(symbol, day, count=9), False

        with patch.object(module, 'SYMBOLS', ('AAPL', 'MSFT')), \
                patch.object(module, 'verify_sources', return_value={'synthetic': 'only'}), \
                patch.object(module, 'read_calendar', return_value=calendar), \
                patch.object(module, 'preflight', return_value={'synthetic': 'checked'}), \
                patch.object(module, '_history_days', side_effect=historical), \
                patch.object(module, 'iter_sessions', side_effect=sessions), \
                patch.object(module, 'summarize', wraps=lambda rows: {'development_eligible': False, 'signals': sum(day['signals'] for day in rows.values())}):
            result = module.replay(Path('synthetic-only'), emit=events.append)
        self.assertEqual(len(events), 2)
        self.assertEqual({event['candidate'] for event in events}, set(module.CANDIDATES))
        for event in events:
            self.assertEqual(event['trade_date'], dates[21])
            self.assertEqual(event['previous_date'], dates[20])
            self.assertEqual(event['peers'], ['MSFT'])
            self.assertEqual(event['labels']['30m']['paired_status'], 'complete')
            self.assertEqual(event['labels']['to_close']['status'], 'missing_future')
        self.assertEqual(result['overlapping_base_down_signals'], 1)
        self.assertEqual(len(result['by_day']['Q2_BASE_945']), 24)
        self.assertEqual(result['by_day']['Q2_BASE_945'][dates[22]]['signals'], 0)
        self.assertEqual(result['source_equivalence'], 'unverified')
        json.dumps(result, allow_nan=False)

    def test_join_failure_happens_before_any_detection_or_label(self):
        with patch.object(module, 'verify_sources', return_value={}), \
                patch.object(module, 'read_calendar', return_value={DAY: 78}), \
                patch.object(module, 'preflight', side_effect=ValueError('conflicting ext30')), \
                patch.object(module, 'freeze_events') as detect, patch.object(module, 'terminal_label') as label:
            with self.assertRaisesRegex(ValueError, 'conflicting'):
                module.replay(Path('synthetic-only'))
        detect.assert_not_called()
        label.assert_not_called()

    def test_cli_refuses_any_existing_or_shared_output_without_replay(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(module, 'replay') as replay:
            report, events = Path(folder) / 'report.json', Path(folder) / 'events.jsonl'
            report.write_text('user data')
            with self.assertRaises(SystemExit):
                module.main(['--out', str(report), '--signals-out', str(events)])
            self.assertEqual(report.read_text(), 'user data')
            self.assertFalse(events.exists())
            with self.assertRaises(SystemExit):
                module.main(['--out', str(events), '--signals-out', str(events)])
            replay.assert_not_called()


if __name__ == '__main__':
    unittest.main()
