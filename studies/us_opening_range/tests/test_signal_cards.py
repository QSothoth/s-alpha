"""Only synthetic fixtures: no RG1 export, market API, or new strategy labels."""
from dataclasses import asdict, replace
from datetime import date, datetime, time, timedelta
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ETREE

from custody.dataset import sha256_file
from custody.marketdata import Bar
from custody.models import ET
from studies.us_opening_range import signal_cards as module


DAY = date(2026, 9, 24)


def bars(day=DAY, symbol='XLV', historical=False):
    opening = datetime.combine(day, time(9, 30), ET)
    result = []
    for index in range(1, 79):
        price = 100 if historical else 105 if index <= 3 else 99999
        start = 100 if historical else 104
        result.append(Bar('US.' + symbol, opening + timedelta(minutes=5 * index), start,
                          max(start, price) + 1, min(start, price) - 1, price, 100, '5m'))
    return result


def event(day=DAY, symbol='XLV'):
    return {'candidate': 'G20_REVERSE', 'symbol': 'US.' + symbol,
            'time': datetime.combine(day, time(9, 45), ET).isoformat(),
            'direction': 'SHORT', 'original_direction': 'LONG', 'reference': 105,
            'range_high20': 101, 'range_low20': 99, 'key_level': 101, 'snapshot_minutes': 15,
            'atr': 2, 'gap_atr': 2, 'rvol': 1, 'activity_reason': 'gap', 'return_30m': -.01234567}


def prior_dates(today=DAY):
    result, day = [], today - timedelta(days=1)
    while len(result) < 20:
        if day.weekday() < 5:
            result.append(day)
        day -= timedelta(days=1)
    return list(reversed(result))


def card(e=None):
    e = e or event()
    today = date.fromisoformat(e['time'][:10])
    serial = lambda bar: asdict(bar) | {'close_time': bar.close_time.isoformat()}
    historical = [module.source.aggregate_daily(bars(day, historical=True)) for day in prior_dates(today)]
    return {'event': {key: e.get(key) for key in module.CONTEXT_KEYS},
            'daily': [serial(row) for row in historical], 'opening': [serial(row) for row in bars(today)[:3]]}


def write_events(path, events):
    path.write_text(''.join(json.dumps(e) + '\n' for e in events), encoding='utf-8')


class EventTests(unittest.TestCase):
    def test_exact_118_and_sort_preflight_before_any_output_or_price_access(self):
        events = [event(date(2020, 1, 2) + timedelta(days=i)) for i in range(118)]
        with tempfile.TemporaryDirectory() as folder:
            path, out = Path(folder) / 'events.jsonl', Path(folder) / 'out'
            write_events(path, list(reversed(events)))
            with patch.object(module, 'EVENTS_SHA256', sha256_file(path)):
                self.assertEqual(module.read_events(path), events)
            for count in (117, 119):
                write_events(path, [event(date(2020, 1, 2) + timedelta(days=i)) for i in range(count)])
                with patch.object(module, 'EVENTS_SHA256', sha256_file(path)), patch.object(module.source, 'load_inputs') as loader:
                    with self.assertRaises(ValueError):
                        module.export(out, path, Path(folder))
                    loader.assert_not_called()
                    self.assertFalse(out.exists())

    def test_hash_symbol_duplicate_and_sealed_date_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'events.jsonl'
            write_events(path, [event()])
            with self.assertRaisesRegex(ValueError, 'checksum'):
                module.read_events(path)
            cases = ([event(symbol='DIA')], [event(DAY + timedelta(days=1))],
                     [event(), event()], [event() | {'snapshot_minutes': 20}],
                     [event() | {'time': '2026-09-24T09:45:00'}])
            for events in cases:
                write_events(path, events)
                with patch.object(module, 'EVENT_COUNT', len(events)), patch.object(module, 'EVENTS_SHA256', sha256_file(path)):
                    with self.assertRaises(ValueError):
                        module.read_events(path)


