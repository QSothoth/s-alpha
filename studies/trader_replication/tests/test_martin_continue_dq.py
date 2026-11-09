import csv
from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest

from studies.trader_replication.martin_continue_dq import coverage, read_csv


class InventoryTest(unittest.TestCase):
    def test_prior_warmup_does_not_use_current_or_future_bar(self):
        calendar = [(date(2023, 1, 1) + timedelta(days=i)).isoformat() for i in range(260)]
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for sub in ('daily', 'daily_none'):
                (folder / sub).mkdir()
                with (folder / sub / 'AAA.csv').open('w', newline='') as f:
                    w = csv.writer(f)
                    w.writerow(['date', 'open', 'high', 'low', 'close', 'volume', 'turnover'])
                    for day in calendar:
                        w.writerow([day, 10, 11, 9, 10, 100, 20000000])
            _, counts = coverage({'AAA': folder}, calendar)
            self.assertEqual(counts['liquid_warm'][calendar[250]], 0)
            self.assertEqual(counts['liquid_warm'][calendar[251]], 1)
            with (folder / 'daily' / 'AAA.csv').open('w', newline='') as f:
                w = csv.writer(f)
                w.writerow(['date', 'open', 'high', 'low', 'close', 'volume', 'turnover'])
                for day in calendar[:252]:
                    w.writerow([day, 10, 11, 9, 10, 100, 20000000])
            _, altered = coverage({'AAA': folder}, calendar)
            self.assertEqual(counts['liquid_warm'][calendar[251]], altered['liquid_warm'][calendar[251]])

    def test_invalid_ohlcv_does_not_count_as_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'AAA.csv'
            p.write_text('date,open,high,low,close,volume,turnover\n2023-01-03,10,9,8,10,100,1000\n')
            valid, dates = read_csv(p)
            self.assertFalse(valid)
            self.assertIn('2023-01-03', dates)


if __name__ == '__main__':
    unittest.main()
