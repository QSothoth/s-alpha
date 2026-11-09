import unittest

import numpy as np

from studies.trader_replication.martin_continue_dn import first_retest, z1_chunks
from studies.martin_luk import replicate


class FirstRetestTest(unittest.TestCase):
    def test_break_close_then_first_touch_and_rearm(self):
        close = np.array([11., 9., 9., 9., 11., 9., 9.])[:, None]
        high = np.array([11., 11., 10., 10., 11., 11., 10.])[:, None]
        e50 = np.full_like(close, 10.)
        first, prior = first_retest(close, high, e50)
        self.assertEqual(np.flatnonzero(first[:, 0]).tolist(), [2, 6])
        self.assertEqual(prior[3, 0], 2)
        changed = high.copy()
        changed[6, 0] = 9.5
        amended, _ = first_retest(close, changed, e50)
        np.testing.assert_array_equal(first[:6], amended[:6])

    def test_missing_bar_resets_wait_and_no_unknown_retest(self):
        close = np.array([11., 9., 9., 9., 11., 9., 9.])[:, None]
        high = np.array([11., 11., np.nan, 10., 11., 11., 10.])[:, None]
        first, prior = first_retest(close, high, np.full_like(close, 10.))
        self.assertEqual(np.flatnonzero(first[:, 0]).tolist(), [6])
        self.assertEqual(prior[3, 0], 0)

    def test_chunked_original_z1_matches_full(self):
        rng = np.random.default_rng(17)
        close = rng.uniform(8., 12., (100, 7))
        A = {'days': np.datetime64('2024-01-01') + np.arange(100).astype('timedelta64[D]'),
             'close': close, 'open': close.copy(), 'low': close * .98, 'high': close * 1.02,
             'e9': close * .98, 'e21': close * .99, 'e50': np.full_like(close, 10.),
             'tight': np.zeros_like(close, dtype=bool)}
        pool = np.ones_like(close, dtype=bool)
        chunked, _ = z1_chunks(A, pool, block=3)
        np.testing.assert_array_equal(chunked, replicate.short_signals(A, pool)['Z1'])


if __name__ == '__main__':
    unittest.main()
