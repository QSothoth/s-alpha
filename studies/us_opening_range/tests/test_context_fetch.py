import csv
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from custody.dataset import sha256_file
from studies.us_opening_range import context_fetch as fetcher


def row(code, stamp='2020-01-02 09:35:00', **changes):
    return {'code': code, 'time_key': stamp, 'open': 100, 'high': 102,
            'low': 99, 'close': 101, 'volume': 1000, 'turnover': 100500, **changes}


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, delay):
        self.now += delay


class Context:
    def __init__(self, clock, *, charged=(), remaining=84, pages=None):
        self.clock, self.charged, self.remaining = clock, set(charged), remaining
        self.pages = pages
        self.calls, self.history, self.quota_calls = [], [], 0
        self.closed = False

    def get_history_kl_quota(self, get_detail=False):
        self.calls.append(self.clock.now)
        self.quota_calls += 1
        assert get_detail
        return 0, (len(self.charged), self.remaining,
                   [{'code': c} for c in sorted(self.charged)])

    def request_history_kline(self, code, **kwargs):
        self.calls.append(self.clock.now)
        self.history.append((code, kwargs))
        if code not in self.charged:
            self.charged.add(code)
            self.remaining -= 1
        if self.pages:
            return self.pages(code, kwargs['page_req_key'])
        return 0, [row(code)], None

    def close(self):
        self.closed = True


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'capture'
        self.clock = Clock()

    def run_fetch(self, ctx):
        return fetcher.fetch(ctx, self.root, sleep=self.clock.sleep,
                             monotonic=self.clock.monotonic)

    def test_fixed_scope_streaming_boundary_dedup_quota_and_hashes(self):
        def pages(code, key):
            if key is None:
                return 0, [row(code)], b'next'
            # Prior page must already be flushed to disk, before another request.
            text = (self.root / (code + '.csv')).read_text()
            self.assertIn('2020-01-02 09:35:00', text)
            return 0, [row(code), row(code, '2020-01-02 09:40:00')], None

        ctx = Context(self.clock, pages=pages)
        manifest = self.run_fetch(ctx)
        self.assertEqual('downloaded', manifest['status'])
        self.assertEqual('holdout/underlying-context', manifest['role'])
        self.assertEqual('not_evaluated', manifest['evaluation_status'])
        self.assertEqual(72, manifest['quota_after']['remaining'])
        self.assertEqual(list(fetcher.CODES), manifest['new_symbols_attempted'])
        self.assertEqual(14, ctx.quota_calls)
        self.assertTrue(all(b - a >= 0.6 - 1e-12 for a, b in zip(ctx.calls, ctx.calls[1:])))
        for code, kwargs in ctx.history:
            self.assertIn(code, fetcher.CODES)
            self.assertEqual(dict(start='2018-09-01', end='2026-09-25', ktype='K_5M',
                                  autype='qfq', session='RTH', extended_time=False,
                                  max_count=1000, page_req_key=kwargs['page_req_key']), kwargs)
        for item in manifest['symbols']:
            self.assertEqual(2, item['rows'])
            self.assertEqual(1, item['boundary_duplicates'])
            with (self.root / item['file']).open() as fh:
                self.assertEqual(['2020-01-02 09:35:00', '2020-01-02 09:40:00'],
                                 [r['time_key'] for r in csv.DictReader(fh)])
        self.assertEqual(manifest, json.loads((self.root / 'manifest.json').read_text()))
        for line in (self.root / 'CHECKSUMS.sha256').read_text().splitlines():
            digest, name = line.split('  ')
            self.assertEqual(digest, sha256_file(self.root / name))

    def test_already_charged_does_not_spend_authorization(self):
        ctx = Context(self.clock, charged=fetcher.CODES, remaining=72)
        manifest = self.run_fetch(ctx)
        self.assertEqual('downloaded', manifest['status'])
        self.assertEqual([], manifest['new_symbols_attempted'])
        self.assertEqual(72, ctx.remaining)

    def test_quota_details_can_repeat_one_charged_symbol(self):
        ctx = Context(self.clock, charged=('US.SPY',))
        original = ctx.get_history_kl_quota

        def quota(**kwargs):
            ret, (used, remaining, details) = original(**kwargs)
            return ret, (used, remaining, details + [{'code': 'US.SPY'}])

        ctx.get_history_kl_quota = quota
        manifest = self.run_fetch(ctx)
        self.assertEqual(manifest['status'], 'downloaded')
        self.assertEqual(manifest['quota_before']['used'], 1)
        self.assertEqual(manifest['quota_before']['detail_rows'], 2)
        self.assertEqual(manifest['quota_before']['charged_codes'], ['US.SPY'])

    def test_insufficient_full_batch_quota_prevents_every_history_request(self):
        ctx = Context(self.clock, remaining=83)
        manifest = self.run_fetch(ctx)
        self.assertEqual('partial', manifest['status'])
        self.assertFalse(ctx.history)
        self.assertEqual(12, sum(i['status'] == 'not_started' for i in manifest['symbols']))

    def test_reserve_rechecked_before_next_new_symbol(self):
        ctx = Context(self.clock)
        original = ctx.request_history_kline

        def history(*args, **kwargs):
            result = original(*args, **kwargs)
            ctx.remaining = 72  # Another connection consumed remaining headroom.
            return result

        ctx.request_history_kline = history
        manifest = self.run_fetch(ctx)
        self.assertEqual('partial', manifest['status'])
        self.assertEqual(1, len(ctx.history))
        self.assertIn('reserve guard', manifest['errors'][0])
        self.assertEqual('not_started', manifest['symbols'][2]['status'])

    def test_bad_pages_fail_fast_keep_partial_and_never_retry(self):
        scenarios = {
            'conflict': lambda c, k: (0, [row(c)] if k is None else [row(c, close=100)], b'next'),
            'repeated_key': lambda c, k: (0, [row(c, '2020-01-02 09:35:00' if k is None
                                                      else '2020-01-02 09:40:00')], b'next'),
            'duplicate_inside_page': lambda c, k: (0, [row(c), row(c)], None),
            'unordered': lambda c, k: (0, [row(c, '2020-01-02 09:40:00'), row(c)], None),
            'error': lambda c, k: (1, 'permission denied', None),
            'empty': lambda c, k: (0, [], None),
            'empty_nonterminal': lambda c, k: (0, [], b'next'),
            'oversized': lambda c, k: (0, [row(c)] * 1001, None),
        }
        for name, pages in scenarios.items():
            with self.subTest(name=name):
                self.root = Path(self.tmp.name) / name
                ctx = Context(self.clock, pages=pages)
                manifest = self.run_fetch(ctx)
                self.assertEqual('partial', manifest['status'])
                self.assertTrue(manifest['errors'])
                if name == 'oversized':
                    self.assertIn('exceeds 1000', manifest['errors'][0])
                self.assertEqual({fetcher.CODES[0]}, {c for c, _ in ctx.history})
                self.assertEqual('not_started', manifest['symbols'][1]['status'])
                self.assertTrue((self.root / 'US.DIA.csv').exists())
                self.assertTrue((self.root / 'CHECKSUMS.sha256').exists())
                with self.assertRaises(FileExistsError):
                    self.run_fetch(ctx)

    def test_scope_and_value_checks_reject_instead_of_drop(self):
        for change in ({'time_key': '2020-01-02 09:30:00'},
                       {'time_key': '2020-01-02 16:05:00'},
                       {'time_key': '2018-08-31 09:35:00'},
                       {'time_key': '2020-01-02 09:36:00'},
                       {'code': 'US.SPY'}, {'close': float('nan')},
                       {'open': 0}, {'volume': -1}, {'high': 98}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                fetcher._row({**row('US.DIA'), **change}, 'US.DIA')

    def test_daily_gaps_recorded_without_fabricating_tail_or_calendar(self):
        ctx = Context(self.clock, pages=lambda c, k: (
            0, [row(c, '2020-01-02 09:40:00'), row(c, '2020-01-02 09:50:00'),
                row(c, '2020-01-03 09:35:00')], None))
        manifest = self.run_fetch(ctx)
        self.assertEqual('calendar_unverified', manifest['coverage_status'])
        with (self.root / 'US.DIA.coverage.csv').open() as fh:
            days = list(csv.DictReader(fh))
        self.assertEqual('2', days[0]['missing_before_or_between'])
        self.assertEqual('0', days[1]['missing_before_or_between'])
        self.assertEqual('09:50:00', days[0]['last_close'])

    def test_page_cap_and_final_quota_failure_are_not_success(self):
        ctx = Context(self.clock, pages=lambda c, k: (0, [row(c)], b'next'))
        with patch.object(fetcher, 'MAX_PAGES', 1):
            manifest = self.run_fetch(ctx)
        self.assertIn('page limit', manifest['errors'][0])
        self.root = Path(self.tmp.name) / 'quota-fail'
        ctx = Context(self.clock)
        original = ctx.get_history_kl_quota

        def quota(**kwargs):
            if len(ctx.history) == 12:
                return 1, 'disconnected'
            return original(**kwargs)

        ctx.get_history_kl_quota = quota
        manifest = self.run_fetch(ctx)
        self.assertEqual('partial', manifest['status'])
        self.assertIsNone(manifest['quota_after'])

    def test_entry_closes_single_context_even_on_failure(self):
        ctx = Context(self.clock)
        sdk = types.SimpleNamespace(__version__='fake', OpenQuoteContext=lambda **kwargs: ctx)
        with patch.dict('sys.modules', futu=sdk), \
                patch.object(fetcher, 'fetch', side_effect=RuntimeError('disk full')):
            with self.assertRaisesRegex(RuntimeError, 'disk full'):
                fetcher.main(['--out', str(self.root)])
        self.assertTrue(ctx.closed)
        self.root.mkdir()
        with patch.dict('sys.modules', futu=sdk), patch('sys.stderr', io.StringIO()):
            with self.assertRaises(SystemExit):
                fetcher.main(['--out', str(self.root)])


if __name__ == '__main__':
    unittest.main()
