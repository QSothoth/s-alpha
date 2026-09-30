import json
from datetime import datetime
from pathlib import Path
import tempfile
import unittest

from custody.models import ET
from studies.us_0dte_picks.launch_watch import build_command, validate_launch


class LaunchWatchTests(unittest.TestCase):
    def test_validation_rejects_stale_inputs_and_existing_output(self):
        now=datetime(2026,9,30,9,0,tzinfo=ET)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            candidates=root/'candidates.json'
            baselines=root/'baselines.json'
            candidates.write_text(json.dumps({'trade_date':'2026-09-29'}))
            baselines.write_text('{}')
            with self.assertRaisesRegex(ValueError,'for today'):
                validate_launch(candidates,baselines,root/'out','10:45',300,20,now)
            candidates.write_text(json.dumps({'trade_date':'2026-09-30'}))
            (root/'out').mkdir()
            with self.assertRaisesRegex(ValueError,'already exists'):
                validate_launch(candidates,baselines,root/'out','10:45',300,20,now)

    def test_command_is_bounded_and_passes_budget_limits(self):
        now=datetime(2026,9,30,9,0,tzinfo=ET)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            candidates=root/'candidates.json'
            baselines=root/'baselines.json'
            candidates.write_text(json.dumps({'trade_date':'2026-09-30'}))
            baselines.write_text('{}')
            cutoff=validate_launch(candidates,baselines,root/'out','10:45',300,20,now)
            command=build_command('watch-test',candidates,baselines,root/'out','10:45',
                                  300,20,cutoff,now,python=Path('/venv/python'))
            self.assertIn('--property=MemoryMax=512M',command)
            self.assertIn('--property=RuntimeMaxSec=6390s',command)
            self.assertEqual(command[-4:],['--budget-usd','300','--fee-reserve-usd','20'])
            self.assertNotIn('--mode',command)


if __name__=='__main__':
    unittest.main()
