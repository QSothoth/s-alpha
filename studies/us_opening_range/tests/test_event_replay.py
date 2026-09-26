"""Synthetic DS2 black-box checks; no historical files, APIs or real labels."""
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from custody.marketdata import Bar
from custody.models import ET
from studies.us_opening_range import event_replay as module


TODAY = date(2024, 3, 18)


def bars(symbol='QQQ', direction='LONG', minutes=15, day=TODAY, count=12,
         future_close=None, volume=20):
    opening = datetime.combine(day, time(9, 30), ET)
    sign = 1 if direction == 'LONG' else -1
    rows, previous = [], 100
    for index in range(count):
        close = 100 + sign if index < minutes // 5 else (
            future_close if future_close is not None else 100 + 2 * sign)
        rows.append(Bar('US.' + symbol, opening + timedelta(minutes=5 * (index + 1)),
                        previous, max(previous, close) + .1, min(previous, close) - .1,
                        close, volume, '5m'))
        previous = close
    return rows


def levels(symbol='QQQ', day=TODAY):
    return {'symbol': 'US.' + symbol, 'trade_date': day.isoformat(), 'atr': 4,
            'previous_close': 100, 'range_high20': 102, 'range_low20': 98,
            'mean_opening_volume': {15: 30, 20: 40, 30: 60}}


