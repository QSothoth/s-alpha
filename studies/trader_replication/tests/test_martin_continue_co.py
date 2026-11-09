import unittest

import numpy as np

from studies.trader_replication.martin_continue_co import opening_and_intraday, select_four, support_best
from studies.trader_replication.martin_continue_s import support_levels
from studies.trader_replication.martin_list import ema
from studies.trader_replication.martin_strong import lag


class SupportLimitTests(unittest.TestCase):
    def test_opening_fill_intraday_and_stop_are_distinct(self):
        level = np.array([100., 100., 100., 100., 100., 100.])
        opening = np.array([95., 95., 102., 102., 102., 95.])
        low = np.array([94., 92., 99., 97., 101., 96.])
        valid, gap, intraday, survived = opening_and_intraday(level, opening, low)
        np.testing.assert_array_equal(valid, [1, 1, 1, 1, 1, 0])
        np.testing.assert_array_equal(gap, [1, 1, 0, 0, 0, 0])
        np.testing.assert_array_equal(intraday, [0, 0, 1, 1, 0, 0])
        np.testing.assert_array_equal(survived, [1, 0, 1, 0, 0, 0])

    def test_levels_match_s4_and_do_not_read_current_day(self):
        rng = np.random.default_rng(8)
        close = rng.uniform(20, 80, (45, 70)).astype(np.float32)
        high = close * 1.05
        e9 = ema(close.astype(float), 9).astype(np.float32)
        data = type('D', (), {'c': close, 'h': high, 'e9': e9})()
        levels = support_levels(data)
        previous = lag(close)
        levels = {k: np.where(np.isfinite(v) & (v > 0) & (v <= previous), v, np.nan)
                  for k, v in levels.items()}
        expected = np.fmax(np.fmax(levels['S1'], levels['S2']), levels['S3'])
        actual = support_best(close, high, e9)
        np.testing.assert_array_equal(actual, expected)
        changed = close.copy()
        changed[30:] = 10000
        changed_high = high.copy()
        changed_high[30:] = 20000
        changed_e9 = ema(changed.astype(float), 9).astype(np.float32)
        np.testing.assert_array_equal(actual[:31], support_best(changed, changed_high, changed_e9)[:31])

    def test_preselection_depends_only_on_eligible_order_and_score(self):
        order = np.ones((1, 6), dtype=bool)
        score = np.array([[.9, .8, .7, .6, .5, .4]])
        codes = np.array(['a', 'b', 'c', 'd', 'e', 'f'])
        selected = select_four(order, score, codes)
        np.testing.assert_array_equal(selected, [[1, 1, 1, 1, 0, 0]])
        self.assertEqual(int(selected.sum()), 4)


if __name__ == '__main__':
    unittest.main()
