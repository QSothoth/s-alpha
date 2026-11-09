import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from studies.trader_replication import martin_strong


class BenchmarkCoverage(unittest.TestCase):
    def test_valid_sessions_use_their_own_closes(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'US.QQQ.csv').write_text('time_key,close\n2024-01-02,100\n2024-01-03,102\n')
            with patch.object(martin_strong, 'BENCH', Path(tmp)):
                np.testing.assert_array_equal(martin_strong.bench(['2024-01-02', '2024-01-03'], 'QQQ'), [100., 102.])

    def test_missing_or_invalid_session_does_not_reuse_an_old_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'US.QQQ.csv').write_text('time_key,close\n2024-01-02,100\n2024-01-04,nan\n')
            with patch.object(martin_strong, 'BENCH', Path(tmp)):
                with self.assertRaisesRegex(ValueError, '2024-01-03'):
                    martin_strong.bench(['2024-01-02', '2024-01-03'], 'QQQ')
                with self.assertRaisesRegex(ValueError, '2024-01-04'):
                    martin_strong.bench(['2024-01-04'], 'QQQ')
