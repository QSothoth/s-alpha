import csv
from datetime import date, timedelta
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from custody.dataset import DatasetError, default_session, sha256_file, write_bars, write_checksums
from custody.marketdata import Bar
from studies.us_opening_range import pricing_replay as module


class PricingTests(unittest.TestCase):
    def setUp(self):
        self.session = default_session('2026-09-18')
        self.history = [((date(2026, 9, 18) - timedelta(days=i)).isoformat(), 0.0) for i in range(20, 0, -1)]

    def bar(self, minute, price=1, low=None, high=None, volume=10):
        return Bar('US.SPY260918C100000', self.session.opens + timedelta(minutes=minute),
                   price, high if high is not None else price, low if low is not None else price,
                   price, volume)

    def test_observation_exact_threshold_fee_units_and_causality(self):
        spot = [self.bar(30, 101), self.bar(31, 999)]
        options = {d: [self.bar(30, .387), self.bar(31, 999)] for d in ('LONG', 'SHORT')}
        observation = module.observe(spot, options, self.history, self.session, 100)
        self.assertTrue(observation['eligible'])
        self.assertEqual(1.0, observation['M'])
        self.assertEqual(.8, observation['P'])
        self.assertFalse(observation['passes_price_filter'])
        changed = {d: [bars[0], self.bar(31, 5000)] for d, bars in options.items()}
        self.assertEqual(observation, module.observe(spot[:1], changed, self.history, self.session, 100))
        spot[0] = self.bar(30, 101.01)
        self.assertTrue(module.observe(spot, options, self.history, self.session, 100)['passes_price_filter'])

    def test_common_admission_missing_history_quotes_volume_and_half_day(self):
        options = {d: [self.bar(30)] for d in ('LONG', 'SHORT')}
        self.assertFalse(module.observe([self.bar(30, 100)], options, self.history[:-1], self.session, 100)['eligible'])
        for bars in ([self.bar(29), self.bar(31)], [self.bar(30, volume=0)], [self.bar(30, price=0)]):
            with self.subTest(bars=bars):
                result = module.observe([self.bar(30, 100)], {**options, 'SHORT': bars}, self.history, self.session, 100)
                self.assertEqual(['MISSING_1000_PUT'], result['reasons'])
        half = default_session(self.session.day, self.session.opens.replace(hour=13, minute=0).isoformat())
        self.assertIn('NON_REGULAR_SESSION', module.observe([self.bar(30, 100)], options, self.history, half, 100)['reasons'])
        for history in (self.history + [(self.session.day, 0)], self.history[:-1] + [self.history[0]]):
            with self.assertRaisesRegex(ValueError, 'strictly before'):
                module.observe([self.bar(30, 100)], options, history, self.session, 100)

    def test_two_legs_actual_paid_denominator_and_both_slippage_costs(self):
        options = {'LONG': [self.bar(30, 99), self.bar(31, 2, 1, 3), self.bar(376, 3, 2, 4)],
                   'SHORT': [self.bar(30, 99), self.bar(32, 4, 3, 5), self.bar(377, 5, 4, 6)]}
        primary = module.group_trade(options, self.session, True, module.FILLS['primary'])
        stress = module.group_trade(options, self.session, True, module.FILLS['stress'])
        self.assertEqual('COMPLETED', primary['outcome'])
        self.assertEqual(700, primary['paid_premium'])
        self.assertAlmostEqual(-2.6, primary['proxy_net_pnl'])
        self.assertAlmostEqual(-2.6/700, primary['proxy_net_return'])
        self.assertAlmostEqual(-202.6/800, stress['proxy_net_return'])
        self.assertEqual(primary['observed_net_return'], primary['proxy_net_return'])
        self.assertEqual(self.bar(31).close_time.isoformat(), primary['legs']['CALL']['entry']['time'])
        self.assertEqual(self.bar(32).close_time.isoformat(), primary['legs']['PUT']['entry']['time'])

    def test_partial_waits_until_1002_then_exits_1003_or_1004_only(self):
        for entry in (31, 32):
            for exit_minute in (33, 34):
                with self.subTest(entry=entry, exit=exit_minute):
                    options = {'LONG': [self.bar(entry, 2), self.bar(exit_minute, 3), self.bar(376, 999)],
                               'SHORT': [self.bar(33, 1), self.bar(376, 999)]}
                    trade = module.group_trade(options, self.session, True, module.FILLS['primary'])
                    self.assertEqual('PARTIAL_ENTRY', trade['outcome'])
                    self.assertEqual(self.bar(32).close_time.isoformat(), trade['cancel_unfilled_leg_at'])
                    self.assertEqual(self.bar(exit_minute).close_time.isoformat(), trade['legs']['CALL']['exit']['time'])
                    self.assertIsNone(trade['legs']['PUT']['entry'])
                    self.assertAlmostEqual(98.7/200, trade['proxy_net_return'])

    def test_missing_exits_are_unknown_observed_and_assumed_loss_without_sell_fee(self):
        cases = [({'LONG': [self.bar(31, 2), self.bar(35, 9)], 'SHORT': []}, 1, -200.65, 200),
                 ({'LONG': [self.bar(31, 2), self.bar(378, 9)],
                   'SHORT': [self.bar(31, 1), self.bar(376, 1)]}, 1, -201.95, 300),
                 ({'LONG': [self.bar(31, 2)], 'SHORT': [self.bar(32, 1)]}, 2, -301.3, 300)]
        for options, missing, pnl, paid in cases:
            with self.subTest(missing=missing, paid=paid):
                trade = module.group_trade(options, self.session, True, module.FILLS['primary'])
                self.assertEqual(missing, trade['missing_exit_legs'])
                self.assertIsNone(trade['observed_net_pnl'])
                self.assertIsNone(trade['observed_net_return'])
                self.assertAlmostEqual(pnl, trade['proxy_net_pnl'])
                self.assertAlmostEqual(pnl/paid, trade['proxy_net_return'])
                self.assertTrue(trade['legs']['CALL']['exit']['assumed_zero_value'])
        # A real, valid exit bar clipped to zero remains an executed proxy exit.
        options = {'LONG': [self.bar(31, 2), self.bar(33, 1, 0, 5)], 'SHORT': []}
        trade = module.group_trade(options, self.session, True, module.FILLS['stress'])
        self.assertEqual(0, trade['missing_exit_legs'])
        self.assertAlmostEqual(-201.3, trade['observed_net_pnl'])
        self.assertFalse(trade['legs']['CALL']['exit']['assumed_zero_value'])

    def test_unfilled_and_no_signal_are_zero_without_fees(self):
        options = {d: [self.bar(30), self.bar(31, volume=0), self.bar(33)] for d in ('LONG', 'SHORT')}
        for emit, outcome in ((True, 'UNFILLED'), (False, 'NO_SIGNAL')):
            trade = module.group_trade(options, self.session, emit, module.FILLS['primary'])
            self.assertEqual(outcome, trade['outcome'])
            self.assertEqual(0, trade['paid_premium'])
            self.assertEqual(0, trade['proxy_net_pnl'])

    def test_history_stream_is_bounded_prior_only_and_handles_missing_target_day(self):
        start = date(2026, 7, 1)
        days = [(start+timedelta(days=i)).isoformat() for i in range(26)]
        def rows(path, symbol):
            for index, day in enumerate(days):
                if index == 22:  # A target date absent from k5 still gets its prior window.
                    continue
                bars = [self.bar(i, 100) for i in range(78)]
                bars[74] = self.bar(74, 100 + index)
                yield day, symbol, bars if index != 1 else None, 'short_session' if index == 1 else None
        with patch.object(module, 'iter_days', side_effect=rows):
            history, coverage = module.prior_histories([('US.SPY', days[22]), ('US.SPY', days[24])], '/synthetic')
        first = history['US.SPY', days[22]]
        self.assertEqual(20, len(first))
        self.assertEqual(days[2], first[0][0])
        self.assertEqual(days[21], first[-1][0])
        self.assertAlmostEqual(.21, first[-1][1])
        self.assertTrue(all(day < days[24] for day, _ in history['US.SPY', days[24]]))
        self.assertEqual(1, coverage['US.SPY']['short_session'])

    def test_summary_resamples_original_dates_and_includes_single_leg_and_zero_days(self):
        records = []
        days = [(date(2026, 8, 18)+timedelta(days=i)).isoformat() for i in range(21)]
        for index, day in enumerate(days):
            trade = module.group_trade({'LONG': [self.bar(31, 2), self.bar(33, 3)], 'SHORT': []},
                                       self.session, index == 0, module.FILLS['primary'])
            records.append({'trade_date': day, 'observation': {'eligible': True, 'reasons': []}, 'primary': trade})
        result = module.summarize(records, 'primary')
        self.assertEqual((21, 21, 1), (result['n_sessions'], result['n_days'], result['n_trades']))
        self.assertEqual(10, len(result['halves']['early']['dates']))
        self.assertEqual(11, len(result['halves']['late']['dates']))
        self.assertEqual(days[9], result['halves']['early']['dates'][-1])
        self.assertAlmostEqual(result['mean_trade_return']/21, result['mean_all_sessions_return'])
        self.assertEqual(2000, result['bootstrap']['draws'])
        self.assertGreater(result['bootstrap']['undefined_trade_draws'], 0)
        self.assertEqual(result, module.summarize(records, 'primary'))
        for record in records:
            record['primary']['entered_legs'] = 0
            record['primary']['proxy_net_return'] = 0
        self.assertEqual(2000, module.summarize(records, 'primary')['bootstrap']['undefined_trade_draws'])

    def test_proxy_status_primary_pf_and_stress_mean_not_stress_pf(self):
        summary = dict(n_trades=1, trading_days=1, mean_trade_return=.1, net_mean_lower_95_bp=1,
                       profit_factor=1.3, positive_profit_without_losses=False,
                       halves={'early': {'mean_trade_return': .1}, 'late': {'mean_trade_return': .1}})
        status, gates = module.candidate_status(summary, {**summary, 'profit_factor': .9})
        self.assertEqual('UNCONFIRMED_PROXY', status)
        self.assertFalse(gates['at_least_60_trading_days'])
        self.assertFalse(gates['at_least_100_trades'])
        self.assertEqual('FAILED_PROXY', module.candidate_status({**summary, 'profit_factor': 1.1}, summary)[0])
        self.assertEqual('FAILED_PROXY', module.candidate_status(summary, {**summary, 'mean_trade_return': 0})[0])
        self.assertEqual('NO_EVIDENCE', module.candidate_status({**summary, 'n_trades': 0}, summary)[0])

    def fixture(self, root):
        pins = {}
        for name, day, symbol in ((list(module.PINS)[0], '2026-09-17', 'SPY'),
                                  (list(module.PINS)[1], '2026-09-18', 'QQQ')):
            path, session = root/name, default_session(day)
            path.mkdir()
            cases = []
            for cp, right in (('C', 'CALL'), ('P', 'PUT')):
                code = 'US.' + symbol + day[2:].replace('-', '') + cp + '100000'
                bars = [Bar(code, session.opens + timedelta(minutes=i), price, price, price, price, 10)
                        for i, price in ((30, 1), (31, 1), (376, 1.1))]
                write_bars(path/'option'/(code+'.csv'), bars)
                cases.append(dict(symbol='US.'+symbol, contract=code, trade_date=day, right=right,
                                  selection='both_sides_atm_at_open', session_close=session.closes.isoformat()))
            write_bars(path/'underlying'/('US.'+symbol+'.csv'), [
                Bar('US.'+symbol, session.opens+timedelta(minutes=i), 100, 100, 100, 100, 10) for i in range(1,391)])
            (path/'cases.json').write_text(json.dumps({'cases': cases}))
            manifest = {'dataset': name, 'role': 'train/custody'}
            if name == list(module.PINS)[1]:
                manifest['series'] = [{'csv': str(p.relative_to(path)), 'sha256': {'csv': sha256_file(p)}}
                                      for p in path.rglob('*') if p.is_file()]
            (path/'manifest.json').write_text(json.dumps(manifest))
            pin = 'CHECKSUMS.sha256' if name == list(module.PINS)[0] else 'manifest.json'
            write_checksums(path)
            pins[name] = (pin, sha256_file(path/pin))
        path = root/'preopen-us-k5-valid-v1'
        (path/'k5').mkdir(parents=True)
        (path/'manifest.json').write_text(json.dumps({'name': path.name}))
        for symbol in ('SPY','QQQ'):
            with (path/'k5'/(symbol+'.csv')).open('w', newline='') as fh:
                writer = csv.writer(fh)
                writer.writerow(('time_key','open','high','low','close','volume'))
                for offset in range(50):
                    day = date(2026,8,1)+timedelta(days=offset)
                    if day.weekday()>4:
                        continue
                    session = default_session(day.isoformat())
                    for index in range(1,79):
                        price = 103 if index == 75 else 100
                        writer.writerow(((session.opens+timedelta(minutes=5*index)).strftime('%Y-%m-%d %H:%M:%S'),
                                         price,price,price,price,10))
        write_checksums(path)
        pins[path.name] = ('CHECKSUMS.sha256', sha256_file(path/'CHECKSUMS.sha256'))
        return pins

    def test_synthetic_pinned_pipeline_and_corruption_fail_fast(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pins = self.fixture(root)
            tape_pin = ('CHECKSUMS.sha256', sha256_file(root/'custody-eval-2026-09-18-v2'/'CHECKSUMS.sha256'))
            with patch.object(module, 'DATA', root), patch.object(module, 'PINS', pins), \
                    patch.object(module, 'V2_TAPE_PIN', tape_pin), \
                    patch.object(module, 'EXPECTED_COUNTS', (2,2,2)):
                result = module.replay()
                self.assertEqual('DIAGNOSTIC_ONLY', result['verdict'])
                self.assertIsNone(result['selected_for_further_testing'])
                source = result['inputs'][1]
                self.assertEqual('manifest.json', source['pinned_by'])
                self.assertEqual(pins['custody-eval-2026-09-18-v2'][1], source['fingerprint'])
                self.assertEqual(tape_pin, (source['tape_pinned_by'], source['tape_fingerprint']))
                for candidate in module.CANDIDATES:
                    self.assertEqual(2, result['candidates'][candidate]['primary']['n_trades'])
                    self.assertEqual(2, len(result['candidates'][candidate]['sessions']))
                original = module.session_bars
                def broken(dataset, kind, code, session):
                    if kind == 'option':
                        raise DatasetError('invalid session row: future malformed OHLC')
                    return original(dataset, kind, code, session)
                with patch.object(module, 'session_bars', side_effect=broken), \
                        self.assertRaisesRegex(DatasetError, 'future malformed'):
                    module.replay()
                def no_trades(dataset, kind, code, session):
                    if kind == 'option':
                        raise DatasetError('no traded option bars: ' + code)
                    return original(dataset, kind, code, session)
                with patch.object(module, 'session_bars', side_effect=no_trades):
                    unavailable = module.replay()
                self.assertEqual(2, unavailable['candidates']['P20_125']['primary']['counts']['INELIGIBLE'])
                self.assertEqual('NO_EVIDENCE', unavailable['P20_125_status'])
                with patch.object(module, 'V2_TAPE_PIN', ('CHECKSUMS.sha256', 'bad')), \
                        self.assertRaisesRegex(ValueError, 'option tape fingerprint'):
                    module.load_inputs()
                bad_manifest_pins = {**pins, 'custody-eval-2026-09-18-v2': ('manifest.json', 'bad')}
                with patch.object(module, 'PINS', bad_manifest_pins), \
                        self.assertRaisesRegex(ValueError, 'input fingerprint'):
                    module.load_inputs()
                (root/'preopen-us-k5-valid-v1'/'k5'/'SPY.csv').write_text('corrupt')
                with self.assertRaisesRegex(ValueError, 'history checksum'):
                    module.load_inputs()
                with patch.object(module, 'PINS', {name:(pin, 'bad') for name,(pin,digest) in pins.items()}), \
                        self.assertRaisesRegex(ValueError, 'fingerprint'):
                    module.load_inputs()

    def test_prereg_and_existing_output_stop_before_data_access(self):
        with patch.object(module, 'PREREG_SHA256', 'changed'), patch.object(module, 'load_inputs') as load, \
                self.assertRaisesRegex(ValueError, 'preregistration'):
            module.replay()
        load.assert_not_called()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'report.json'
            path.write_text('untouched')
            with patch.object(module, 'replay') as replay, patch('sys.stderr', io.StringIO()), self.assertRaises(SystemExit):
                module.main(['--out', str(path)])
            replay.assert_not_called()
            self.assertEqual('untouched', path.read_text())


if __name__ == '__main__':
    unittest.main()
