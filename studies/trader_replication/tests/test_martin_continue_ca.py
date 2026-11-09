import unittest
from types import SimpleNamespace
from unittest.mock import patch
import warnings

import numpy as np

from studies.trader_replication.martin_continue_bv import daily_name_score
from studies.trader_replication.martin_continue_ca import coil_fields
from studies.trader_replication.martin_list import ema
from studies.trader_replication.martin_strong import library
from studies.trader_replication.martin_strong_scan import HOLD, name_score


class ConsolidationScoreTests(unittest.TestCase):
    def test_compact_fields_match_existing_library(self):
        rng = np.random.default_rng(5)
        close = rng.uniform(10, 100, (260, 16)).astype(np.float32)
        high, low = close * np.float32(1.03), close * np.float32(.97)
        data = SimpleNamespace(c=close, h=high, l=low, o=close, t=close * 1e6,
                               adr=np.full(close.shape, .06, dtype=np.float32),
                               to20=close * 1e6, days=list(range(len(close))))
        data.e9 = ema(close.astype(float), 9).astype(np.float32)
        with patch('studies.trader_replication.martin_strong.bench', return_value=np.full(len(close), 100.)), warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            reference = library(data)
        actual = coil_fields(data)
        np.testing.assert_array_equal(actual['nsq'], -reference['squeeze'])
        np.testing.assert_array_equal(actual['nr10'], -reference['range10'])

    def test_score_matches_original_and_never_reads_same_day_fields(self):
        rng = np.random.default_rng(7)
        fields = {key: rng.normal(size=(6, 16)).astype(np.float32)
                  for group in HOLD['H4'] for key in group}
        mask = np.ones((6, 16), dtype=bool)
        data = SimpleNamespace(c=np.zeros(mask.shape))
        score = daily_name_score(fields, mask, HOLD['H4'])
        np.testing.assert_array_equal(score, name_score(data, fields, mask, HOLD['H4']))
        fields['nsq'][3] = fields['nsq'][3, ::-1]
        fields['nr10'][3] = fields['nr10'][3, ::-1]
        changed = daily_name_score(fields, mask, HOLD['H4'])
        np.testing.assert_array_equal(score[:4], changed[:4])
        self.assertFalse(np.array_equal(score[4], changed[4]))


if __name__ == '__main__':
    unittest.main()