class ContextTests(unittest.TestCase):
    def test_real_frozen_reader_excludes_0925_and_chart_never_contains_future(self):
        dates = prior_dates() + [DAY]
        calendar = {day.isoformat(): 78 for day in dates}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with (root / 'US.XLV.csv').open('w', newline='') as handle:
                writer = csv.writer(handle)
                writer.writerow(('code', 'time_key', 'open', 'high', 'low', 'close', 'volume'))
                for day in dates:
                    for row in bars(day, historical=day < DAY):
                        writer.writerow((row.code, row.close_time.replace(tzinfo=None).isoformat(' '),
                                         row.open, row.high, row.low, row.close, row.volume))
                writer.writerow(('WRONG', '2026-09-25 INVALID SEALED TIME', 'invalid', '', '', '', ''))
            with patch.object(module.source, 'SYMBOLS', ('XLV',)), \
                    patch.object(module.source, 'evaluate_signal_quality', side_effect=AssertionError('no new labels')):
                contexts = list(module.iter_contexts(root, calendar, [event()]))
            self.assertEqual(len(contexts), 1)
            context = contexts[0]
            self.assertEqual(len(context['daily']), 20)
            self.assertEqual(len(context['opening']), 3)
            self.assertTrue(all(row['close_time'][:10] < str(DAY) for row in context['daily']))
            self.assertTrue(all(row['close_time'] <= event()['time'] for row in context['opening']))
            self.assertNotIn('return_30m', context['event'])
            self.assertNotIn('99999', json.dumps(context))
            svg = module.render_svg(context)
            ETREE.fromstring(svg)
            self.assertIn('UNVALIDATED', svg)
            self.assertIn('20日高 101.0000', svg)
            self.assertIn('20日低 99.0000', svg)
            self.assertIn('参考价 105.0000', svg)
            self.assertNotIn('99999', svg)
            self.assertNotIn('09:50', svg)
            self.assertNotIn('return_30m', svg)

    def test_missing_day_history_prefix_and_reference_mismatch_fail_closed(self):
        dates = prior_dates() + [DAY]
        calendar = {day.isoformat(): 78 for day in dates}
        stream = [(day.isoformat(), 'XLV', bars(day, historical=day < DAY), True) for day in dates]
        cases = (stream[1:], stream[:5] + stream[6:],
                 stream[:-1] + [(str(DAY), 'XLV', bars()[1:], False)])
        with patch.object(module.source, 'SYMBOLS', ('XLV',)):
            for rows in cases:
                with patch.object(module.source, 'iter_sessions', return_value=iter(rows)):
                    with self.assertRaisesRegex(ValueError, 'missing prior'):
                        list(module.iter_contexts(Path('/synthetic'), calendar, [event()]))
            with patch.object(module.source, 'iter_sessions', return_value=iter(stream)):
                with self.assertRaisesRegex(ValueError, 'mismatch'):
                    list(module.iter_contexts(Path('/synthetic'), calendar, [event() | {'reference': 106}]))
            with patch.object(module.source, 'iter_sessions', return_value=iter(stream[:-1])):
                with self.assertRaisesRegex(ValueError, 'missing prior'):
                    list(module.iter_contexts(Path('/synthetic'), calendar, [event()]))

    def test_symbol_and_titles_are_xml_escaped_and_labels_do_not_enter_chart(self):
        context = card(event() | {'symbol': 'US.<script>&"', 'original_direction': 'LONG <unsafe>'})
        svg = module.render_svg(context)
        ETREE.fromstring(svg)
        self.assertNotIn('<script>', svg)
        self.assertIn('&lt;script&gt;&amp;', svg)
        self.assertIn('LONG &lt;unsafe&gt;', svg)
        changed = card(event() | {'return_30m': 99999})
        self.assertEqual(module.render_svg(changed), module.render_svg(card()))


