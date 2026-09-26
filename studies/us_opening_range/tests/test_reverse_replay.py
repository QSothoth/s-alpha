"""Synthetic RG1 checks; no real held-out price rows, APIs or labels."""
from dataclasses import replace
from datetime import date, datetime, time, timedelta
import csv
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from custody.dataset import sha256_file
from custody.marketdata import Bar
from custody.models import ET
from studies.us_opening_range import reverse_replay as module


TODAY = date(2024, 3, 18)


def bars(symbol='XLV', day=TODAY, count=78, direction='LONG', minutes=15, future=104, quiet=False):
    start, rows = datetime.combine(day, time(9, 30), ET), []
    for index in range(count):
        opening = 100 if quiet else 104 if index == 0 else 105
        close = 100 if quiet else 105 if index < minutes // 5 else future
        high, low = (101, 99) if quiet else (max(opening, close) + .1, min(opening, close) - .1)
        row = Bar('US.' + symbol, start + timedelta(minutes=5 * (index + 1)),
                  opening, high, low, close, 20, '5m')
        if direction == 'SHORT':
            row = replace(row, open=200 - row.open, high=200 - row.low,
                          low=200 - row.high, close=200 - row.close)
        rows.append(row)
    return rows


def levels(symbol='XLV', day=TODAY):
    return {'symbol': 'US.' + symbol, 'trade_date': day.isoformat(), 'atr': 4,
            'previous_close': 100, 'range_high20': 102, 'range_low20': 98,
            'mean_opening_volume': {15: 30, 20: 40, 30: 60}}


