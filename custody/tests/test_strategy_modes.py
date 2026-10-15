import argparse
import contextlib
import io
import unittest
from unittest.mock import patch

from custody.registry import Registry, add_strategy_arguments
from custody import runner


class StrategyModeTests(unittest.TestCase):
    def test_mapping_preserves_identity_and_status(self):
        r = Registry()
        for mode, sid in (('selective', 'zero_dte_timing_v6.6'), ('required', 'open_hold_v3')):
            self.assertEqual(r.resolve_id(version='v6.6', strategy_mode=mode), sid)
            self.assertEqual(r.versions()['V6.6'][mode]['sha256'], r.get(sid)['sha256'])
            self.assertEqual(r.versions()['V6.6'][mode]['status'], r.get(sid)['status'])
        self.assertEqual(r.resolve_id(), r.default_id)

    def test_incomplete_and_conflicting_arguments(self):
        r = Registry()
        for kwargs in ({'version': 'V6.6'}, {'strategy_mode': 'required'},
                       {'version': 'V6.7', 'strategy_mode': 'required'},
                       {'strategy_id': r.default_id, 'version': 'V6.6', 'strategy_mode': 'selective'}):
            with self.assertRaises(ValueError):
                r.resolve_id(**kwargs)
        parser = argparse.ArgumentParser()
        add_strategy_arguments(parser)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(['--strategy', r.default_id, '--strategy-version', 'V6.6'])

    def test_invalid_mode_fails_before_market_connection(self):
        with patch.object(runner, 'OpenDMarket') as market:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                runner.main('dryrun', ['--symbol', 'US.SPY', '--direction', 'LONG',
                                       '--contract', 'US.SPY261014C700000', '--strategy-version', 'V6.6'])
            market.assert_not_called()
