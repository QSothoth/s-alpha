import csv
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from custody.dataset import Case, Dataset, DatasetError, default_session, write_checksums
from custody.evaluate import FillModel
from custody.marketdata import Bar
from studies.us_opening_range import replay as module
from studies.us_opening_range.signals import Signal


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.session = default_session('2026-09-18')
        self.signal = Signal('LONG', self.session.opens + timedelta(minutes=35),
                             101.0, 100.5, 99.5, 100.0, 103.0)
        self.exit = (self.session.opens + timedelta(minutes=45), 'time_limit')

    def option(self, minute, price=2.0, low=None, high=None, volume=1):
        return Bar('US.SPY260918C100000', self.session.opens + timedelta(minutes=minute),
                   price, price if high is None else high,
                   price if low is None else low, price, volume)

    def dataset(self, root):
        root.mkdir()
        (root / 'underlying').mkdir()
        (root / 'option').mkdir()
        (root / 'manifest.json').write_text(json.dumps({'dataset': root.name, 'role': 'train/custody'}))
        cases = []
        for right, direction, cp in [('CALL', 'LONG', 'C'), ('PUT', 'SHORT', 'P')]:
            code = 'US.SPY260918%s100000' % cp
            cases.append({'symbol': 'US.SPY', 'contract': code, 'trade_date': self.session.day,
                          'right': right, 'direction': direction, 'selection': 'both_sides_atm_at_open',
                          'session_close': self.session.closes.isoformat()})
            bars = [replace(self.option(36, 2), code=code),
                    replace(self.option(46, 1 if cp == 'C' else 6), code=code)]
            self.write_bars(root / 'option' / (code + '.csv'), bars)
        (root / 'cases.json').write_text(json.dumps({'cases': cases}))
        bars = [Bar('US.SPY', self.session.opens + timedelta(minutes=minute), 100, 101, 99, 100, 100)
                for minute in range(1, 391)]
        self.write_bars(root / 'underlying' / 'US.SPY.csv', bars)
        write_checksums(root)
        return root

    @staticmethod
    def write_bars(path, bars):
        with path.open('w', newline='') as handle:
            writer = csv.writer(handle)
            writer.writerow(('code', 'close_time', 'interval', 'open', 'high', 'low', 'close', 'volume'))
            for bar in bars:
                writer.writerow((bar.code, bar.close_time.isoformat(), bar.interval,
                                 bar.open, bar.high, bar.low, bar.close, bar.volume))

    def test_fill_costs_and_stress_use_later_actual_option_prints(self):
        bars = [self.option(35, 9), self.option(36, 2, 1, 3), self.option(46, 3, 2, 4)]
        primary = module.option_trade(bars, self.session, self.signal, self.exit, FillModel())
        stress = module.option_trade(bars, self.session, self.signal, self.exit,
                                     FillModel(slippage_fraction=0.5))
        self.assertEqual(primary['entry']['price'], 2.5)
        self.assertEqual(primary['exit']['price'], 2.5)
        self.assertAlmostEqual(primary['net_pnl'], -1.3)
        self.assertAlmostEqual(primary['net_return'], -1.3 / 250)
        self.assertLess(stress['net_return'], primary['net_return'])

    def test_entry_wait_limit_cannot_cross_exit_decision(self):
        for bars, exit_decision in [([self.option(38)], self.exit),
                                    ([self.option(36, volume=0)], self.exit),
                                    ([self.option(37)], (self.option(36).close_time, 'stop'))]:
            with self.subTest(bars=bars, exit_decision=exit_decision):
                trade = module.option_trade(bars, self.session, self.signal, exit_decision, FillModel())
                self.assertEqual(trade['outcome'], 'UNFILLED')
                self.assertEqual(trade['net_return'], 0)
        trade = module.option_trade([self.option(37), self.option(47, 3)], self.session,
                                    self.signal, self.exit, FillModel())
        self.assertEqual(trade['outcome'], 'COMPLETED')

    def test_pending_entry_fills_before_same_minute_stop_decision(self):
        stop = (self.option(36).close_time, 'stop')
        trade = module.option_trade([self.option(36, 2), self.option(37, 1)], self.session,
                                    self.signal, stop, FillModel())
        self.assertEqual(trade['outcome'], 'COMPLETED')
        self.assertEqual(trade['entry']['time'], stop[0].isoformat())
        self.assertAlmostEqual(trade['net_return'], -101.3 / 200)

    def test_missing_exit_is_zero_value_loss_and_does_not_use_late_print(self):
        trade = module.option_trade([self.option(36), self.option(48, 20)], self.session,
                                    self.signal, self.exit, FillModel())
        self.assertEqual(trade['outcome'], 'MISSING_EXIT')
        self.assertTrue(trade['exit']['assumed_zero_value'])
        self.assertAlmostEqual(trade['net_return'], -1.00325)
        late_exit = (self.session.closes, 'flatten')
        trade = module.option_trade([self.option(36), self.option(391, 20)], self.session,
                                    self.signal, late_exit, FillModel())
        self.assertEqual(trade['outcome'], 'MISSING_EXIT')

    def test_summary_keeps_no_signal_sessions_and_weights_dates_equally(self):
        def record(day, value, entered):
            trade = {'outcome': 'COMPLETED' if entered else 'NO_SIGNAL',
                     'net_return': value, 'entry': {'price': 1} if entered else None,
                     'direction': 'LONG' if entered else None}
            return {'trade_date': day, 'primary': trade}
        records = [record('2026-09-17', 0.2, True), record('2026-09-17', 0, False),
                   record('2026-09-18', -0.2, True)]
        result = module.summarize(records, 'primary')
        self.assertEqual(result['n_sessions'], 3)
        self.assertEqual(result['n_trades'], 2)
        self.assertAlmostEqual(result['mean_net_return'], 0)
        self.assertAlmostEqual(result['trading_day_mean_return'], -0.05)
        self.assertEqual(result['win_rate'], 0.5)
        self.assertEqual(result['payoff_ratio'], 1)
        self.assertEqual(result['worst_day'], -0.2)

    def test_rejects_single_side_multiple_strikes_and_wrong_selection(self):
        call = Case('US.SPY', 'US.SPY260918C100000', self.session.day, 'LONG', 100,
                    selection='both_sides_atm_at_open', session_close=self.session.closes.isoformat())
        put = replace(call, contract='US.SPY260918P100000', direction='SHORT')
        for cases in [[call], [call, replace(put, strike=101)],
                      [replace(call, selection='post_hoc'), put], [call, put, call],
                      [replace(call, session_close=None), replace(put, session_close=None)]]:
            with self.subTest(cases=cases), self.assertRaises(DatasetError):
                list(module.paired_sessions(SimpleNamespace(cases=cases)))

    def test_replay_uses_signal_side_even_when_other_option_wins(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self.dataset(Path(temp) / 'test-data')
            with patch.object(module, 'find_signal', return_value=self.signal), \
                    patch.object(module, 'exit_signal', return_value=self.exit):
                report = module.replay([path])
            self.assertEqual(report['verdict'], 'DIAGNOSTIC')
            self.assertEqual(len(report['candidates']), 4)
            for candidate in report['candidates'].values():
                self.assertLess(candidate['primary']['mean_net_return'], 0)
                self.assertTrue(candidate['sessions'][0]['contract'].endswith('C100000'))
                self.assertEqual(candidate['primary']['direction_counts'], {'LONG': 1, 'SHORT': 0})
            self.assertIn('studies/us_opening_range/replay.py', report['code_sha256'])
            with self.assertRaisesRegex(DatasetError, 'duplicate symbol/session'):
                module.replay([path, path])

    def test_stream_reader_keeps_current_session_and_rejects_bad_order(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self.dataset(Path(temp) / 'test-data')
            dataset = Dataset(path)
            bars = module.session_bars(dataset, 'underlying', 'US.SPY', self.session)
            self.assertEqual(len(bars), 390)
            self.assertEqual(dataset._tapes, {})
            csv_path = path / 'underlying' / 'US.SPY.csv'
            earlier = replace(bars[0], close_time=bars[0].close_time - timedelta(days=1))
            self.write_bars(csv_path, [earlier] + bars)
            self.assertEqual(len(module.session_bars(dataset, 'underlying', 'US.SPY', self.session)), 390)
            self.write_bars(csv_path, bars[:1] + bars)
            with self.assertRaisesRegex(DatasetError, 'duplicate or unordered'):
                module.session_bars(dataset, 'underlying', 'US.SPY', self.session)
            with self.assertRaisesRegex(DatasetError, 'checksum mismatch'):
                module.replay([path])

    def test_report_output_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'report.json'
            out.write_text('keep')
            with self.assertRaises(SystemExit), patch('sys.stderr'):
                module.main(['--dataset', 'unused', '--out', str(out)])
            self.assertEqual(out.read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
