"""Synthetic OM1 display tests; never calculate fresh strategy labels."""
from copy import deepcopy
from dataclasses import asdict
from datetime import date, datetime, time, timedelta
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as XML

from custody.dataset import sha256_file
from custody.marketdata import Bar
from custody.models import ET
from studies.us_opening_range import option_cards as module
from studies.us_opening_range.tests.test_signal_cards import bars, card, prior_dates


def past_bars(day, symbol):
    return [Bar(symbol, datetime.combine(d, time(16), ET), 100, 101, 99, 100, 7800, '1d') for d in prior_dates(day)]


def observation(day, symbol):
    day = date.fromisoformat(day)
    setup = module.source.daily_levels(past_bars(day, symbol), day)
    signal = dict(symbol=symbol, time=day.isoformat() + 'T09:45:00-04:00', direction='LONG',
                  reference=105, level=101, invalidation=100.8, risk=4.2, target=113.4,
                  room_state='beyond_observed_20d_range', boundary20=101, atr=2, snapshot_minutes=15)
    return dict(candidate='PD_BREAK', symbol=symbol, trade_date=day.isoformat(), setup=setup, signal=signal,
                underlying={'return_30m': -.123456}, option={'contract': symbol + 'FAKE',
                'mark_return_30m': None if symbol == 'US.META' else .123456, 'missing': ['future'] if symbol == 'US.META' else []})


