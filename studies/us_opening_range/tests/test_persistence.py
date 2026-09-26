"""Synthetic fixed-event persistence labels and pinning; never read real reports."""
from contextlib import ExitStack
from dataclasses import replace
from datetime import date, datetime, time, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from custody.marketdata import Bar
from custody.models import ET
from studies.us_opening_range import persistence as module


TODAY = date(2024, 3, 18)


def bars(symbol='SPY', count=78, prices=None):
    opening = datetime.combine(TODAY, time(9, 30), ET)
    path = {3: 101, 4: 99, 8: 102, 14: 103, count - 1: 101} if prices is None else prices
    result, previous = [], 100
    for index in range(count):
        close = path.get(index, 100)
        result.append(Bar('US.' + symbol, opening + timedelta(minutes=5 * (index + 1)),
                          previous, max(previous, close) + .25, min(previous, close) - .25,
                          close, 10, '5m'))
        previous = close
    return result


def frozen_event(rows, study='DS1', candidate=None, peers=(), current=None, direction='LONG'):
    candidate = candidate or ('PD_BREAK' if study == 'DS1' else 'B20_BREAK')
    sign, reference = (1 if direction == 'LONG' else -1), rows[2].close
    event = {'symbol': rows[0].code, 'time': rows[2].close_time.isoformat(), 'candidate': candidate,
             'direction': direction, 'reference': reference, 'atr': 4, 'risk': 1,
             'target': reference + 2 * sign, 'invalidation': reference - sign,
             'snapshot_minutes': 15, 'origin_study': study}
    event.update(module.evaluate_signal_quality(rows, event))
    if study == 'DS2':
        values = []
        for peer in peers:
            peer_rows = current[peer]
            peer_event = event | {'symbol': 'US.' + peer, 'reference': peer_rows[2].close}
            values.append(module.evaluate_signal_quality(peer_rows, peer_event)['return_30m'])
        complete = bool(values) and event['return_30m'] is not None and all(value is not None for value in values)
        event.update(peers=list(peers), peer_returns=values, paired_status='complete' if complete else 'missing',
                     paired_lift=event['return_30m'] - sum(values) / len(values) if complete else None)
    return event