def event(symbol='QQQ', direction='LONG', minutes=15, rows=None):
    rows = rows if rows is not None else bars(symbol, direction, minutes)
    signal = module.measurement_signal(rows[:minutes // 5], levels(symbol), direction)
    return signal | {'candidate': 'B20_BREAK', 'snapshot_minutes': minutes}


def current_for(*symbols, direction='LONG', minutes=15):
    return ({symbol: levels(symbol) for symbol in symbols},
            {symbol: (bars(symbol, direction, minutes), True) for symbol in symbols})


class PeerTests(unittest.TestCase):
    def test_peer_names_ignore_future_prices_labels_and_afternoon_completeness(self):
        contexts, current = current_for('QQQ', 'SPY', 'IWM')
        signal = event()
        expected = ['IWM', 'SPY']
        self.assertEqual(module.peer_names(signal, contexts, current), expected)
        changed = dict(current)
        changed['SPY'] = (current['SPY'][0][:3], False)
        changed['IWM'] = (current['IWM'][0][:3] + [replace(bar, low=0, code='US.BAD')
                                                 for bar in current['IWM'][0][3:]], False)
        with patch.object(module, 'evaluate_signal_quality', side_effect=AssertionError('lookahead')):
            self.assertEqual(module.peer_names(signal, contexts, changed), expected)

    def test_peer_self_group_prefix_activity_and_direction_are_respected(self):
        contexts, current = current_for('QQQ', 'SPY', 'IWM', 'AAPL', 'SMALL')
        current['IWM'] = (bars('IWM', 'SHORT'), True)
        self.assertEqual(module.peer_names(event(), contexts, current), ['SPY'])
        current['SPY'] = (bars('SPY', volume=1), True)
        self.assertEqual(module.peer_names(event(), contexts, current), [])
        current['SPY'] = (bars('SPY')[1:], True)
        self.assertEqual(module.peer_names(event(), contexts, current), [])
        contexts, current = current_for('AAPL', 'MSFT', 'SMALL', 'OTHER')
        self.assertEqual(module.peer_names(event('AAPL'), contexts, current), ['MSFT'])
        self.assertEqual(module.peer_names(event('SMALL'), contexts, current), ['OTHER'])

    def test_one_missing_peer_keeps_whole_frozen_list_and_raw_label(self):
        contexts, current = current_for('QQQ', 'SPY', 'IWM')
        current['IWM'] = (current['IWM'][0][:8], False)
        result = module.evaluate_event(event(), contexts, current)
        self.assertEqual(result['peers'], ['IWM', 'SPY'])
        self.assertIsNone(result['peer_returns'][0])
        self.assertIsNotNone(result['peer_returns'][1])
        self.assertEqual(result['label_status'], 'complete')
        self.assertEqual(result['paired_status'], 'missing')
        self.assertIsNone(result['paired_lift'])
        current['QQQ'] = (current['QQQ'][0][:8], False)
        result = module.evaluate_event(event(), contexts, current)
        self.assertEqual(result['peers'], ['IWM', 'SPY'])
        self.assertEqual(result['label_status'], 'missing_future')
        self.assertIsNone(result['return_30m'])
        self.assertIsNone(result['paired_lift'])

    def test_peer_and_spy_measure_the_same_clock_and_mirrored_direction(self):
        for direction, reference, final in [('LONG', 101, 104), ('SHORT', 99, 96)]:
            with self.subTest(direction=direction):
                contexts, current = current_for('QQQ', 'SPY', direction=direction, minutes=20)
                current['QQQ'] = (bars('QQQ', direction, 20, future_close=final), True)
                # 10:15 differs from 10:20: reusing the 09:45 label would fail.
                earlier = 105 if direction == 'LONG' else 95
                current['QQQ'][0][8] = replace(current['QQQ'][0][8], high=max(final, earlier) + .1,
                                                low=min(final, earlier) - .1, close=earlier)
                # Benchmark activity is not required; it stays a clock-matched description.
                current['SPY'] = (bars('SPY', direction, 20, volume=0), True)
                signal = event('QQQ', direction, 20, current['QQQ'][0])
                result = module.evaluate_event(signal, contexts, current)
                sign = 1 if direction == 'LONG' else -1
                expected_raw = sign * (final / reference - 1)
                expected_spy = sign * ((102 if sign == 1 else 98) / reference - 1)
                self.assertAlmostEqual(result['return_30m'], expected_raw)
                self.assertAlmostEqual(result['spy_signed_return'], expected_spy)
                self.assertAlmostEqual(result['spy_beta1_difference'], expected_raw - expected_spy)
                self.assertEqual(result['peers'], [])
                current['SPY'] = (bars('SPY', direction, 20), True)
                result = module.evaluate_event(signal, contexts, current)
                self.assertEqual(result['peers'], ['SPY'])
                self.assertAlmostEqual(result['peer_returns'][0], expected_spy)
                self.assertAlmostEqual(result['paired_lift'], expected_raw - expected_spy)

    def test_failed_gap_peers_follow_reversal_direction_not_original_gap_sign(self):
        contexts, current = current_for('QQQ', 'SPY', 'IWM')
        own = current['QQQ'][0]
        own[0] = replace(own[0], open=103, high=103.1)
        current['SPY'] = (bars('SPY', 'SHORT'), True)
        signal = event('QQQ', 'SHORT', rows=own) | {'candidate': 'F20_FAIL', 'gap_atr': .75}
        self.assertEqual(module.peer_names(signal, contexts, current), ['SPY'])
        result = module.evaluate_event(signal, contexts, current)
        self.assertEqual(result['peers'], ['SPY'])
        self.assertAlmostEqual(result['return_30m'], -(102 / 101 - 1))
        self.assertAlmostEqual(result['peer_returns'][0], -(98 / 99 - 1))

    def test_spy_self_is_not_zero_and_no_peer_never_becomes_zero_lift(self):
        contexts, current = current_for('SPY')
        result = module.evaluate_event(event('SPY'), contexts, current)
        self.assertEqual(result['label_status'], 'complete')
        self.assertIsNone(result['spy_signed_return'])
        self.assertIsNone(result['spy_beta1_difference'])
        self.assertEqual(result['paired_status'], 'missing')
        self.assertIsNone(result['paired_lift'])

    def test_quality_flags_only_read_prefix_and_record_history_without_mutation(self):
        rows = bars()
        rows[0] = replace(rows[0], volume=0)
        rows[2] = replace(rows[2], open=101, high=101, low=101, close=101, volume=0)
        history = [[replace(bar, volume=0) for bar in bars(day=TODAY - timedelta(days=1))[:6]]]
        signal, original_history = event(rows=rows), [list(history[0])]
        expected = {'zero_volume_prefix_bars': 2, 'flat_zero_volume_prefix_bars': 1,
                    'reference_zero_volume': True, 'historical_opening_zero_volume_bars': 6}
        self.assertEqual(module.quality_flags(signal, rows, history), expected)
        changed = rows[:3] + [replace(bar, open=1, high=1, low=1, close=1, volume=0) for bar in rows[3:]]
        self.assertEqual(module.quality_flags(signal, changed, history), expected)
        self.assertEqual(history, original_history)
        self.assertEqual(signal, event(rows=rows))


class SummaryTests(unittest.TestCase):
    def test_missing_labels_zero_dates_halves_and_conservative_paired_denominator(self):
        days = {'2021-01-04': {'n_sessions': 5, 'signals': 3, 'returns': [.01, -.005], 'paired': [.002]},
                '2023-01-04': {'n_sessions': 5, 'signals': 1, 'returns': [0], 'paired': [0]},
                '2023-01-05': {'n_sessions': 5, 'signals': 0, 'returns': [], 'paired': []}}
        result = module.summarize(days, draws=20)
        self.assertEqual((result['n_dates'], result['active_dates'], result['signals']), (3, 2, 4))
        self.assertEqual((result['labeled_signals'], result['missing_labels'], result['paired_labels']), (3, 1, 2))
        self.assertEqual(result['paired_coverage'], .5)
        self.assertEqual(result['win_rate'], 1 / 3)
        self.assertEqual(result['payoff_ratio'], 2)
        self.assertAlmostEqual(result['signals_per_100_sessions'], 400 / 15)
        self.assertEqual(result['halves']['before_2022_06_01']['labeled_signals'], 2)
        self.assertEqual(result['halves']['from_2022_06_01']['labeled_signals'], 1)
        self.assertFalse(result['development_eligible'])
        self.assertEqual(module.summarize(days, draws=20), result)

    def test_raw_and_paired_bootstrap_share_draws_and_include_zero_signal_dates(self):
        days = {'2021-01-04': {'n_sessions': 2, 'signals': 1, 'returns': [.01], 'paired': [.002]},
                '2023-01-04': {'n_sessions': 2, 'signals': 2, 'returns': [-.03, .01], 'paired': [-.004, .002]},
                '2023-01-05': {'n_sessions': 2, 'signals': 0, 'returns': [], 'paired': []}}
        first, second, zero = (.01, 1, .002, 1), (-.02, 2, -.002, 2), (0, 0, 0, 0)
        rng = Mock()
        rng.choice.side_effect = [first] * 3 + [second] * 3 + [zero] * 3 + [first, second, zero]
        with patch.object(module.random, 'Random', return_value=rng) as seeded, \
                patch.object(module, 'quantile', wraps=module.quantile) as quantile:
            result = module.summarize(days, draws=4)
        seeded.assert_called_once_with(20260926)
        self.assertEqual(rng.choice.call_count, 12)  # Not separately redrawn for paired labels.
        for call in rng.choice.call_args_list:
            self.assertEqual(len(call.args[0]), 3)
            self.assertEqual(call.args[0][-1], zero)
        raw, paired = quantile.call_args_list
        self.assertEqual(raw.args[1], .05 / 3)
        self.assertEqual(paired.args[1], .05)
        for actual, expected in zip(raw.args[0], (100, -100, -100 / 3)):
            self.assertAlmostEqual(actual, expected)
        for actual, expected in zip(paired.args[0], (20, -10, 0)):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(result['bootstrap']['undefined_raw_draws'], 1)
        self.assertEqual(result['bootstrap']['undefined_paired_draws'], 1)
        self.assertAlmostEqual(result['raw_simultaneous_lower_bp'], -100 + (200 / 3) / 30)
        self.assertAlmostEqual(result['paired_lower_95_bp'], -9)

    def test_quantiles_are_linear_bonferroni_and_empty_population_is_explicit(self):
        values = [180, 0, 120, 60]
        self.assertAlmostEqual(module.quantile(values, .05 / 3), 3)
        self.assertAlmostEqual(module.quantile(values, .05), 9)
        self.assertEqual(values, [180, 0, 120, 60])
        self.assertIsNone(module.quantile([], .05))
        result = module.summarize({'2023-01-04': module.day_record()}, draws=10)
        self.assertEqual(result['signals'], 0)
        self.assertEqual(result['paired_coverage'], 0)
        self.assertIsNone(result['raw_simultaneous_lower_bp'])
        self.assertIsNone(result['paired_lower_95_bp'])
        self.assertEqual(result['bootstrap']['undefined_raw_draws'], 10)
        self.assertEqual(result['bootstrap']['undefined_paired_draws'], 10)
        self.assertFalse(result['development_eligible'])


class ReplayTests(unittest.TestCase):
    def test_calendar_gap_clears_both_histories_and_incomplete_day_keeps_early_event(self):
        dates, day = [], date(2020, 1, 2)
        while len(dates) < 46:
            if day.weekday() < 5:
                dates.append(day)
            day += timedelta(days=1)
        calendar = {day.isoformat(): 42 if index == 5 else 78 for index, day in enumerate(dates)}
        stream = []
        for index, day in enumerate(dates):
            if index == 21:
                continue  # The calendar supplies a day missing from the entire pool.
            count = 9 if index == 42 else calendar[day.isoformat()]
            rows = bars('SPY', day=day, count=count, volume=20 if index in (20, 42) else 1)
            if index not in (20, 42):
                rows = [replace(bar, open=100, high=100.1, low=99.9, close=100) for bar in rows]
                rows[0] = replace(rows[0], volume=0)
            else:
                rows[2] = replace(rows[2], open=101, high=101, low=101, close=101, volume=0)
            stream.append((day.isoformat(), 'SPY', rows, index != 42))
        contexts, emitted = [], []
        real_context = module.context

        def checked_context(daily, opening, today):
            contexts.append(today)
            self.assertEqual((len(daily), len(opening)), (20, 20))
            self.assertTrue(all(bar.close_time.date() < today for bar in daily))
            self.assertTrue(all(rows[0].close_time.date() < today for rows in opening))
            self.assertTrue(all(len(rows) == 6 for rows in opening))
            self.assertEqual(daily[-1].close, 100)  # Today's event close is not historical input.
            if today == dates[20]:
                self.assertEqual(daily[5].close_time.hour, 13)
            return real_context(daily, opening, today)

        def digest(path):
            return module.PREREG_SHA256 if Path(path).name == 'DS2_PREREG.md' else module.INPUT_SHA256

        with patch.object(module, 'SYMBOLS', ('SPY',)), \
                patch.object(module, 'sha256_file', side_effect=digest), \
                patch.object(module, 'verify_inputs', return_value={}), \
                patch.object(module, 'verify_small', return_value=([], {'missing': ['TEM']})), \
                patch.object(module, 'read_calendar', return_value=calendar), \
                patch.object(module, 'iter_sessions', return_value=iter(stream)), \
                patch.object(module, 'context', side_effect=checked_context):
            result = module.replay(Path('/synthetic-large'), Path('/synthetic-small'), emit=emitted.append)
        self.assertEqual(contexts, [dates[20], dates[42]])
        self.assertEqual([row['time'][:10] for row in emitted], [dates[20].isoformat(), dates[42].isoformat()])
        self.assertTrue(all(row['label_status'] == 'complete' for row in emitted))
        self.assertTrue(all(row['data_quality']['reference_zero_volume'] for row in emitted))
        self.assertTrue(all(row['data_quality']['historical_opening_zero_volume_bars'] == 20 for row in emitted))
        self.assertEqual(result['coverage_by_symbol']['SPY']['missing_day'], 1)
        self.assertEqual(result['coverage_by_symbol']['SPY']['incomplete_days'], 1)
        self.assertEqual(result['coverage_by_symbol']['SPY']['history_eligible_days'], 2)
        summary = result['candidates']['B20_BREAK']
        self.assertEqual((summary['n_dates'], summary['eligible_sessions'], summary['signals']), (46, 2, 2))
        self.assertEqual(summary['paired_coverage'], 0)
        self.assertEqual(summary['quality_flag_counts']['reference_zero_volume_signals'], 2)
        self.assertEqual(summary['quality_flag_counts']['historical_opening_zero_volume_bars_signals'], 2)
        self.assertEqual(result['by_day']['B20_BREAK'][dates[21].isoformat()], module.day_record())
        self.assertIsNone(result['selected_for_migration'])

    def test_bad_fingerprint_aborts_before_input_or_label_access(self):
        with patch.object(module, 'sha256_file', return_value='wrong'), \
                patch.object(module, 'iter_sessions') as reader, \
                patch.object(module, 'evaluate_event') as labels, self.assertRaises(ValueError):
            module.replay(Path('/synthetic-large'), Path('/synthetic-small'))
        reader.assert_not_called()
        labels.assert_not_called()

    def test_existing_report_or_events_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            out, events = Path(directory) / 'report.json', Path(directory) / 'events.jsonl'
            for occupied in (out, events):
                occupied.write_text('unchanged', encoding='utf-8')
                with patch('sys.argv', ['event_replay', '--out', str(out), '--signals-out', str(events)]), \
                        patch.object(module, 'replay') as replay, self.assertRaises(SystemExit):
                    module.main()
                replay.assert_not_called()
                self.assertEqual(occupied.read_text(encoding='utf-8'), 'unchanged')
                occupied.unlink()


if __name__ == '__main__':
    unittest.main()
