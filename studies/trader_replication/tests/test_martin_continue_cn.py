import datetime as dt
import unittest

import numpy as np

from studies.trader_replication import watchlist
from studies.trader_replication.martin_continue_cn import prior_squeeze, prior_week_tight, rank_coil
from studies.trader_replication.martin_list import ema
from studies.trader_replication.martin_words import weekly


class CoilRankTests(unittest.TestCase):
    def test_weekly_matches_existing_lag_and_ignores_current_week(self):
        rng = np.random.default_rng(53)
        days = [(dt.date(2023, 1, 2) + dt.timedelta(days=i)).isoformat()
                for i in range(180) if (dt.date(2023, 1, 2) + dt.timedelta(days=i)).weekday() < 5]
        close = rng.uniform(15, 80, (len(days), 70)).astype(np.float32)
        high, low = close * 1.05, close * .95
        high[30:35, 0] = np.nan
        data = {'days': np.array(days), 'close': close, 'high': high, 'low': low}
        _, wh, wl, indexes = weekly(data)
        with np.errstate(all='ignore'):
            ratios = (wh / wl - 1) / watchlist.roll_mean(wh / wl - 1, 10)
        targets = [1, 40, 80, 100, 115]
        expected = np.full((len(targets), close.shape[1]), np.nan)
        for i, target in enumerate(targets):
            idx = indexes[target - 1]
            if idx >= 0:
                expected[i] = ratios[idx]
        np.testing.assert_array_equal(prior_week_tight(data, targets), expected.astype(np.float32))
        changed = dict(data, high=high.copy(), low=low.copy())
        changed['high'][100:] *= 9
        changed['low'][100:] *= .1
        np.testing.assert_array_equal(prior_week_tight(data, [100]), prior_week_tight(changed, [100]))

    def test_daily_squeeze_and_priority_use_previous_data(self):
        rng = np.random.default_rng(9)
        c = rng.uniform(10, 100, (40, 70)).astype(np.float32)
        e9, e21 = (ema(c.astype(float), n).astype(np.float32) for n in (9, 21))
        adr = np.full(c.shape, .05, dtype=np.float32)
        targets = [15, 30]
        expected = np.abs(e9[np.array(targets) - 1] / e21[np.array(targets) - 1] - 1) / adr[np.array(targets) - 1]
        np.testing.assert_allclose(prior_squeeze(c, e9, adr, targets), expected, equal_nan=True)
        day = 30
        fields = {key: np.ones_like(c) for key in ('act20', 'stay250', 'fast250')}
        names = np.array([0, 1, 2])
        codes = np.array([f'{j:03}' for j in range(70)])
        active = np.ones(70, bool)
        squeeze = np.ones(70, dtype=np.float32)
        tight = np.ones(70, dtype=np.float32)
        a = rank_coil(names, active, fields, squeeze, tight, day, codes)
        for value in fields.values():
            value[day:] = 999
        b = rank_coil(names, active, fields, squeeze, tight, day, codes)
        np.testing.assert_array_equal(a, b)
        self.assertCountEqual(a, names)


if __name__ == '__main__':
    unittest.main()