class PathTests(unittest.TestCase):
    def test_exact_three_horizons_original_reference_and_common_increments(self):
        rows = bars()
        event = frozen_event(rows)
        out = module.label_event(event, {'SPY': rows}, 78)
        self.assertTrue(out['common_complete'])
        for name, expected in [('30m', .02), ('60m', .03), ('close', .01)]:
            self.assertAlmostEqual(out['horizons'][name]['return'], expected)
            self.assertEqual(out['horizons'][name]['paired_status'], 'not_applicable')
            self.assertIsNone(out['horizons'][name]['paired_lift'])
        self.assertAlmostEqual(out['horizons']['30m']['direction_efficiency'], 2 / 6)
        self.assertAlmostEqual(out['horizons']['30m']['mfe_atr'], 2.25 / 4)
        self.assertAlmostEqual(out['horizons']['30m']['mae_atr'], 1.25 / 4)
        self.assertAlmostEqual(out['increments']['30_to_60']['return'], .01)
        self.assertAlmostEqual(out['increments']['60_to_close']['return'], -.02)
        self.assertEqual(out['increments']['30_to_60']['return_atr'], .25)
        self.assertEqual(out['increments']['60_to_close']['return_atr'], -.5)

    def test_signal_bar_excluded_and_atr_excursions_do_not_compare_study_r(self):
        rows = bars()
        rows[2] = replace(rows[2], high=1000, low=1)
        event = frozen_event(rows)
        event.update(risk=2, target=104, invalidation=98)
        event.update(module.evaluate_signal_quality(rows, event))
        result = module.label_event(event, {'SPY': rows}, 78)
        self.assertAlmostEqual(result['horizons']['30m']['mfe_atr'], .5625)
        self.assertAlmostEqual(result['horizons']['30m']['mae_atr'], .3125)

    def test_missing_later_path_preserves_short_label_and_all_fixed_peers(self):
        current = {symbol: bars(symbol) for symbol in ('SPY', 'QQQ', 'IWM')}
        original = frozen_event(current['SPY'], 'DS2', peers=('QQQ', 'IWM'), current=current)
        current['IWM'] = current['IWM'][:10] + current['IWM'][11:]
        out = module.label_event(original, current, 78)
        self.assertEqual(out['peers'], ['QQQ', 'IWM'])
        self.assertEqual(out['horizons']['30m']['paired_status'], 'complete')
        for name in ('60m', 'close'):
            self.assertEqual(out['horizons'][name]['status'], 'complete')
            self.assertEqual(out['horizons'][name]['paired_status'], 'missing')
            self.assertIsNotNone(out['horizons'][name]['peer_returns'][0])
            self.assertIsNone(out['horizons'][name]['peer_returns'][1])
            self.assertIsNone(out['horizons'][name]['paired_lift'])
        current['SPY'] = current['SPY'][:10] + current['SPY'][11:]
        out = module.label_event(original, current, 78)
        self.assertEqual(out['horizons']['30m']['status'], 'complete')
        self.assertFalse(out['common_complete'])
        self.assertEqual(out['increments'], {})
        for name in ('60m', 'close'):
            label = out['horizons'][name]
            self.assertEqual(label['status'], 'missing_future')
            for key in ('return', 'mfe_atr', 'mae_atr', 'direction_efficiency', 'zero_volume_bars'):
                self.assertIsNone(label[key])

    def test_half_day_calendar_close_and_future_beyond_end_are_not_used(self):
        rows = bars(count=42)
        event = frozen_event(rows)
        out = module.label_event(event, {'SPY': rows}, 42)
        close = out['horizons']['close']
        self.assertEqual(datetime.fromisoformat(close['end_time']).hour, 13)
        self.assertEqual(close['minutes'], 195)
        self.assertEqual(close['status'], 'complete')
        normal = module.label_event(event, {'SPY': rows}, 78)
        self.assertEqual(normal['horizons']['close']['status'], 'missing_future')
        longer = rows + [replace(rows[-1], close_time=rows[-1].close_time + timedelta(minutes=5),
                                  open=1, high=1, low=1, close=1, volume=0)]
        self.assertEqual(module.label_event(event, {'SPY': longer}, 42)['horizons'], out['horizons'])
        with self.assertRaises(ValueError):
            module.label_event(event, {'SPY': rows}, 43)

    def test_flat_zero_volume_paths_retained_with_undefined_efficiency(self):
        rows = [replace(bar, open=100, high=100, low=100, close=100, volume=0) for bar in bars(prices={})]
        out = module.label_event(frozen_event(rows), {'SPY': rows}, 78)
        for name, count in [('30m', 6), ('60m', 12), ('close', 75)]:
            label = out['horizons'][name]
            self.assertEqual(label['status'], 'complete')
            self.assertEqual(label['return'], 0)
            self.assertEqual(label['mfe_atr'], 0)
            self.assertEqual(label['mae_atr'], 0)
            self.assertEqual(label['zero_volume_bars'], count)
            self.assertIsNone(label['direction_efficiency'])

    def test_short_mirror_and_duplicate_or_missing_future(self):
        rows = bars()
        mirrored = [replace(bar, open=200 - bar.open, high=200 - bar.low,
                            low=200 - bar.high, close=200 - bar.close) for bar in rows]
        long = module.label_event(frozen_event(rows), {'SPY': rows}, 78)
        short = module.label_event(frozen_event(mirrored, direction='SHORT'), {'SPY': mirrored}, 78)
        for horizon in module.HORIZONS:
            for key in ('return', 'return_atr', 'mfe_atr', 'mae_atr', 'direction_efficiency'):
                self.assertAlmostEqual(long['horizons'][horizon][key], short['horizons'][horizon][key])
        for changed in (rows[:4] + rows[5:], rows[:4] + rows[3:4] + rows[4:]):
            event = frozen_event(changed)
            out = module.label_event(event, {'SPY': changed}, 78)
            self.assertTrue(all(row['status'] == 'missing_future' for row in out['horizons'].values()))

    def test_original_labels_peer_returns_and_reference_must_reconcile(self):
        current = {symbol: bars(symbol) for symbol in ('SPY', 'QQQ')}
        event = frozen_event(current['SPY'], 'DS2', peers=('QQQ',), current=current)
        mutations = [{'return_30m': event['return_30m'] + 1e-8}, {'mfe_r': event['mfe_r'] + 1e-8},
                     {'path_status': 'ambiguous'}, {'label_status': 'missing_future'},
                     {'paired_lift': .1}, {'peer_returns': [.1]}, {'reference': 100.1}]
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, 'reconcile|reference'):
                module.label_event(event | mutation, current, 78)
        module.label_event(event | {'return_30m': event['return_30m'] + 5e-13}, current, 78)


