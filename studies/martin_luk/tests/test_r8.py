"""R8 helpers: point-in-time eligibility counting and 5-minute file slot mapping."""
import csv
import gzip
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from studies.martin_luk import fetch_r8, intraday as I


def trading_days(start, n):
    d, out = date.fromisoformat(start), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


class Eligible(unittest.TestCase):
    def test_a_volatile_uptrend_counts_and_a_flat_stock_does_not(self):
        days = trading_days('2023-06-01', 400)
        up = []
        for k in range(400):
            c = 10 * 1.004 ** k
            up.append([c, c * 1.03, c * .97, c, 5e6, 5e7])      # 6% daily range, $50M turnover
        flat = [[10, 10.1, 9.9, 10, 5e6, 5e7] for _ in range(400)]
        self.assertGreater(fetch_r8._eligible_days(days, up, []), 100)
        self.assertEqual(fetch_r8._eligible_days(days, flat, []), 0)


class K5Slots(unittest.TestCase):
    def test_bar_end_times_land_in_their_slots(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'X.csv.gz'
            with gzip.open(path, 'wt', newline='') as fh:
                w = csv.writer(fh)
                w.writerow(('time_key', 'open', 'high', 'low', 'close', 'volume', 'turnover'))
                w.writerow(('2024-01-02 09:35:00', 1, 2, .5, 1.5, 10, 15))
                w.writerow(('2024-01-02 16:00:00', 3, 4, 2.5, 3.5, 20, 70))
                w.writerow(('2024-01-03 09:40:00', 5, 6, 4.5, 5.5, 30, 165))
            arr = np.full((6, 1, 2, I.NB), np.nan, np.float32)
            I._k5_into(arr, 0, path, {'2024-01-02': 0, '2024-01-03': 1})
            self.assertEqual(arr[3, 0, 0, 0], 1.5)
            self.assertEqual(arr[3, 0, 0, 77], 3.5)
            self.assertEqual(arr[5, 0, 1, 1], 165)
            self.assertEqual(int(np.isfinite(arr[3]).sum()), 3)


if __name__ == '__main__':
    unittest.main()
