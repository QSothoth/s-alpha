"""IE47 selection boundaries; synthetic prices are confined to these unit tests."""
import unittest
from unittest.mock import patch

import numpy as np

from studies.martin_luk import ie47_e1 as M
from studies.trader_replication import standard_indicators as S
from studies.trader_replication.tests.test_standard_indicators import synthetic


class SelectionTests(unittest.TestCase):
    def test_live_partial_option_scope_is_refused_without_changing_the_filter(self):
        arrays, q, _ = synthetic(50)
        p = {field: np.repeat(arrays[key][:, None], 2, axis=1) for key, field in
             (('o', 'open'), ('h', 'high'), ('l', 'low'), ('c', 'close'), ('v', 'volume'), ('raw_c', 'raw_close'))}
        p['volume'][:] = 1e9
        p.update(days=arrays['days'], codes=np.array(['SYN_A', 'SYN_B']))
        option = np.ones((50, 2), np.float32)
        option[-1, 1] = np.nan
        with patch.object(M.SP, 'benchmark', return_value=(q, {})), \
                patch.object(M.SP, 'option_volume', return_value=(option, {})), \
                patch.object(M, 'history_panel', side_effect=AssertionError('must not generate partial picks')):
            with self.assertRaisesRegex(ValueError, 'option_volume.*1/2'):
                M.selection(p, None, 'live', profile={'first_signal': '2024-01-02'})

    def test_live_missing_benchmark_refuses_before_generating_partial_picks(self):
        a = dict(mode='live', days=np.array(['2026-11-04']))
        with patch.object(M.SP, 'benchmark', return_value=(np.array([np.nan]), {})), \
                patch.object(M, 'selection', side_effect=AssertionError('must not compute an incomplete live list')):
            with self.assertRaisesRegex(ValueError, 'QQQ'):
                M.IE47Study().selected(a)

    def test_h4_missing_passes_but_option_missing_fails(self):
        raw = np.repeat(np.arange(100, dtype=np.float32)[:, None], 4, axis=1)
        raw[:, 0] = np.nan
        raw[99, 2] = np.nan
        passed, percentiles = M.filter_night(raw)
        self.assertEqual(np.flatnonzero(passed).tolist(), list(range(79, 99)))
        self.assertTrue(np.isnan(percentiles[:, 0]).all())

    def test_stable_ties_and_ten_night_cooldown(self):
        codes = np.array(['A', 'B', 'C', 'D'])
        rows = [np.arange(4)] * 13
        scores = [np.zeros(4, np.float32)] * 13
        picked = M.select_nights(rows, scores, codes)
        self.assertEqual(picked[0], [0, 1, 2])
        self.assertEqual(picked[1], [3])
        self.assertEqual(picked[10], [])
        self.assertEqual(picked[11], [0, 1, 2])

    def test_regime_prefix_uses_no_future_closes(self):
        q = np.r_[np.arange(100., 180.), 130., 125., 120.]
        np.testing.assert_array_equal(M.regimes(q)[:81], M.regimes(q[:81]))
        self.assertEqual(M.regimes(q)[-1], 2)

    def test_requested_indicators_equal_the_existing_full_library(self):
        arrays, q, extras = synthetic(280)
        full = S.per_stock(arrays, q, extras)
        subset = S.per_stock(arrays, q, extras, names=M.INDICATORS)
        self.assertEqual(set(subset), set(M.INDICATORS))
        for name in M.INDICATORS:
            np.testing.assert_allclose(subset[name], full[name], rtol=0, atol=0, equal_nan=True, err_msg=name)


if __name__ == '__main__':
    unittest.main()