def records():
    keys = set(module.EXPECTED)
    for index in range(80):
        if len(keys) == 77:
            break
        keys.add(((date(2026, 8, 18) + timedelta(days=index // 15)).isoformat(), 'US.' + module.source.SYMBOLS[index % 15]))
    rows = []
    for day, symbol in sorted(keys):
        for candidate in module.source.CANDIDATES:
            row = observation(day, symbol)
            row['candidate'] = candidate
            if (day, symbol) not in module.EXPECTED or candidate != 'PD_BREAK' and symbol != 'US.META':
                row['signal'] = None
            else:
                row['signal']['candidate'] = candidate
            rows.append(row)
    return rows


def context(row):
    day, symbol = date.fromisoformat(row['trade_date']), row['symbol'].removeprefix('US.')
    serialize = lambda b: asdict(b) | {'close_time': b.close_time.isoformat()}
    event = {key: row['signal'][key] for key in module.SIGNAL_KEYS}
    event.update({key: row['setup'][key] for key in module.SETUP_KEYS})
    event.update(key_level=event['level'], member_candidates=row['member_candidates'])
    return {'event': event, 'daily': [serialize(b) for b in past_bars(day, row['symbol'])],
            'opening': [serialize(b) for b in bars(day, symbol)[:3]]}


class OptionCardTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.events, self.report = self.root / 'records.jsonl', self.root / 'report.json'
        self.rows = records()
        self.write()

    def write(self):
        self.events.write_text(''.join(json.dumps(row) + '\n' for row in reversed(self.rows)))
        self.report.write_text(json.dumps({'study': 'OM1', 'records_artifact': {'sha256': sha256_file(self.events)},
            'preregistration_sha256': module.source.PREREG_SHA256, 'code_sha256': {}}))
        for name, digest in (('EVENTS_SHA', sha256_file(self.events)), ('REPORT_SHA', sha256_file(self.report))):
            guard = patch.object(module, name, digest)
            guard.start()
            self.addCleanup(guard.stop)

    def frozen(self):
        return module.read_frozen(self.events, self.report)[0]

    def test_exact_seven_all_records_and_members_not_duplicate_cards(self):
        events = self.frozen()
        self.assertEqual([(r['trade_date'], r['symbol']) for r in events], list(module.EXPECTED))
        self.assertEqual(events[0]['member_candidates'], list(module.source.CANDIDATES))
        self.assertEqual(len(events), 7)
        for row in self.rows:
            if row['signal']:
                row['signal']['time'] = '2026-09-25T09:45:00-04:00'
                break
        self.write()
        with self.assertRaisesRegex(ValueError, 'identity|overlap'):
            self.frozen()

    def test_count_hash_and_missing_independent_event_fail_before_source_access(self):
        for mode in ('count', 'missing', 'hash'):
            with self.subTest(mode=mode):
                self.rows = records()
                if mode == 'count': self.rows.pop()
                if mode == 'missing':
                    for row in self.rows:
                        if row['symbol'] == 'US.MU': row['signal'] = None
                self.write()
                if mode == 'hash': self.events.write_text('changed')
                with patch.object(module.source, 'load_inputs') as load:
                    with self.assertRaises(ValueError):
                        module.export(self.root / mode, self.events, self.report)
                    load.assert_not_called()
                    self.assertFalse((self.root / mode).exists())

    def test_context_uses_original_reader_cutoff_and_causal_whitelist(self):
        event = self.frozen()[0]
        day, symbol = date.fromisoformat(event['trade_date']), 'META'
        dates = prior_dates(day) + [day]
        calendar = {d.isoformat(): 78 for d in dates}
        source = self.root / 'preopen-us-k5-valid-v1/k5/META.csv'
        source.parent.mkdir(parents=True)
        from studies.us_opening_range.tests.test_option_bridge import HistoryTests
        HistoryTests().write(source, [b for d in dates for b in bars(d, symbol, d < day)],
            [{'time_key': '2026-09-25 MUST_NOT_PARSE', 'code': 'WRONG', 'close': 'SEALED'}])
        with patch.object(module, 'EXPECTED', ((str(day), 'US.META'),)), \
                patch.object(module.source, 'detect_signals', side_effect=AssertionError('no redetection')), \
                patch.object(module.source, 'evaluate_signal_quality', side_effect=AssertionError('no labels')):
            result = module.contexts(self.root, calendar, [event])[0]
        self.assertEqual(len(result['daily']), 20)
        self.assertEqual(len(result['opening']), 3)
        self.assertTrue(all(b['close_time'][:10] < str(day) for b in result['daily']))
        text = json.dumps(result)
        for value in ('return_30m', 'future_close', 'mark_return', '99999', 'SEALED'):
            self.assertNotIn(value, text)
        for bad_calendar in (dict(list(calendar.items())[1:]), dict(calendar)):
            if len(bad_calendar) == len(calendar):
                event = deepcopy(event)
                event['signal']['reference'] += 1
            with patch.object(module, 'EXPECTED', ((str(day), 'US.META'),)), self.assertRaises(ValueError):
                module.contexts(self.root, bad_calendar, [event])

    def test_rg1_default_bytes_identical_and_custom_text_is_escaped(self):
        svg = module.render_svg(card())
        self.assertEqual(hashlib.sha256(svg.encode()).hexdigest(), 'd0fc8828293c4acb2e486078bb8ebbabb7132b710e83abfb9888e1670bdbb143')
        svg = module.render_svg(card(), title='UNVALIDATED <script>&', key_level_label='昨日 <高>&')
        XML.fromstring(svg)
        self.assertNotIn('<script>', svg)
        self.assertIn('昨日 &lt;高&gt;&amp;', svg)

    def test_overlay_is_above_candles_separates_text_and_preserves_geometry_values(self):
        value = card()
        value['event'].update(range_high20=105.01, range_low20=105.005, key_level=105.001)
        original = XML.fromstring(module.render_svg(value))
        improved = XML.fromstring(module.render_svg(value, label_overlay=True))
        nodes = list(improved.iter())
        geometry = lambda tree: [(n.tag, n.attrib) for n in tree.iter() if n.tag.rsplit('}', 1)[-1] in ('path', 'rect')]
        self.assertEqual(geometry(original), geometry(improved))
        labels = [node for node in nodes if node.get('class') == 'key-label']
        self.assertEqual(len(labels), 5)
        original_text = [node.text for node in original.iter() if node.tag.endswith('text')]
        for node in labels:
            self.assertIn(node.text, original_text)
            self.assertEqual(node.get('stroke'), 'white')
            self.assertEqual(node.get('paint-order'), 'stroke')
        for x, panel_start, panel_end in (('69', 65, 540), ('669', 665, 1140)):
            panel_labels = [node for node in labels if node.get('x') == x]
            positions = sorted(float(node.get('y')) for node in panel_labels)
            self.assertTrue(all(b - a >= 16.99 for a, b in zip(positions, positions[1:])))
            bodies = [node for node in nodes if node.tag.endswith('rect') and node.get('fill') in ('#16836c', '#c3414a')
                      and panel_start <= float(node.get('x')) <= panel_end]
            self.assertTrue(all(nodes.index(label) > nodes.index(body) for label in panel_labels for body in bodies))

    def test_export_all_seven_preserves_sources_separates_audit_and_seals(self):
        events, out = self.frozen(), self.root / 'cards'
        with patch.object(module.source, 'load_inputs', return_value=({}, {}, {'synthetic': True})), \
                patch.object(module, 'contexts', return_value=[context(row) for row in events]):
            result = module.export(out, self.events, self.report)
        self.assertEqual(result['cards'], 7)
        self.assertEqual(len(list(out.glob('card-*.svg'))), 7)
        self.assertEqual((out / 'records.jsonl').read_bytes(), self.events.read_bytes())
        self.assertEqual((out / 'om1_diagnostic.json').read_bytes(), self.report.read_bytes())
        self.assertEqual(sha256_file(out / 'OM1_PREREG.md'), module.source.PREREG_SHA256)
        html = (out / 'index.html').read_text()
        self.assertEqual(html.count('loading="lazy"'), 7)
        self.assertIn('缺失', html)
        self.assertIn('-1234.56', html)
        for path in list(out.glob('*.svg')) + [out / 'contexts.jsonl']:
            self.assertNotIn('-1234.56', path.read_text())
            self.assertNotIn('mark_return_30m', path.read_text())
        for line in (out / 'CHECKSUMS.sha256').read_text().splitlines():
            digest, name = line.split('  ', 1)
            self.assertEqual(sha256_file(out / name), digest)
        with patch.object(module, 'read_frozen') as read, self.assertRaises(FileExistsError):
            module.export(out)
        read.assert_not_called()

    def test_code_and_source_pin_failure_creates_no_output(self):
        contents = json.loads(self.report.read_text())
        contents['code_sha256'] = {'studies/us_opening_range/option_bridge.py': 'bad'}
        self.report.write_text(json.dumps(contents))
        with patch.object(module, 'REPORT_SHA', sha256_file(self.report)), self.assertRaisesRegex(ValueError, 'code mismatch'):
            self.frozen()
        self.write()
        with patch.object(module.source, 'load_inputs', side_effect=ValueError('source mismatch')):
            with self.assertRaisesRegex(ValueError, 'source mismatch'):
                module.export(self.root / 'failed', self.events, self.report)
        self.assertFalse((self.root / 'failed').exists())


if __name__ == '__main__':
    unittest.main()
