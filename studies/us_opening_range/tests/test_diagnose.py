import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from custody.dataset import DatasetError, default_session
from custody.evaluate import FillModel
from custody.marketdata import Bar
from studies.us_opening_range import diagnose as module


class AttributionTests(unittest.TestCase):
    def setUp(self):
        self.session = default_session('2026-09-18')
        self.entry_time = self.session.opens + timedelta(minutes=31)
        self.exit_time = self.entry_time + timedelta(minutes=10)
        self.fill = FillModel()
        self.underlying = {self.entry_time: Bar('US.SPY', self.entry_time, 100, 100, 100, 100, 1),
                           self.exit_time: Bar('US.SPY', self.exit_time, 101, 101, 101, 101, 1)}
        self.options = {self.entry_time: Bar('US.SPY260918C100000', self.entry_time, 2, 3, 1, 2, 1),
                        self.exit_time: Bar('US.SPY260918C100000', self.exit_time, 1.5, 2, 1, 1.5, 1)}
        self.trade = {'outcome': 'COMPLETED', 'direction': 'LONG',
                      'entry': {'time': self.entry_time.isoformat(), 'price': 2.5},
                      'exit': {'time': self.exit_time.isoformat(), 'price': 1.25,
                               'assumed_zero_value': False},
                      'net_pnl': -126.3, 'net_return': -126.3 / 250}

    def test_observed_direction_option_return_and_original_denominator_reconcile(self):
        result = module.decompose(self.trade, self.underlying, self.options, self.fill, 'LONG')
        observed = result['observed']
        self.assertAlmostEqual(observed['underlying_signed_return'], 0.01)
        self.assertEqual(observed['option_close_to_close_return'], -0.25)
        self.assertEqual(observed['category'], 'underlying_positive_option_negative')
        self.assertEqual(observed['components_dollars'],
                         {'price_movement': -50, 'slippage': -75, 'fees': -1.3})
        self.assertEqual(observed['components_original_denominator']['price_movement'], -0.2)
        self.assertAlmostEqual(sum(observed['components_original_denominator'].values()),
                               self.trade['net_return'])
        short = module.decompose(self.trade, self.underlying, self.options, self.fill, 'SHORT')
        self.assertAlmostEqual(short['observed']['underlying_signed_return'], -0.01)
        self.assertEqual(short['observed']['option_close_to_close_return'], -0.25)
        self.assertEqual(short['observed']['category'], 'underlying_negative')

    def test_missing_exit_is_unobserved_and_retained_in_all_session_reconciliation(self):
        missing = dict(self.trade, outcome='MISSING_EXIT', net_pnl=-250.65, net_return=-250.65/250,
                       exit={'time': None, 'price': 0, 'assumed_zero_value': True})
        result = module.decompose(missing, self.underlying, self.options, self.fill, 'LONG')
        self.assertIsNone(result['observed'])
        self.assertIsNone(result['missing_exit_assumption']['observed_option_return'])
        completed = module.decompose(self.trade, self.underlying, self.options, self.fill, 'LONG')
        empty = module.decompose({'outcome': 'NO_SIGNAL', 'entry': None, 'net_pnl': 0, 'net_return': 0},
                                 {}, {}, self.fill, None)
        original = {'n_trades': 2, 'mean_net_return': (missing['net_return'] + self.trade['net_return']) / 3}
        summary = module.summarize([{'primary': completed}, {'primary': result}, {'primary': empty}],
                                   'primary', original)
        self.assertEqual(summary['completed_same_times_descriptive_only']['n'], 1)
        self.assertEqual(summary['outcome_counts'], {'COMPLETED': 1, 'MISSING_EXIT': 1, 'NO_SIGNAL': 1})
        self.assertEqual(summary['original_all_session_summary'], original)
        self.assertAlmostEqual(summary['all_session_reconciliation']['original_net_pnl'], -376.95)
        self.assertAlmostEqual(summary['all_session_reconciliation']['error_dollars'], 0)

    def test_missing_exact_minute_or_changed_original_pnl_fails(self):
        with self.assertRaisesRegex(DatasetError, 'no exact observed bar'):
            module.decompose(self.trade, self.underlying, {}, self.fill, 'LONG')
        with self.assertRaisesRegex(DatasetError, 'completed net pnl'):
            module.decompose(dict(self.trade, net_pnl=1), self.underlying, self.options, self.fill, 'LONG')

    def test_output_refuses_overwrite_before_loading_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'existing.json'
            output.write_text(json.dumps({'keep': True}))
            with patch.object(module, 'diagnose') as diagnose, self.assertRaises(SystemExit):
                module.main(['--report', 'unused', '--dataset', 'unused', '--out', str(output)])
            diagnose.assert_not_called()
            self.assertEqual(json.loads(output.read_text()), {'keep': True})


if __name__ == '__main__':
    unittest.main()
