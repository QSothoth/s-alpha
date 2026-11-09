"""The bounded-memory D1 reconstruction agrees with the existing factor definitions."""
import datetime as dt
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from studies.trader_replication import watchlist as WL
from studies.trader_replication.martin_continue_a import required_fields
from studies.trader_replication.martin_strong import library
from studies.trader_replication.martin_strong_scan import extra
from studies.trader_replication.martin_words import words


class FactorParity(unittest.TestCase):
    def test_selected_inputs_match_existing_calculations(self):
        rng = np.random.default_rng(83)
        shape = (270, 80)
        close = (30 * np.exp(np.cumsum(rng.normal(0, .025, shape), axis=0))).astype(np.float32)
        high = close * rng.uniform(1.001, 1.05, shape).astype(np.float32)
        low = close * rng.uniform(.95, .999, shape).astype(np.float32)
        opening = close * rng.uniform(.98, 1.02, shape).astype(np.float32)
        turnover = rng.uniform(2e7, 2e8, shape).astype(np.float32)
        days = [(dt.date(2024, 1, 2) + dt.timedelta(days=i)).isoformat() for i in range(shape[0])]
        A = dict(close=close.astype(float), high=high.astype(float), low=low.astype(float),
                 turnover=turnover.astype(float), days=np.array(days))
        D = SimpleNamespace(c=close, h=high, l=low, o=opening, t=turnover, A=A, days=days,
                            raw=close, adr=WL.roll_mean(high / low - 1, 20).astype(np.float32),
                            to20=WL.roll_mean(turnover, 20).astype(np.float32),
                            rk=np.tile(np.arange(shape[1]), (shape[0], 1)))
        benchmark = np.linspace(90., 110., shape[0])
        with patch('studies.trader_replication.martin_continue_a.bench', return_value=benchmark), \
             patch('studies.trader_replication.martin_strong.bench', return_value=benchmark):
            selected = required_fields(D)
            expected = {**library(D), **extra(D), 'w_wk_above': words(A, D.rk)['wk_above'].astype(np.float32)}
        for key, value in selected.items():
            with self.subTest(key=key):
                np.testing.assert_allclose(value, expected[key], rtol=0, atol=0, equal_nan=True)


if __name__ == '__main__':
    unittest.main()
