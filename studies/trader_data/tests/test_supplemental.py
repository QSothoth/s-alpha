import csv
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from studies.trader_data import supplemental as S


class SupplementalTests(unittest.TestCase):
    def test_exact_dates_missing_values_and_frozen_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for folder, rows in (('frozen', [('2025-01-02', 10), ('2025-01-06', 999)]),
                                 ('live', [('2025-01-02', 20), ('2025-01-03', 30)])):
                path = root / folder / 'stat'
                path.mkdir(parents=True)
                with (path / 'SYN_A.csv').open('w') as stream:
                    writer = csv.writer(stream)
                    writer.writerow(['time', 'option_volume'])
                    writer.writerows(rows)
            with patch.multiple(S, ROOT=root, OPTIONS=root / 'frozen', LIVE_OPTIONS=root / 'live'):
                frozen, _ = S.option_volume(['SYN_A', 'SYN_B'], ['2025-01-02', '2025-01-03'])
                live, sources = S.option_volume(['SYN_A', 'SYN_B'], ['2025-01-02', '2025-01-03'], 'live')
            np.testing.assert_array_equal(frozen[:, 0], [10, np.nan])
            np.testing.assert_array_equal(live[:, 0], [10, 30])
            self.assertTrue(np.isnan(live[:, 1]).all())
            self.assertEqual(len(sources), 2)

    def test_benchmark_does_not_fill_a_missing_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'SYN_Q.csv').write_text('time_key,close\n2025-01-02,10\n2025-01-06,99\n')
            with patch.multiple(S, ROOT=root, BENCHMARKS=root):
                values, sources = S.benchmark('SYN_Q', ['2025-01-02', '2025-01-03'])
            np.testing.assert_array_equal(values, [10, np.nan])
            self.assertEqual(len(sources), 1)