class InputAndReplayTests(unittest.TestCase):
    def test_event_reader_filters_only_registered_ds1_subsets_and_rejects_duplicates(self):
        event = frozen_event(bars())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'events.jsonl'
            path.write_text('\n'.join(json.dumps(event | {'candidate': name}) for name in
                                     ('PD_BREAK', 'NR7_BREAK', 'INSIDE_BREAK')) + '\n', encoding='utf-8')
            output = list(module.iter_events(path, 'DS1', ('SPY',)))
            self.assertEqual(len(output), 1)
            self.assertEqual(output[0][1]['candidate'], 'PD_BREAK')
            path.write_text(json.dumps(event) + '\n' + json.dumps(event) + '\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                list(module.iter_events(path, 'DS1', ('SPY',)))
            path.write_text(json.dumps(event | {'time': '2024-06-03T09:45:00-04:00'}) + '\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                list(module.iter_events(path, 'DS1', ('SPY',)))

    def test_input_artifact_source_code_and_source_tape_pins_are_all_enforced(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            base = Path(directory)
            ds1, ds2, report_path = base / 'ds1.jsonl', base / 'ds2.jsonl', base / 'report.json'
            source = dict(module.SOURCE_PINS, **{'custody/models.py': 'dependency'})
            inputs = {'large': {'source': 'large'}, 'smallmid': {'source': 'small'},
                      'calendar_metadata_sha256': module.CALENDAR_SHA256}
            report = {'study': 'DS2', 'preregistration_sha256': module.DS2_PREREG_SHA256,
                      'signals_artifact': {'path': str(ds2), 'sha256': module.DS2_SHA256},
                      'code_sha256': source, 'inputs': inputs}
            pins = {str(ds1): module.DS1_SHA256, str(ds2): module.DS2_SHA256,
                    str(report_path): module.DS2_REPORT_SHA256,
                    'PERSISTENCE_PREREG.md': module.PREREG_SHA256,
                    'DS2_PREREG.md': module.DS2_PREREG_SHA256, 'CHECKSUMS.sha256': module.INPUT_SHA256}
            pins.update({str((module.REPO / name).resolve()): digest for name, digest in source.items()})
            stack.enter_context(patch.object(module, 'sha256_file', side_effect=lambda path: pins.get(str(path), pins.get(Path(path).name))))
            stack.enter_context(patch.object(module, 'verify_inputs', return_value=inputs['large']))
            stack.enter_context(patch.object(module, 'verify_small', return_value=(['SMALL'], inputs['smallmid'])))
            stack.enter_context(patch.object(module, 'read_calendar', return_value={TODAY.isoformat(): 78}))
            report_path.write_text(json.dumps(report), encoding='utf-8')
            args = (base / 'large', base / 'small', base / 'calendar', ds1, ds2, report_path)
            self.assertEqual(module.load_inputs(*args)[2]['ds2_events_sha256'], module.DS2_SHA256)
            for key in (str(ds1), str(ds2), str(report_path), str(module.REPO / 'custody/models.py')):
                before = pins[key]
                pins[key] = 'wrong'
                with self.subTest(pin=key), self.assertRaises(ValueError):
                    module.load_inputs(*args)
                pins[key] = before
            for changed in (report | {'preregistration_sha256': 'wrong'},
                            report | {'signals_artifact': {'path': str(ds2), 'sha256': 'wrong'}},
                            report | {'code_sha256': source | {next(iter(module.SOURCE_PINS)): 'wrong'}},
                            report | {'inputs': inputs | {'large': {'source': 'different'}}}):
                report_path.write_text(json.dumps(changed), encoding='utf-8')
                with self.assertRaises(ValueError):
                    module.load_inputs(*args)

    def test_stream_report_keeps_all_four_classes_zero_dates_and_endpoint_flips(self):
        current = {'SPY': bars(prices={8: 102, 14: 103, 77: 98}), 'QQQ': bars('QQQ')}
        ds1_event = frozen_event(current['SPY'])
        ds2_events = [frozen_event(current['SPY'], 'DS2', name, ('QQQ',), current) for name in module.CLASSES[1:]]
        calendar = {TODAY.isoformat(): 78, (TODAY + timedelta(days=1)).isoformat(): 78}
        emitted = []
        with tempfile.TemporaryDirectory() as directory:
            ds1, ds2 = Path(directory) / 'ds1.jsonl', Path(directory) / 'ds2.jsonl'
            ds1.write_text(json.dumps(ds1_event) + '\n', encoding='utf-8')
            ds2.write_text(''.join(json.dumps(event) + '\n' for event in ds2_events), encoding='utf-8')

            def stream(path, symbol, days):
                yield TODAY.isoformat(), symbol, current[symbol], True

            with patch.object(module, 'SYMBOLS', ('SPY', 'QQQ')), \
                    patch.object(module, 'load_inputs', return_value=(('SPY', 'QQQ'), calendar, {}, {})), \
                    patch.object(module, 'iter_sessions', side_effect=stream), \
                    patch('studies.us_opening_range.daily_signals.detect_signals', side_effect=AssertionError('re-detect')), \
                    patch('studies.us_opening_range.event_signals.detect_events', side_effect=AssertionError('re-detect')):
                result = module.replay(Path('/synthetic-large'), Path('/synthetic-small'),
                                       ds1_events=ds1, ds2_events=ds2, emit=emitted.append)
        self.assertEqual(result['status'], 'DESCRIPTIVE_ONLY_NO_SELECTION')
        self.assertEqual(tuple(result['classes']), module.CLASSES)
        self.assertEqual(len(emitted), 4)
        for name in module.CLASSES:
            self.assertEqual(tuple(result['classes'][name]), module.HORIZONS)
            for label in result['classes'][name].values():
                self.assertEqual((label['signals'], label['valid'], label['missing']), (1, 1, 0))
                self.assertNotIn('gates', label)
            cohort = result['common_complete'][name]
            self.assertEqual(cohort['endpoint_sign_patterns'], {'++-': 1})
            self.assertEqual(cohort['same_endpoint_sign'], 0)
            self.assertEqual(cohort['both_positive_negative_endpoints'], 1)
            self.assertEqual(cohort['increments']['30_to_60']['positive'], 1)
            self.assertEqual(cohort['increments']['60_to_close']['negative'], 1)
            self.assertAlmostEqual(cohort['increments']['60_to_close']['mean_bp'], -500)
            empty = result['by_day'][(TODAY + timedelta(days=1)).isoformat()][name]
            self.assertTrue(all(tally['signals'] == 0 for tally in empty.values()))
        self.assertNotIn('selected_for_migration', result)

    def test_summary_counts_zero_negative_missing_and_no_efficiency_fabrication(self):
        rows = bars()
        event = frozen_event(rows)
        end = rows[8].close_time
        good = module.path_label(rows, event, end) | {'paired_lift': None}
        tally = module.Counter()
        for label in (good, good | {'return': -.01}, good | {'return': 0, 'direction_efficiency': None},
                      good | {'status': 'missing_future'}):
            module.add(tally, label)
        out = module.summary(tally)
        self.assertEqual((out['signals'], out['valid'], out['missing']), (4, 3, 1))
        self.assertEqual(out['win_rate'], 1 / 3)
        self.assertAlmostEqual(out['payoff_ratio'], 2)
        self.assertEqual(out['direction_efficiency_count'], 2)
        self.assertIsNone(out['mean_paired_lift'])

    def test_cli_refuses_existing_or_identical_output_paths_before_reading_data(self):
        with tempfile.TemporaryDirectory() as directory:
            report, labels = Path(directory) / 'report.json', Path(directory) / 'labels.jsonl'
            for occupied in (report, labels):
                occupied.write_text('unchanged', encoding='utf-8')
                with patch.object(module, 'replay') as run, self.assertRaises(SystemExit):
                    module.main(['--out', str(report), '--labels-out', str(labels)])
                run.assert_not_called()
                self.assertEqual(occupied.read_text(encoding='utf-8'), 'unchanged')
                occupied.unlink()
            with patch.object(module, 'replay') as run, self.assertRaises(SystemExit):
                module.main(['--out', str(report), '--labels-out', str(report)])
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
