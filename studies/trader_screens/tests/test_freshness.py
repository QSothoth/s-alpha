import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from studies import trader_data
from studies.trader_screens import scan


class FreshnessTests(unittest.TestCase):
    def setUp(self):
        refresh = mock.patch('studies.trader_options.live.refresh',
                             return_value=dict(codes=0, rows=0, earnings=0, errors=[]))
        refresh.start()
        self.addCleanup(refresh.stop)

    def test_live_json_preserves_calendar_verified_update_status(self):
        freshness = dict(market='us', last_before='2026-10-16', missing=['2026-10-19'],
                         method='snapshot', rows=3, actions=0, expected_last_day='2026-10-19',
                         last_day='2026-10-19', status='updated', checked_at='2026-10-20T00:30:00+00:00')
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(trader_data, 'dataset', return_value=SimpleNamespace(update=lambda: freshness)), \
                mock.patch.object(scan, 'run', return_value=dict(last_day='2026-10-19')), \
                mock.patch.object(scan.data, 'SCANS', Path(tmp)), \
                mock.patch.object(scan.board, 'render', return_value='board'), \
                mock.patch.object(scan, 'show'), contextlib.redirect_stdout(io.StringIO()):
            scan.main(['run', 'us'])
            output = Path(tmp) / 'out' / 'us_2026-10-19_1d.json'
            self.assertEqual(json.loads(output.read_text())['freshness'], freshness)

    def test_replay_ending_before_expected_session_is_not_written(self):
        freshness = dict(market='us', last_before='2026-10-16', missing=['2026-10-19'],
                         method='snapshot', rows=3, actions=0, expected_last_day='2026-10-19')
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(trader_data, 'dataset', return_value=SimpleNamespace(update=lambda: freshness)), \
                mock.patch.object(scan, 'run', return_value=dict(last_day='2026-10-16')), \
                mock.patch.object(scan.data, 'SCANS', Path(tmp)), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'replay ends 2026-10-16, expected 2026-10-19'):
                scan.main(['run', 'us'])
            self.assertFalse((Path(tmp) / 'out').exists())

    def test_quarantined_trade_or_holding_blocks_output_including_cached_update(self):
        for key in ('buys', 'sells', 'holdings'):
            freshness = dict(market='us', last_before='2026-10-19', missing=[], method=None, rows=0,
                             actions=0, expected_last_day='2026-10-19', last_day='2026-10-19',
                             status='current', rejected_bars=[dict(code='US.BAD', day='2026-10-19')])
            trader = dict(buys=[], sells=[], holdings=[])
            trader[key] = [dict(code='US.BAD')]
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(trader_data, 'dataset', return_value=SimpleNamespace(update=lambda: freshness)), \
                    mock.patch.object(scan, 'run', return_value=dict(last_day='2026-10-19', traders=[trader])), \
                    mock.patch.object(scan.data, 'SCANS', Path(tmp)), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, 'invalid prices affect positions or trades'):
                    scan.main(['run', 'us'])
                self.assertFalse((Path(tmp) / 'out').exists())


if __name__ == '__main__':
    unittest.main()
