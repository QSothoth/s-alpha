import contextlib
import io
import json
import tempfile
import unittest
import warnings
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

from studies.trader_replication import runner
from studies.trader_replication.tests.test_runner import panel, system
from studies.trader_screens import scan


class PresentationTests(unittest.TestCase):
    def test_official_cn_limit_up_is_also_skipped_in_intraday_diff(self):
        from studies import trader_data
        from studies.trader_replication import systems
        from studies.trader_screens import intraday
        p = panel()
        p['codes'] = np.array(['SH.600001', 'SH.600002', 'SH.600003'])
        p['close'][-2, 1], p['close'][-1, 1] = 10.15, 11.17
        p.update(raw_close=p['close'].astype(np.float32), volume=np.full(p['close'].shape, 1e6),
                 turnover=np.full(p['close'].shape, 1e8), digest='cn-source')
        day = str(p['days'][-1])
        trader = dict(id='toy', name='Toy', last_day=day, wanted=[], sells=[], holdings=[],
                      buys=[dict(code='SH.600002', day=day, side=1, setup='brk', price=11.17, stop=10.15)])
        ds = SimpleNamespace(id='cn-source', panel=lambda: p, names=lambda: {})
        with mock.patch.object(trader_data, 'dataset', return_value=ds), \
                mock.patch.object(systems, 'board', return_value=[SimpleNamespace(id='toy')]), \
                mock.patch.object(runner, 'run', return_value=trader), \
                mock.patch.object(scan.data, 'industries', return_value={}):
            official = scan.run('cn', 'frozen')
        self.assertTrue(official['traders'][0]['buys'][0]['limit_up'])
        self.assertEqual(intraday.diff(deepcopy(official), official)['buys']['missed'], [])

    def test_account_history_ends_at_reported_equity_and_day(self):
        p = panel()
        result = runner.run(system(p, str(p['days'][-1])), 'us')
        history = result['equity_history']
        self.assertEqual(history['days'], p['days'][-61:].tolist())
        self.assertEqual(history['days'][-1], result['last_day'])
        self.assertEqual(history['values'][-1], result['account']['ret'] + 1)
        self.assertTrue(all(value > 0 for value in history['values']))

    def test_history_stops_at_requested_day_and_rejects_missing_values(self):
        days = np.array(['2026-10-01', '2026-10-02', '2026-10-03'])
        self.assertEqual(runner.bounded_history(days, [10., 11., 99.], days[1]),
                         dict(days=days[:2].tolist(), values=[10., 11.]))
        for missing in (np.nan, np.inf, 0., -1.):
            self.assertEqual(runner.bounded_history(days, [10., missing, 12.], days[-1]),
                             dict(days=[], values=[]))

    def test_rowwise_pool_index_preserves_existing_formula_and_gates(self):
        closes = np.array([[10., 20., np.nan], [11., 19., 10.], [12., np.nan, 11.], [11., 22., 12.]])
        pool = np.array([[False, False, False], [True, True, False], [True, True, True], [True, True, True]])
        cache = {}
        feature = SimpleNamespace(c=closes, rank_pool=pool)
        feature.get = lambda key, fn: cache[key] if key in cache else cache.setdefault(key, fn())
        previous = scan.S.lag(closes)
        with warnings.catch_warnings(), np.errstate(invalid='ignore', divide='ignore'):
            warnings.simplefilter('ignore', RuntimeWarning)
            returns = np.where(pool & np.isfinite(previous), closes / previous - 1, np.nan)
            expected = np.cumprod(1 + np.nan_to_num(np.nanmean(returns, axis=1)))
        np.testing.assert_array_equal(scan.pool_index(feature), expected)
        for period in (20, 50):
            original = (expected[:, None] > scan.S.ema(expected[:, None], period))[:, 0]
            np.testing.assert_array_equal(scan.index_above(feature, period), original)

    def test_scan_cli_writes_source_only_presentation_json(self):
        from studies import trader_data
        from studies.trader_replication import systems

        p = panel()
        trader = system(p, str(p['days'][-1]))
        report = runner.run(trader, 'us')
        p.update(volume=np.full(p['close'].shape, 1e6), turnover=np.full(p['close'].shape, 1e8),
                 raw_close=p['close'].copy(), digest='toy-source')
        p['close'][-2, 1] = np.nan
        report['wanted'].append(dict(code='US.UNKNOWN', side=1))
        ds = SimpleNamespace(id='toy-dataset', panel=mock.Mock(return_value=p),
                             names=mock.Mock(return_value={'US.T1': 'Source company'}))
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(trader_data, 'dataset', return_value=ds), \
                mock.patch.object(systems, 'board', return_value=[trader]), \
                mock.patch.object(runner, 'run', return_value=deepcopy(report)), \
                mock.patch.object(scan.data, 'industries', return_value={'US.T1': 'Source industry'}), \
                mock.patch.object(scan.data, 'SCANS', Path(tmp)), \
                mock.patch.object(scan.board, 'render', return_value='test board'), \
                mock.patch.object(scan, 'show'), contextlib.redirect_stdout(io.StringIO()) as stdout:
            scan.main(['run', 'us', '--mode', 'frozen'])
            output = Path(tmp) / 'out' / f"us_{p['days'][-1]}_1d.json"
            result = json.loads(output.read_text(encoding='utf-8'))
            self.assertIn(str(output), stdout.getvalue())
        ds.panel.assert_called_once_with()
        presentation = result['presentation']
        self.assertEqual(presentation['window'], 60)
        self.assertEqual(presentation['market_curve']['days'], p['days'][-61:].tolist())
        self.assertEqual(result['traders'][0]['equity_history'], report['equity_history'])
        stocks = presentation['stocks']
        self.assertEqual(stocks['US.T1']['description'], 'Source company，所属行业为Source industry。')
        self.assertEqual(stocks['US.T1']['values'], [])
        self.assertEqual(stocks['US.UNKNOWN'], dict(days=[], values=[], description=''))
        self.assertTrue(stocks['US.T2']['values'])
        self.assertEqual(stocks['US.T2']['days'][-1], result['last_day'])
        self.assertTrue(all(len(stock['days']) <= 61 for stock in stocks.values()))


if __name__ == '__main__':
    unittest.main()
