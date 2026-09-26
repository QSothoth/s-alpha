"""Synthetic source equivalence checks; never API calls or real price rows."""
import contextlib
import csv
from datetime import datetime, timedelta
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from custody.dataset import sha256_file
from studies.us_opening_range import daily_source_check as module


class Clock:
    def __init__(self):
        self.value, self.pauses = 0., []

    def __call__(self):
        return self.value

    def pause(self, seconds):
        self.pauses.append(seconds)
        self.value += seconds

    def now(self):
        return datetime(2026, 9, 26, tzinfo=module.ET) + timedelta(seconds=self.value)


def daily_rows(symbol):
    rows = [dict(code='WRONG', time_key='2026-08-26 00:00:00', **dict.fromkeys(module.FIELDS, 'MUST_NOT_PARSE'))]
    for index, day in enumerate(module.DAYS):
        rows.append(dict(code='US.' + symbol, time_key=day + ' 00:00:00', open=100 + index,
                         high=101 + index, low=99 + index, close=100.5 + index, volume=780))
    return rows + [dict(code='WRONG', time_key='2026-09-25 00:00:00',
                        **dict.fromkeys(module.FIELDS, 'MUST_NOT_PARSE'))]


class Context:
    def __init__(self, clock):
        self.clock, self.calls, self.closed = clock, [], False
        self.own_used, self.reject_all, self.reject_rth = 0, False, False
        self.fail_symbol, self.fail_unsubscribe = None, False
        self.rows = {symbol: daily_rows(symbol) for symbol in module.SYMBOLS}

    def note(self, name, *args):
        self.calls.append((name, self.clock(), args))

    def query_subscription(self, **kwargs):
        self.note('quota', kwargs)
        return 0, {'own_used': self.own_used, 'own_option_used_quota': 0}

    def subscribe(self, *args, **kwargs):
        self.note('subscribe', args, kwargs)
        failed = self.reject_all if kwargs['session'] == 'ALL' else self.reject_rth
        return (-1, 'subscription denied') if failed else (0, None)

    def get_cur_kline(self, code, count, **kwargs):
        self.note('current', code, count, kwargs)
        if code == self.fail_symbol:
            return -1, 'synthetic unavailable'
        return 0, self.rows[code.removeprefix('US.')]

    def unsubscribe(self, *args):
        self.note('unsubscribe', *args)
        return (-1, 'synthetic unsubscribe failure') if self.fail_unsubscribe else (0, None)

    def close(self):
        self.closed = True


def sdk(context):
    return SimpleNamespace(__version__='synthetic', OpenQuoteContext=lambda **kw: context,
        SubType=SimpleNamespace(K_DAY='K_DAY', K_5M='K_5M'), KLType=SimpleNamespace(K_DAY='K_DAY'),
        AuType=SimpleNamespace(QFQ='qfq'), Session=SimpleNamespace(ALL='ALL', RTH='RTH'))


class SourceCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root, self.out = Path(self.temp.name) / 'source', Path(self.temp.name) / 'out'
        self.root.mkdir()
        pins, coverage = {}, None
        for symbol in module.SYMBOLS:
            path = self.root / ('US.' + symbol + '.csv')
            with path.open('w', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=('code', 'time_key', *module.FIELDS))
                writer.writeheader()
                writer.writerow(dict(daily_rows(symbol)[0], time_key='2026-08-26 NOT_A_TIME'))
                for row in daily_rows(symbol)[1:-1]:
                    opening = datetime.fromisoformat(row['time_key']).replace(hour=9, minute=30)
                    for index in range(78):
                        stamp = opening + timedelta(minutes=5 * (index + 1))
                        writer.writerow(dict(row, time_key=stamp.isoformat(sep=' '), volume=10))
                writer.writerow(dict(daily_rows(symbol)[-1], time_key='2026-09-25 NOT_A_TIME'))
            pins[symbol] = sha256_file(path)
            meta = self.root / ('US.' + symbol + '.coverage.csv')
            with meta.open('w', newline='') as handle:
                writer = csv.writer(handle)
                writer.writerow(('date', 'rows', 'first_close', 'last_close', 'missing_before_or_between'))
                writer.writerows((day, 78, '09:35:00', '16:00:00', 0) for day in module.DAYS)
            coverage = sha256_file(meta)
        checksums = self.root / 'CHECKSUMS.sha256'
        checksums.write_text(''.join(sha256_file(path) + '  ' + path.name + '\n' for path in sorted(self.root.glob('*.csv'))))
        for key, value in (('PINS', pins), ('COVERAGE_SHA', coverage), ('CHECKSUM_SHA', sha256_file(checksums))):
            guard = patch.object(module, key, value)
            guard.start()
            self.addCleanup(guard.stop)
        self.clock = Clock()
        self.context = Context(self.clock)

    def capture(self):
        return module.capture(self.context, sdk(self.context), self.out, self.root,
                              now_fn=self.clock.now, clock=self.clock, pause=self.clock.pause)

    def assert_frozen(self, report):
        self.assertEqual(json.loads((self.out / 'manifest.json').read_text()), report)
        for line in (self.out / 'CHECKSUMS.sha256').read_text().splitlines():
            digest, name = line.split('  ', 1)
            self.assertEqual(hashlib.sha256((self.out / name).read_bytes()).hexdigest(), digest)
        self.assertEqual(len(list((self.out / 'raw').iterdir())), len(report['requests']))

    def test_exact_live_subscription_three_daily_calls_and_raw_sealed_boundary(self):
        report = self.capture()
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(report['errors'], [])
        self.assertEqual(report['source_equivalence'], 'unverified')
        current = [call for call in self.context.calls if call[0] == 'current']
        self.assertEqual([call[2] for call in current], [
            ('US.' + symbol, 40, {'ktype': 'K_DAY', 'autype': 'qfq'}) for symbol in module.SYMBOLS])
        sub = next(call for call in self.context.calls if call[0] == 'subscribe')
        self.assertEqual(sub[2], ((['US.XLV', 'US.XLI', 'US.XLY'], ['K_DAY', 'K_5M']),
                                 {'subscribe_push': False, 'session': 'ALL'}))
        unsub = self.context.calls[-1]
        self.assertEqual(unsub[0], 'unsubscribe')
        self.assertGreaterEqual(unsub[1] - sub[1], 61 - 1e-9)
        self.assertEqual(unsub[2], (['US.XLV', 'US.XLI', 'US.XLY'], ['K_DAY', 'K_5M']))
        self.assertTrue(all(value <= 30 for value in self.clock.pauses))
        self.assertTrue(all(b[1] - a[1] >= 3.1 - 1e-9 for a, b in zip(self.context.calls, self.context.calls[1:])))
        for symbol, value in report['comparisons'].items():
            self.assertEqual(list(value['daily']), list(module.DAYS))
            self.assertEqual(value['history_levels_as_of'], '2026-09-25')
            self.assertTrue(all(field['equal'] == 20 for field in value['summary'].values()))
            self.assertTrue(all(field['equal'] for field in value['levels'].values()))
            self.assertEqual(value['outside_window_timestamps'], ['2026-08-26 00:00:00', '2026-09-25 00:00:00'])
        self.assertNotIn('MUST_NOT_PARSE', (self.out / 'manifest.json').read_text())
        self.assertTrue(any('MUST_NOT_PARSE' in path.read_text() for path in (self.out / 'raw').iterdir()))
        self.assert_frozen(report)

    def test_one_rth_fallback_is_recorded_and_last_attempt_controls_cleanup(self):
        self.context.reject_all = True
        report = self.capture()
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(report['subscription_session'], 'RTH')
        self.assertTrue(report['extended_hours_unavailable'])
        calls = [call for call in self.context.calls if call[0] == 'subscribe']
        self.assertEqual([call[2][1]['session'] for call in calls], ['ALL', 'RTH'])
        self.assertGreaterEqual(self.context.calls[-1][1] - calls[-1][1], 61 - 1e-9)
        self.assertEqual(sum(not record['ok'] for record in report['requests']), 1)
        self.assert_frozen(report)

    def test_both_subscription_failures_stop_without_daily_and_still_cleanup(self):
        self.context.reject_all = self.context.reject_rth = True
        report = self.capture()
        self.assertEqual(report['status'], 'incomplete')
        self.assertEqual([call[0] for call in self.context.calls], ['quota', 'subscribe', 'subscribe', 'unsubscribe'])
        self.assert_frozen(report)

    def test_occupied_connection_never_subscribes_or_unsubscribes(self):
        self.context.own_used = 1
        report = self.capture()
        self.assertEqual(report['status'], 'incomplete')
        self.assertEqual([call[0] for call in self.context.calls], ['quota'])
        self.assert_frozen(report)

    def test_failure_stops_batch_keeps_partial_raw_and_never_retries(self):
        self.context.fail_symbol = 'US.XLI'
        report = self.capture()
        self.assertEqual(report['status'], 'incomplete')
        self.assertEqual(list(report['comparisons']), ['XLV'])
        self.assertEqual([call[2][0] for call in self.context.calls if call[0] == 'current'], ['US.XLV', 'US.XLI'])
        self.assertTrue(any('synthetic unavailable' in path.read_text() for path in (self.out / 'raw').iterdir()))
        self.assert_frozen(report)

    def test_price_and_level_differences_are_kept_without_fitted_scaling(self):
        self.context.rows['XLV'][-2]['high'] += 2
        self.context.rows['XLV'][-2]['volume'] += 100
        report = self.capture()
        result = report['comparisons']['XLV']
        self.assertEqual(result['price_scaling'], 'none')
        self.assertEqual(result['daily'][module.DAYS[-1]]['high']['difference'], 2)
        self.assertEqual(result['summary']['high']['equal'], 19)
        self.assertEqual(result['daily'][module.DAYS[-1]]['volume']['difference'], 100)
        self.assertFalse(result['levels']['yesterday_high']['equal'])
        self.assertFalse(result['levels']['atr']['equal'])
        self.assertEqual(module.comparison(0, 0)['relative_error'], None)

    def test_daily_missing_duplicate_bad_ohlc_and_cap_are_not_silently_repaired(self):
        for kind in ('missing', 'duplicate', 'ohlc', 'over_cap'):
            with self.subTest(kind=kind):
                rows = daily_rows('XLV')
                if kind == 'missing': del rows[3]
                elif kind == 'duplicate': rows.insert(3, dict(rows[3]))
                elif kind == 'ohlc': rows[3]['close'] = 999
                else: rows *= 2
                if kind == 'over_cap':
                    self.context.rows['XLV'] = rows
                    result = self.capture()
                    self.assertEqual(result['status'], 'incomplete')
                    self.assertEqual(len([call for call in self.context.calls if call[0] == 'current']), 1)
                else:
                    with self.assertRaises(ValueError): module.current_history(rows, 'XLV')

    def test_local_missing_duplicate_or_invalid_ohlc_rejected_and_sealed_skipped(self):
        path = self.root / 'US.XLV.csv'
        original = path.read_text()
        first = original.splitlines()[2]
        for data in (original.replace(first + '\n', '', 1), original.replace(first, first + '\n' + first, 1),
                     original.replace('100.5,10', '999,10', 1)):
            with self.subTest(data=data[:30]):
                path.write_text(data)
                with self.assertRaises(ValueError): module.local_history(path, 'XLV')
        path.write_text(original)
        self.assertEqual(len(module.local_history(path, 'XLV')), 20)

    def test_input_pin_failure_prevents_every_api_call_and_overwrite_refused(self):
        (self.root / 'US.XLI.coverage.csv').write_text('changed')
        report = self.capture()
        self.assertEqual(report['status'], 'incomplete')
        self.assertEqual(self.context.calls, [])
        self.assert_frozen(report)
        with self.assertRaises(FileExistsError): self.capture()

    def test_cli_always_closes_owned_connection_and_prints_no_prices(self):
        fake = sdk(self.context)
        with patch.dict(sys.modules, {'futu': fake}), patch.object(module, 'capture', side_effect=RuntimeError('synthetic failure')):
            with self.assertRaisesRegex(RuntimeError, 'synthetic failure'):
                module.main(['--out', str(self.out)])
        self.assertTrue(self.context.closed)
        self.context.closed = False
        stdout = io.StringIO()
        with patch.dict(sys.modules, {'futu': fake}), patch.object(module, 'capture', return_value={
                'status': 'completed', 'comparisons': dict.fromkeys(module.SYMBOLS)}), contextlib.redirect_stdout(stdout):
            self.assertEqual(module.main(['--out', str(self.out)]), 0)
        self.assertTrue(self.context.closed)
        self.assertEqual(stdout.getvalue(), 'status=completed compared_symbols=3\n')


if __name__ == '__main__':
    unittest.main()
