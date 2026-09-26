import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from custody.dataset import sha256_file
from studies.us_opening_range import source_recheck as source


class Frame:
    columns = ('time_key', 'open', 'high', 'low', 'close', 'volume', 'turnover')

    def __len__(self):
        return 1

    def itertuples(self, *, index, name):
        assert index is False and name is None
        return iter([('2024-05-30 09:35:00', 10, 11, 9, 10, 100, 1000)])


class QuoteContext:
    def __init__(self, *, charged=True, responses=None):
        self.charged = charged
        self.responses = iter(responses or [(0, Frame(), None)] * 3)
        self.history_calls = []
        self.quota_calls = 0
        self.closed = False

    def get_history_kl_quota(self, *, get_detail):
        assert get_detail is True
        self.quota_calls += 1
        return 0, (1, 299, [{'code': 'US.SPY' if self.charged else 'US.QQQ'}])

    def request_history_kline(self, code, **kwargs):
        self.history_calls.append((code, kwargs))
        return next(self.responses)

    def close(self):
        self.closed = True


class SourceRecheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.out = self.base / 'fresh-work'
        old = {}
        for key in ('k5', 'daily', 'ext30'):
            path = self.base / (key + '.csv')
            first = 'date' if key == 'daily' else 'time_key'
            path.write_text(first + ',open,high,low,close,volume,turnover\n')
            old[key] = path
        self.old_patch = patch.object(source, 'OLD', old)
        self.old_patch.start()
        self.addCleanup(self.old_patch.stop)
        self.waits = []
        self.http_calls = []

    def urlopen(self, request, *, timeout):
        self.http_calls.append((request.full_url, timeout))
        response = io.BytesIO(b'{}')
        response.status = 200
        return response

    def capture(self, context):
        return source.capture(context, self.out, 'fake-sdk',
                              sleep=self.waits.append, urlopen=self.urlopen)

    def assert_frozen(self):
        entries = {}
        for line in (self.out / 'CHECKSUMS.sha256').read_text().splitlines():
            digest, name = line.split('  ', 1)
            self.assertEqual(sha256_file(self.out / name), digest)
            entries[name] = digest
        self.assertEqual(set(entries), {p.name for p in self.out.iterdir()
                                        if p.name != 'CHECKSUMS.sha256'})
        return json.loads((self.out / 'manifest.json').read_text())

    def test_existing_output_is_unchanged_and_no_calls_are_made(self):
        self.capture(QuoteContext())
        before = {p.name: p.read_bytes() for p in self.out.iterdir()}
        context = QuoteContext()
        http_count = len(self.http_calls)
        with self.assertRaises(FileExistsError):
            self.capture(context)
        self.assertEqual(context.quota_calls, 0)
        self.assertEqual(context.history_calls, [])
        self.assertEqual(len(self.http_calls), http_count)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.out.iterdir()})

    def test_uncharged_spy_never_requests_history(self):
        context = QuoteContext(charged=False)
        result = self.capture(context)
        self.assertEqual(context.history_calls, [])
        self.assertEqual(self.waits, [])
        self.assertEqual(context.quota_calls, 2)
        self.assertIn('SPY would require new quota', result['errors'][0])
        self.assertEqual(self.assert_frozen(), result)

    def test_only_three_fixed_requests_and_two_fixed_http_requests(self):
        context = QuoteContext()
        result = self.capture(context)
        expected = [(source.CODE, dict(start=source.DAY, end=source.DAY, autype='qfq',
                     max_count=1000, page_req_key=None, **specific))
                    for _, specific in source.JOBS]
        self.assertEqual(context.history_calls, expected)
        self.assertEqual(self.waits, [1.05] * 3)
        self.assertEqual(context.quota_calls, 2)
        self.assertEqual(self.http_calls, [(url, 20) for _, url in source.URLS])
        self.assertEqual(result['errors'], [])
        self.assertTrue(all(not r['more_pages'] for r in result['history_requests']))
        self.assertEqual(self.assert_frozen(), result)

    def test_continuation_is_saved_but_never_followed(self):
        context = QuoteContext(responses=[(0, Frame(), b'next-page')])
        result = self.capture(context)
        self.assertEqual(len(context.history_calls), 1)
        self.assertTrue((self.out / 'opend_k5.csv').exists())
        self.assertFalse((self.out / 'opend_daily.csv').exists())
        self.assertTrue(result['history_requests'][0]['more_pages'])
        self.assertIn('no extra request permitted', result['errors'][0])
        self.assertEqual(self.assert_frozen(), result)

    def test_failure_keeps_successful_raw_and_error_manifest_without_retry(self):
        context = QuoteContext(responses=[(0, Frame(), None), (-1, 'fake failure', None)])
        result = self.capture(context)
        self.assertEqual(len(context.history_calls), 2)
        self.assertTrue((self.out / 'opend_k5.csv').exists())
        self.assertFalse((self.out / 'opend_daily.csv').exists())
        self.assertEqual(result['history_requests'][1]['error'], 'fake failure')
        self.assertIn('history request failed', result['errors'][0])
        self.assertEqual(self.assert_frozen(), result)

    def test_main_closes_its_connection_even_when_capture_raises(self):
        context = QuoteContext()
        fake_sdk = SimpleNamespace(__version__='fake-sdk', OpenQuoteContext=lambda **kw: context)
        with patch.dict('sys.modules', futu=fake_sdk), \
             patch.object(source, 'capture', side_effect=RuntimeError('fake failure')):
            with self.assertRaisesRegex(RuntimeError, 'fake failure'):
                source.main(['--out', str(self.out)])
        self.assertTrue(context.closed)


if __name__ == '__main__':
    unittest.main()
