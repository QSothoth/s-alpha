"""Legacy dataset folders for the board: a folder built with another list rule is never used.  The panel itself
(bad bars, cache by digest, symlinks) is tested in studies/trader_data/tests."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from studies.trader_screens import data as D


class FolderTests(unittest.TestCase):
    def test_folder_with_another_list_rule_is_not_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, flt in (('2026-10-15', {'min_price': 5.0, 'min_avg_turnover_20d': 5e7}),
                              ('2026-10-14', D.UNIVERSE['us'])):
                (root / name / 'us').mkdir(parents=True)
                (root / name / 'us' / 'universe.json').write_text(json.dumps({'filter': flt}), encoding='utf-8')
            with mock.patch.object(D, 'SCANS', root / 'none'), mock.patch.object(D, 'TREND', root), \
                    mock.patch.object(D, 'DATASET', root / 'missing'):
                self.assertEqual(D.latest_folder('us'), root / '2026-10-14')


if __name__ == '__main__':
    unittest.main()