class ExportTests(unittest.TestCase):
    def test_all_118_cards_are_exported_sorted_including_losing_labels(self):
        events = [event(date(2020, 1, 2) + timedelta(days=i)) | {'return_30m': .01 if i % 2 else -.01}
                  for i in range(118)]
        with tempfile.TemporaryDirectory() as folder:
            root, out = Path(folder), Path(folder) / 'all-cards'
            path = root / 'events.jsonl'
            write_events(path, list(reversed(events)))
            with patch.object(module, 'EVENTS_SHA256', sha256_file(path)), \
                    patch.object(module.source, 'load_inputs', return_value=({}, {'synthetic': True})), \
                    patch.object(module, 'iter_contexts', side_effect=lambda root, calendar, rows: (card(e) for e in rows)):
                result = module.export(out, path, root)
            self.assertEqual(result['events'], 118)
            self.assertEqual(len(list(out.glob('card-*.svg'))), 118)
            contexts = [json.loads(line) for line in (out / 'contexts.jsonl').read_text().splitlines()]
            self.assertEqual([row['event']['time'] for row in contexts], [e['time'] for e in events])
            html = (out / 'index.html').read_text()
            self.assertEqual(html.count('<td>-100.00</td>'), 59)
            self.assertEqual(html.count('<td>+100.00</td>'), 59)
            self.assertEqual(html.count('loading="lazy"'), 118)

    def test_package_preserves_event_bytes_all_cases_checksum_and_audit_separation(self):
        e = event()
        with tempfile.TemporaryDirectory() as folder:
            root, out = Path(folder), Path(folder) / 'cards'
            path = root / 'events.jsonl'
            write_events(path, [e])
            original = path.read_bytes()
            with patch.object(module, 'EVENT_COUNT', 1), patch.object(module, 'EVENTS_SHA256', sha256_file(path)), \
                    patch.object(module.source, 'load_inputs', return_value=({str(DAY): 78}, {'synthetic': True})) as loader, \
                    patch.object(module, 'iter_contexts', return_value=iter([card()])):
                manifest = module.export(out, path, root)
            self.assertEqual(loader.call_count, 2)
            self.assertEqual(manifest['events'], 1)
            self.assertEqual((out / 'events.jsonl').read_bytes(), original)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(set(p.name for p in out.iterdir()),
                             {'events.jsonl', 'contexts.jsonl', 'card-001.svg', 'index.html', 'manifest.json', 'CHECKSUMS.sha256'})
            for line in (out / 'CHECKSUMS.sha256').read_text().splitlines():
                digest, name = line.split(maxsplit=1)
                self.assertEqual(sha256_file(out / name), digest)
            html = (out / 'index.html').read_text()
            self.assertIn('loading="lazy"', html)
            self.assertIn('事后审计表', html)
            self.assertIn('-123.46', html)
            self.assertNotIn('-123.46', (out / 'card-001.svg').read_text())
            self.assertNotIn('return_30m', (out / 'contexts.jsonl').read_text())

    def test_existing_directory_source_pin_and_code_pin_reject_before_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            root, out = Path(folder), Path(folder) / 'new'
            with patch.object(module, 'read_events', side_effect=AssertionError('must not read')):
                with self.assertRaisesRegex(ValueError, 'overwrite'):
                    module.export(root)
            with patch.dict(module.CODE_PINS, {'custody/dataset.py': 'bad'}), \
                    patch.object(module, 'read_events', side_effect=AssertionError('must not read')):
                with self.assertRaisesRegex(ValueError, 'source code changed'):
                    module.export(out)
            self.assertFalse(out.exists())
            with patch.object(module, 'read_events', return_value=[event()]), \
                    patch.object(module.source, 'load_inputs', side_effect=ValueError('authorized input mismatch')):
                with self.assertRaisesRegex(ValueError, 'input mismatch'):
                    module.export(out)
            self.assertFalse(out.exists())


if __name__ == '__main__':
    unittest.main()
