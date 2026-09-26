"""Synthetic single-day cross-source checks: never network or real ETF rows."""
import csv
import io
import json
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.parse

from custody.dataset import sha256_file
from studies.us_opening_range import recent_crosscheck as module


def payload(symbol='XLV', factor=2):
    quote = {key: [] for key in (*module.FIELDS, 'volume')}
    stamps = []
    for index in range(78):
        stamps.append(int((module.OPEN + timedelta(minutes=5 * index)).timestamp()))
        opening = 100 + index * .2
        for key, value in dict(open=opening, high=opening + .4, low=opening - .3,
                               close=opening + .1, volume=100 + index).items():
            quote[key].append(value if key == 'volume' else factor * value)
    return {'chart': {'error': None, 'result': [{'meta': {'symbol': symbol, 'dataGranularity': '5m',
                'exchangeTimezoneName': 'America/New_York'}, 'timestamp': stamps,
                'indicators': {'quote': [quote]}}]}}


def response(raw, status=200):
    stream = io.BytesIO(raw)
    stream.status, stream.headers = status, {'Content-Type': 'application/json'}
    return stream


class CrosscheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'source'
        self.root.mkdir()
        self.out = Path(self.temp.name) / 'new-capture'
        pins = {}
        for symbol in module.SYMBOLS:
            path = self.root / ('US.' + symbol + '.csv')
            quote = payload(symbol, 1)['chart']['result'][0]['indicators']['quote'][0]
            with path.open('w', newline='') as handle:
                writer = csv.writer(handle)
                writer.writerow(('code', 'time_key', *module.FIELDS, 'volume', 'turnover'))
                writer.writerow(('WRONG', '2026-09-23 NOT A TIME', *('bad',) * 6))
                for index in range(78):
                    stamp = module.OPEN + timedelta(minutes=5 * (index + 1))
                    writer.writerow(('US.' + symbol, stamp.strftime('%Y-%m-%d %H:%M:%S'),
                                     *(quote[key][index] for key in (*module.FIELDS, 'volume')), 1000))
                writer.writerow(('WRONG', '2026-09-25 NOT A TIME', *('bad',) * 6))
            pins[symbol] = sha256_file(path)
        checksum = self.root / 'CHECKSUMS.sha256'
        checksum.write_text('\n'.join(digest + '  US.' + symbol + '.csv' for symbol, digest in pins.items()) + '\n')
        for name, value in (('PINS', pins), ('CHECKSUM_SHA', sha256_file(checksum))):
            guard = patch.object(module, name, value)
            guard.start()
            self.addCleanup(guard.stop)
        self.calls = []

    def urlopen(self, request, *, timeout):
        self.calls.append((request.full_url, timeout))
        symbol = urllib.parse.urlparse(request.full_url).path.rsplit('/', 1)[1]
        return response(json.dumps(payload(symbol)).encode())

    def capture(self, opener=None):
        return module.capture(self.out, self.root, urlopen=opener or self.urlopen)

    def assert_frozen(self, report):
        self.assertEqual(json.loads((self.out / 'manifest.json').read_text()), report)
        checksums = {}
        for line in (self.out / 'CHECKSUMS.sha256').read_text().splitlines():
            digest, name = line.split('  ', 1)
            self.assertEqual(sha256_file(self.out / name), digest)
            checksums[name] = digest
        self.assertEqual(set(checksums), {path.name for path in self.out.iterdir() if path.name != 'CHECKSUMS.sha256'})

    def test_exact_three_requests_et_day_bounds_primary_clock_and_uniform_factor(self):
        report = self.capture()
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(report['errors'], [])
        self.assertEqual(report['status'], 'completed')
        for (url, timeout), record, symbol in zip(self.calls, report['requests'], module.SYMBOLS):
            self.assertEqual(timeout, 20)
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            self.assertEqual(query['interval'], ['5m'])
            self.assertEqual(query['includePrePost'], ['false'])
            self.assertEqual(datetime.fromtimestamp(int(query['period1'][0]), module.ET).isoformat(), '2026-09-24T00:00:00-04:00')
            self.assertEqual(datetime.fromtimestamp(int(query['period2'][0]), module.ET).isoformat(), '2026-09-25T00:00:00-04:00')
            self.assertEqual(url, module.request_url(symbol))
            self.assertTrue(record['body_complete'])
            self.assertIn('started_at', record)
            self.assertIn('finished_at', record)
            comparison = record['comparison']
            self.assertTrue(comparison['primary_full_78'])
            self.assertEqual(comparison['factor_yahoo_over_opend'], 2)
            shifts = comparison['shifts_from_raw_yahoo_timestamp_minutes']
            self.assertEqual([shifts[str(shift)]['common_rows'] for shift in (-5, 0, 5)], [76, 77, 78])
            self.assertEqual(shifts['5']['volume_different'], 0)
            for key in module.FIELDS:
                self.assertEqual(shifts['5']['ohlc'][key]['scaled_max_relative_error'], 0)
                self.assertEqual(shifts['5']['ohlc'][key]['raw_max_relative_error'], .5)
                self.assertGreater(shifts['0']['ohlc'][key]['scaled_max_relative_error'], 0)
            with (self.out / (symbol + '.opend.csv')).open() as handle:
                local = list(csv.DictReader(handle))
            self.assertEqual(len(local), 78)
            self.assertTrue(all(row['time_key'].startswith(module.DAY) for row in local))
            self.assertEqual(json.loads((self.out / record['file']).read_bytes()), payload(symbol))
        self.assert_frozen(report)
        with self.assertRaises(ValueError):
            module.request_url('SPY')

    def test_fitted_multiplier_cannot_hide_nonconstant_ohlc_or_volume_difference(self):
        def altered(request, *, timeout):
            symbol = urllib.parse.urlparse(request.full_url).path.rsplit('/', 1)[1]
            data = payload(symbol)
            quote = data['chart']['result'][0]['indicators']['quote'][0]
            quote['high'][-1] *= 1.01
            quote['volume'][-1] += 1
            return response(json.dumps(data).encode())
        report = self.capture(altered)
        comparison = report['requests'][0]['comparison']
        self.assertEqual(comparison['factor_yahoo_over_opend'], 2)
        self.assertGreater(comparison['primary_ratio_max'], comparison['primary_ratio_min'])
        primary = comparison['shifts_from_raw_yahoo_timestamp_minutes']['5']
        self.assertGreater(primary['ohlc']['high']['scaled_max_relative_error'], .009)
        self.assertEqual(primary['ohlc']['high']['scaled_within_1e_4'], 77)
        self.assertEqual(primary['volume_different'], 1)

    def test_null_ohlc_missing_volume_and_outside_scope_are_disclosed_not_imputed(self):
        data = payload()
        item = data['chart']['result'][0]
        quote = item['indicators']['quote'][0]
        quote['close'][4], quote['volume'][5] = None, None
        item['timestamp'].append(int((module.MIDNIGHT + timedelta(days=1)).timestamp()))
        for key in quote:
            quote[key].append('MUST NOT PARSE')
        path = self.root / 'synthetic.raw'
        path.write_bytes(json.dumps(data).encode())
        yahoo, coverage = module.yahoo_rows(path, 'XLV')
        self.assertEqual(len(yahoo), 77)
        self.assertEqual(len(coverage['invalid_ohlc_times']), 1)
        self.assertEqual(len(coverage['outside_rth_times']), 1)
        local = module.local_day(self.root / 'US.XLV.csv', 'XLV', self.root / 'excerpt.csv')
        comparison = module.compare(local, yahoo)
        self.assertFalse(comparison['primary_full_78'])
        self.assertEqual(comparison['shifts_from_raw_yahoo_timestamp_minutes']['5']['volume_unknown'], 1)

    def test_yahoo_symbol_grid_duplicates_and_array_lengths_are_guarded(self):
        path = self.root / 'synthetic.raw'
        for change in ('symbol', 'duplicate', 'off_grid', 'length'):
            data = payload()
            item = data['chart']['result'][0]
            if change == 'symbol': item['meta']['symbol'] = 'SPY'
            if change == 'duplicate': item['timestamp'][1] = item['timestamp'][0]
            if change == 'off_grid': item['timestamp'][0] += 1
            if change == 'length': item['indicators']['quote'][0]['high'].pop()
            path.write_bytes(json.dumps(data).encode())
            with self.assertRaises(ValueError):
                module.yahoo_rows(path, 'XLV')

    def test_http_errors_keep_full_body_and_transport_failure_keeps_empty_raw_no_retry(self):
        attempts = []
        error_body = b'upstream unavailable\x00\xff'
        def failed(request, *, timeout):
            attempts.append(request.full_url)
            if len(attempts) == 1:
                raise urllib.error.HTTPError(request.full_url, 429, 'rate limited', {'X-Test': 'yes'}, io.BytesIO(error_body))
            if len(attempts) == 2:
                raise urllib.error.URLError('connection refused')
            return self.urlopen(request, timeout=timeout)
        report = self.capture(failed)
        self.assertEqual(len(attempts), 3)
        self.assertEqual(len(report['errors']), 2)
        self.assertEqual((self.out / 'XLV.yahoo.raw').read_bytes(), error_body)
        self.assertEqual((self.out / 'XLI.yahoo.raw').read_bytes(), b'')
        self.assertTrue(report['requests'][0]['body_complete'])
        self.assertFalse(report['requests'][1]['body_complete'])
        self.assertEqual(report['requests'][0]['status'], 429)
        self.assertNotIn('comparison', report['requests'][0])
        self.assertIn('comparison', report['requests'][2])
        self.assert_frozen(report)

    def test_large_invalid_body_is_not_truncated_and_partial_transport_bytes_survive(self):
        large = b'x' * ((2 << 20) + 123)
        class Broken(io.BytesIO):
            status, headers = 200, {}
            def read(self, size=-1):
                if self.tell(): raise OSError('interrupted body')
                return super().read(size)
        attempts = []
        def responses(request, *, timeout):
            attempts.append(request.full_url)
            return Broken(b'partial bytes') if len(attempts) == 2 else response(large)
        report = self.capture(responses)
        self.assertEqual(len(attempts), 3)
        self.assertEqual((self.out / 'XLV.yahoo.raw').read_bytes(), large)
        self.assertEqual((self.out / 'XLI.yahoo.raw').read_bytes(), b'partial bytes')
        self.assertFalse(report['requests'][1]['body_complete'])
        self.assertTrue(report['requests'][0]['body_complete'])
        self.assertEqual(len(report['errors']), 3)
        self.assert_frozen(report)

    def test_source_pin_or_grid_failure_prevents_all_http_and_freezes_error(self):
        (self.root / 'US.XLI.csv').write_text('changed')
        opener = Mock(side_effect=AssertionError('must not request'))
        report = self.capture(opener)
        opener.assert_not_called()
        self.assertEqual(report['requests'], [])
        self.assertIn('pin mismatch', report['errors'][0])
        self.assert_frozen(report)
        path = self.root / 'US.XLV.csv'
        path.write_text(path.read_text().replace('09:40:00', '09:41:00'))
        with self.assertRaisesRegex(ValueError, 'RTH grid'):
            module.local_day(path, 'XLV', self.root / 'bad.csv')
        self.assertFalse((self.root / 'bad.csv').exists())

    def test_no_overwrite_or_implicit_redirects(self):
        report = self.capture()
        before = (self.out / 'manifest.json').read_bytes()
        opener = Mock(side_effect=AssertionError('must not request'))
        with self.assertRaises(FileExistsError):
            self.capture(opener)
        opener.assert_not_called()
        self.assertEqual((self.out / 'manifest.json').read_bytes(), before)
        self.assertIsNone(module._NoRedirect().redirect_request(None, None, 302, 'redirect', {}, 'https://other.example/'))
        self.assert_frozen(report)

    def test_empty_yahoo_is_explicitly_unknown_and_headers_exclude_session_secrets(self):
        def empty(request, *, timeout):
            symbol = urllib.parse.urlparse(request.full_url).path.rsplit('/', 1)[1]
            data = payload(symbol)
            item = data['chart']['result'][0]
            item['timestamp'] = []
            item['indicators']['quote'] = [{key: [] for key in (*module.FIELDS, 'volume')}]
            stream = response(json.dumps(data).encode())
            stream.headers = {'Date': 'public date', 'Content-Type': 'application/json',
                              'content-length': '123', 'Cache-Control': 'max-age=0', 'Age': '0',
                              'Set-Cookie': 'DO NOT SAVE', 'Authorization': 'DO NOT SAVE',
                              'X-Session': 'DO NOT SAVE'}
            return stream
        report = self.capture(empty)
        self.assertEqual(report['status'], 'completed')  # Capture completed, not a quality pass.
        for record in report['requests']:
            self.assertEqual({key.lower() for key in record['headers']}, module.PUBLIC_HEADERS)
            comparison = record['comparison']
            self.assertEqual(comparison['quality_status'], 'unknown_empty_yahoo_rth')
            self.assertIsNone(comparison['factor_yahoo_over_opend'])
            self.assertFalse(comparison['primary_full_78'])
        self.assertNotIn('DO NOT SAVE', (self.out / 'manifest.json').read_text())
        self.assert_frozen(report)


if __name__ == '__main__':
    unittest.main()
