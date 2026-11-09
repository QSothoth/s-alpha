import unittest
from types import SimpleNamespace
import warnings

import numpy as np

from studies.trader_replication.martin_continue_ca import coil_fields
from studies.trader_replication.martin_continue_bv import daily_pool_book
from studies.trader_replication.martin_continue_hj import coil_fields_chunked
from studies.trader_replication.martin_strong_scan import pool_book2


class ChunkedCoilTest(unittest.TestCase):
    def test_existing_features_are_preserved_across_column_batches(self):
        values = np.arange(48 * 5, dtype=np.float32).reshape(48, 5) / 100 + 10
        values[8:11, 2] = np.nan
        data = SimpleNamespace(c=values, h=values * 1.02, l=values * .98,
                               e9=values * .99, adr=np.full_like(values, .05))
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            expected = coil_fields(data)
            actual = coil_fields_chunked(data, width=2)
        for name in expected:
            np.testing.assert_array_equal(actual[name], expected[name])

    def test_daily_candidates_match_original_complete_panel(self):
        rng = np.random.default_rng(42)
        close = rng.uniform(8, 12, (30, 7)).astype(np.float32)
        data = SimpleNamespace(c=close, h=close * 1.03, l=close * .97,
                               e9=close * .99, adr=np.full_like(close, .05))
        fields = {'lowe9': rng.uniform(-.1, .2, close.shape).astype(np.float32),
                  'cpos': rng.uniform(0, 1, close.shape).astype(np.float32),
                  'ext21': rng.uniform(0, 10, close.shape).astype(np.float32)}
        holding = rng.random(close.shape) > .3
        score = rng.random(close.shape).astype(np.float32)
        expected = pool_book2(data, fields, holding, score, True, 8., None, False)
        self.assertEqual(daily_pool_book(data, fields, holding, score), expected)


if __name__ == '__main__':
    unittest.main()
