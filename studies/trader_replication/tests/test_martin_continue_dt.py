import csv
from pathlib import Path
import tempfile
import unittest

from studies.trader_replication.martin_continue_dt import EarlyHistory, early_rows


class Base:
    def stocks(self):
        return [{'code': 'US.A', 'name': 'A'}, {'code': 'US.B', 'name': 'B'}]

    def rows(self):
        yield 'US.A', '2023-01-03', [3, 3, 3, 3, 3, 3]

    def actions(self):
        return {'US.A': [('2023-01-03', .5, 0)]}


class EarlyDatasetTests(unittest.TestCase):
    def test_splice_uses_only_registered_early_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'daily_none').mkdir()
            path = folder / 'daily_none/A.csv'
            def write(overlap):
                with path.open('w', newline='') as f:
                    w = csv.writer(f)
                    w.writerow(['date', 'open', 'high', 'low', 'close', 'volume', 'turnover'])
                    for day, value in [('2022-09-28', 1), ('2022-09-29', 2), ('2023-01-03', overlap)]:
                        w.writerow([day] + [value] * 6)
            write(4)
            adapter = EarlyHistory(Base(), {'US.A': folder}, 'test')
            before = list(adapter.rows())
            write(99)
            self.assertEqual(before, list(adapter.rows()))
            self.assertEqual([row[1] for row in before], ['2022-09-29', '2023-01-03'])
            self.assertEqual(before[1][2][3], 3)
            self.assertEqual(adapter.actions(), Base().actions())
            self.assertEqual([s['code'] for s in adapter.stocks()], ['US.A'])

    def test_empty_source_does_not_invent_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'empty.csv'
            path.write_text('date,open,high,low,close,volume,turnover\n')
            self.assertEqual(list(early_rows(path)), [])


if __name__ == '__main__':
    unittest.main()