def event(symbol='XLV', direction='LONG', minutes=15, rows=None):
    rows = rows if rows is not None else bars(symbol, direction=direction, minutes=minutes)
    original = module.measurement_signal(rows[:minutes // 5], levels(symbol), direction)
    return module.reverse_event(original | {'candidate': 'G20_HOLD', 'snapshot_minutes': minutes,
                               'key_level': 102 if direction == 'LONG' else 98,
                               'activity_reason': 'gap', 'gap_atr': 1 if direction == 'LONG' else -1})


def panel(direction='LONG', minutes=15):
    return ({symbol: levels(symbol) for symbol in module.SYMBOLS},
            {symbol: (bars(symbol, direction=direction, minutes=minutes), True) for symbol in module.SYMBOLS})


def write_bars(path, rows, extra=()):
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(('code', 'time_key', 'open', 'high', 'low', 'close', 'volume', 'turnover'))
        for row in rows:
            writer.writerow((row.code, row.close_time.replace(tzinfo=None).isoformat(' '),
                             row.open, row.high, row.low, row.close, row.volume, 0))
        writer.writerows(extra)


class SignalTests(unittest.TestCase):
    def test_mirrored_measurements_preserve_original_state_and_first_event(self):
        for direction in ('LONG', 'SHORT'):
            rows = bars(direction=direction)
            originals, _ = module.detect_events(rows, levels())
            original = originals['G20_HOLD']
            saved = dict(original)
            reverse = module.reverse_event(original)
            sign = 1 if reverse['direction'] == 'LONG' else -1
            self.assertNotEqual(reverse['direction'], direction)
            self.assertEqual(reverse['original_direction'], direction)
            self.assertEqual(reverse['time'][11:16], '09:45')
            for key in ('reference', 'key_level', 'atr', 'gap_atr', 'rvol', 'activity_reason'):
                self.assertEqual(reverse[key], original[key])
            self.assertEqual(reverse['target'], reverse['reference'] + sign * 2)
            self.assertEqual(reverse['invalidation'], reverse['reference'] - sign)
            self.assertEqual(original, saved)
            self.assertEqual(module.reverse_event(module.detect_events(rows[:3], levels())[0]['G20_HOLD']), reverse)
        with self.assertRaises(ValueError):
            module.reverse_event(saved | {'candidate': 'B20_BREAK'})

    def test_later_failed_gap_cannot_retract_earlier_G(self):
        rows = bars(future=100)
        original = module.detect_events(rows[:3], levels())[0]['G20_HOLD']
        events, _ = module.detect_events(rows, levels())
        self.assertIsNotNone(events['F20_FAIL'])
        self.assertEqual(module.reverse_event(events['G20_HOLD']), module.reverse_event(original))

    def test_peers_match_original_drive_not_reversed_prediction_and_never_self(self):
        contexts, current = panel()
        current['XLY'] = (bars('XLY', direction='SHORT'), True)
        contexts['SPY'], current['SPY'] = levels('SPY'), (bars('SPY'), True)
        self.assertEqual(module.peer_names(event(), contexts, current), ['XLI'])
        # XLI may itself trigger G; that does not disqualify it as a peer.
        self.assertIsNotNone(module.detect_events(current['XLI'][0], contexts['XLI'])[0]['G20_HOLD'])
        contexts['XLI'] = levels('XLI') | {'previous_close': 104, 'mean_opening_volume': {15: None}}
        self.assertEqual(module.peer_names(event(), contexts, current), [])
        contexts['XLI'] = levels('XLI')
        current['XLI'] = (current['XLI'][0][1:], False)
        self.assertEqual(module.peer_names(event(), contexts, current), [])

    def test_missing_future_keeps_fixed_peer_list_and_complete_raw(self):
        contexts, current = panel()
        expected = ['XLI', 'XLY']
        self.assertEqual(module.peer_names(event(), contexts, current), expected)
        current['XLI'] = (current['XLI'][0][:8], False)
        with patch.object(module, 'evaluate_signal_quality', side_effect=AssertionError('future read')):
            self.assertEqual(module.peer_names(event(), contexts, current), expected)
        result = module.evaluate_event(event(), contexts, current)
        self.assertEqual(result['peers'], expected)
        self.assertIsNone(result['peer_returns'][0])
        self.assertIsNotNone(result['peer_returns'][1])
        self.assertEqual(result['label_status'], 'complete')
        self.assertEqual(result['paired_status'], 'missing')
        self.assertIsNone(result['paired_lift'])
        current['XLV'] = (current['XLV'][0][:8], False)
        result = module.evaluate_event(event(), contexts, current)
        self.assertEqual(result['peers'], expected)
        self.assertEqual(result['label_status'], 'missing_future')
        for key in ('return_30m', 'mfe_r', 'mae_r', 'path_status', 'paired_lift'):
            self.assertIsNone(result[key])

    def test_same_clock_mirrored_labels_and_absent_peer_are_explicit(self):
        for direction in ('LONG', 'SHORT'):
            contexts, current = panel(direction, minutes=20)
            rows = current['XLV'][0]
            reference, terminal = rows[3].close, rows[9].close
            altered = 107 if direction == 'LONG' else 93
            rows[8] = replace(rows[8], high=max(rows[8].high, altered),
                              low=min(rows[8].low, altered), close=altered)
            signal = event(direction=direction, minutes=20, rows=rows)
            result = module.evaluate_event(signal, contexts, current)
            sign = -1 if direction == 'LONG' else 1
            self.assertAlmostEqual(result['return_30m'], sign * (terminal / reference - 1))
            self.assertAlmostEqual(result['peer_returns'][0], result['return_30m'])
            self.assertAlmostEqual(result['paired_lift'], 0)
            self.assertEqual(result['paired_status'], 'complete')
            alone = module.evaluate_event(signal, {'XLV': contexts['XLV']}, current)
            self.assertEqual(alone['peers'], [])
            self.assertIsNone(alone['paired_lift'])

    def test_path_excludes_trigger_bar_and_zero_volume_is_flag_only(self):
        rows = bars()
        signal = event(rows=rows)
        original = module.evaluate_event(signal, {'XLV': levels()}, {'XLV': (rows, True)})
        rows[2] = replace(rows[2], high=200, low=1, volume=0)
        changed = module.evaluate_event(signal, {'XLV': levels()}, {'XLV': (rows, True)})
        self.assertEqual(original, changed)
        self.assertTrue(module.quality_flags(signal, rows, [])['reference_zero_volume'])
        rows[3] = replace(rows[3], high=107, low=102)
        self.assertEqual(module.evaluate_event(signal, {'XLV': levels()}, {'XLV': (rows, True)})['path_status'], 'ambiguous')


class InputTests(unittest.TestCase):
    def test_inputs_verify_only_three_price_files_and_all_authorized_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calendar = ('date,rows,first_close,last_close,missing_before_or_between\n'
                        + module.START + ',78,09:35:00,16:00:00,0\n'
                        + module.END + ',78,09:35:00,16:00:00,0\n')
            for symbol in (*module.SYMBOLS, 'DIA'):
                (root / ('US.' + symbol + '.coverage.csv')).write_text(calendar)
            price_pins = {}
            for symbol in module.SYMBOLS:
                path = root / ('US.' + symbol + '.csv')
                path.write_text('Deliberately invalid price rows: hash only, do not parse.\n')
                price_pins[symbol] = sha256_file(path)
            meta_sha = sha256_file(root / 'US.DIA.coverage.csv')
            lines = [sha256_file(path) + '  ' + path.name for path in sorted(root.iterdir())]
            # Nine unselected price entries need not even exist; no verification may open them.
            lines.extend('a' * 64 + '  US.' + symbol + '.csv' for symbol in
                         ('DIA', 'TLT', 'GLD', 'SLV', 'XLF', 'XLE', 'SMH', 'EEM', 'XLU'))
            checksum = root / 'CHECKSUMS.sha256'
            checksum.write_text('\n'.join(lines) + '\n')
            with patch.object(module, 'INPUT_SHA256', sha256_file(checksum)), \
                    patch.object(module, 'CALENDAR_SHA256', meta_sha), \
                    patch.object(module, 'PRICE_SHA256', price_pins), \
                    patch.object(module, 'sha256_file', wraps=sha256_file) as hashed:
                dates, identity = module.load_inputs(root)
                self.assertEqual(list(dates), [module.START, module.END])
                self.assertEqual(identity['symbols'], list(module.SYMBOLS))
                checked = {Path(call.args[0]).name for call in hashed.call_args_list}
                self.assertEqual({name for name in checked if name.endswith('.csv') and '.coverage.' not in name},
                                 {'US.XLV.csv', 'US.XLI.csv', 'US.XLY.csv'})
                (root / 'US.XLI.csv').write_text('changed')
                with self.assertRaisesRegex(ValueError, 'authorized input mismatch'):
                    module.load_inputs(root)

    def test_reader_stops_before_excluded_timestamp_code_or_price_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'US.XLV.csv'
            rows = bars(day=date.fromisoformat(module.END), count=1)
            tail = [('WRONG', '2026-09-25 NOT A TIME', 'invalid', '', '', '', '', '')]
            write_bars(path, rows, tail)
            with patch.object(module, 'Bar', wraps=Bar) as constructed:
                result = list(module.iter_sessions(path, 'XLV', {module.END: 78}))
            self.assertEqual(constructed.call_count, 1)
            self.assertEqual(result[0][0], module.END)
            self.assertEqual(result[0][2], [replace(row, source='opend_qfq_5m') for row in rows])
            self.assertFalse(result[0][3])
            with self.assertRaises(ValueError):
                list(module.iter_sessions(path, 'DIA', {module.END: 78}))

    def test_reader_half_day_grid_and_structural_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'US.XLV.csv'
            rows = bars(count=42)
            write_bars(path, rows)
            self.assertTrue(list(module.iter_sessions(path, 'XLV', {str(TODAY): 42}))[0][3])
            self.assertFalse(list(module.iter_sessions(path, 'XLV', {str(TODAY): 78}))[0][3])
            for bad in (rows + [rows[-1]], [replace(rows[0], code='US.XLY')], bars(count=79)):
                write_bars(path, bad)
                with self.assertRaises(ValueError):
                    list(module.iter_sessions(path, 'XLV', {str(TODAY): 78}))
            write_bars(path, rows)
            with self.assertRaisesRegex(ValueError, 'outside RG1 calendar'):
                list(module.iter_sessions(path, 'XLV', {}))

    def test_malformed_future_does_not_erase_known_signal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'US.XLV.csv'
            rows = bars(count=9)
            malformed = (rows[3].code, rows[3].close_time.replace(tzinfo=None).isoformat(' '),
                         'nan', 'nan', 'nan', 'nan', 1, 0)
            write_bars(path, rows[:3], [malformed])
            with path.open('a', newline='') as handle:
                writer = csv.writer(handle)
                for row in rows[4:]:
                    writer.writerow((row.code, row.close_time.replace(tzinfo=None).isoformat(' '),
                                     row.open, row.high, row.low, row.close, row.volume, 0))
            _, _, observed, complete = next(module.iter_sessions(path, 'XLV', {str(TODAY): 78}))
            original = module.detect_events(observed, levels())[0]['G20_HOLD']
            self.assertIsNotNone(original)
            self.assertFalse(complete)
            self.assertEqual(module.evaluate_signal_quality(observed, module.reverse_event(original))['label_status'], 'missing_future')


class SummaryTests(unittest.TestCase):
    def test_shared_bootstrap_zero_dates_single_candidate_quantile_and_missing_denominator(self):
        days = {'2022-12-30': {'n_sessions': 2, 'signals': 2, 'returns': [.01], 'paired': [.002]},
                '2023-01-03': {'n_sessions': 2, 'signals': 2, 'returns': [-.03, .01], 'paired': [-.004, .002]},
                '2023-01-04': module.day_record()}
        first, second, zero = (.01, 1, .002, 1), (-.02, 2, -.002, 2), (0, 0, 0, 0)
        rng = Mock()
        rng.choice.side_effect = [first] * 3 + [second] * 3 + [zero] * 3 + [first, second, zero]
        with patch.object(module.random, 'Random', return_value=rng) as seeded, \
                patch.object(module, 'quantile', wraps=module.quantile) as quantile:
            result = module.summarize(days, draws=4)
        seeded.assert_called_once_with(20260926)
        self.assertEqual(rng.choice.call_count, 12)
        self.assertTrue(all(len(call.args[0]) == 3 for call in rng.choice.call_args_list))
        raw, paired = quantile.call_args_list
        self.assertEqual((raw.args[1], paired.args[1]), (.05, .05))
        self.assertAlmostEqual(result['raw_lower_95_bp'], -100 + (200 / 3) * .1)
        self.assertAlmostEqual(result['paired_lower_95_bp'], -9)
        self.assertEqual(result['bootstrap']['undefined_raw_draws'], 1)
        self.assertEqual(result['bootstrap']['undefined_paired_draws'], 1)
        self.assertEqual(result['paired_coverage'], .75)
        self.assertEqual(result['missing_labels'], 1)
        self.assertEqual(result['n_dates'], 3)
        self.assertEqual(result['halves']['before_2023_01_01']['labeled_signals'], 1)
        self.assertEqual(result['halves']['from_2023_01_01']['labeled_signals'], 2)

    def test_gates_require_all_thresholds_and_handle_zero_and_no_losses(self):
        days = {}
        for index in range(60):
            day = date(2022, 12, 1) + timedelta(days=index)
            count = 2 if index < 40 else 1
            days[str(day)] = {'n_sessions': 3, 'signals': count,
                              'returns': [.001] * count, 'paired': [.0001] * count}
        result = module.summarize(days, draws=20)
        self.assertEqual(result['labeled_signals'], 100)
        self.assertIsNone(result['profit_factor'])
        self.assertTrue(result['asset_transfer_eligible'])
        for day in list(days)[:10]:
            days[day]['paired'] = []
        self.assertTrue(module.summarize(days, draws=20)['asset_transfer_eligible'])
        days[next(iter(days))]['signals'] += 1  # Missing raw counts in the paired denominator too.
        self.assertFalse(module.summarize(days, draws=20)['gates']['paired_coverage_at_least_80pct'])
        zeros = {'2023-01-03': {'n_sessions': 3, 'signals': 1, 'returns': [0], 'paired': [0]}}
        result = module.summarize(zeros, draws=5)
        self.assertFalse(result['asset_transfer_eligible'])
        self.assertFalse(result['gates']['profit_factor_at_least_1_2'])
        self.assertFalse(result['gates']['both_halves_positive'])
        empty = module.summarize({'2023-01-03': module.day_record()}, draws=5)
        self.assertIsNone(empty['raw_lower_95_bp'])
        self.assertEqual(empty['bootstrap']['undefined_raw_draws'], 5)
        self.assertFalse(empty['asset_transfer_eligible'])


class ReplayTests(unittest.TestCase):
    def test_stream_history_causal_missing_day_clears_and_only_G_is_labeled(self):
        dates = [date(2022, 12, 1) + timedelta(days=index) for index in range(23)]
        calendar = {str(day): 42 if index == 5 else 78 for index, day in enumerate(dates)}
        streams = {}
        for symbol in module.SYMBOLS:
            streams[symbol] = [(str(day), symbol,
                                bars(symbol, day, calendar[str(day)], quiet=index != 20), True)
                               for index, day in enumerate(dates) if not (symbol == 'XLV' and index == 21)]
        seen = []
        def causal_context(history, opening, today):
            self.assertEqual(len(history), 20)
            self.assertEqual(len(opening), 20)
            self.assertTrue(all(row.close_time.date() < today for row in history))
            seen.append((history[0].code, today))
            return real_context(history, opening, today)
        real_context, real_summary = module.context, module.summarize
        emitted = []
        with patch.object(module, 'load_inputs', return_value=(calendar, {'synthetic': True})), \
                patch.object(module, 'iter_sessions', side_effect=lambda path, symbol, cal: iter(streams[symbol])), \
                patch.object(module, 'context', side_effect=causal_context), \
                patch.object(module, 'summarize', wraps=lambda days: real_summary(days, draws=10)):
            result = module.replay(Path('/synthetic-only'), emitted.append)
        self.assertEqual(set(result['candidates']), {'G20_REVERSE'})
        self.assertEqual(len(emitted), 3)
        self.assertTrue(all(row['candidate'] == 'G20_REVERSE' and row['original_direction'] == 'LONG'
                            and row['direction'] == 'SHORT' for row in emitted))
        self.assertEqual(result['coverage_by_symbol']['XLV']['missing_day'], 1)
        self.assertNotIn(('US.XLV', dates[22]), seen)
        self.assertEqual(result['by_day'][str(dates[0])]['signals'], 0)
        self.assertEqual(len(result['by_day']), 23)
        self.assertTrue(all('/' in key for key in result['code_sha256']))
        self.assertIn('studies/us_opening_range/event_replay.py', result['code_sha256'])

    def test_cli_refuses_existing_or_equal_outputs_before_any_data_access(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / 'existing.json'
            existing.write_text('preserve')
            for report, events in ((existing, root / 'new.jsonl'), (root / 'new.json', existing),
                                   (root / 'same', root / 'same')):
                with patch.object(module, 'replay', side_effect=AssertionError('must not read')):
                    with self.assertRaises(SystemExit):
                        module.main(['--out', str(report), '--signals-out', str(events)])
            self.assertEqual(existing.read_text(), 'preserve')


if __name__ == '__main__':
    unittest.main()
