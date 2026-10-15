"""Scanner helpers: completed weeks and suggested shares."""
from datetime import date, datetime, time, timezone
import json
from pathlib import Path
import tempfile
import unittest

from studies.trend_breakout import scan
from studies.trend_breakout.final import SCHEMES


class Scan(unittest.TestCase):
    def test_week_counts_only_after_friday_close_or_once_the_week_is_over(self):
        def done(bar, now):
            return scan.week_complete(date.fromisoformat(bar), datetime.fromisoformat(now), time(15, 30))
        self.assertTrue(done('2026-10-09', '2026-10-09 16:00'))       # Friday bar after the close
        self.assertFalse(done('2026-10-09', '2026-10-09 12:45'))      # Friday still trading
        self.assertFalse(done('2026-10-14', '2026-10-14 18:00'))      # Wednesday, same week
        self.assertTrue(done('2026-10-01', '2026-10-06 09:00'))       # holiday week, next week now

    def test_fetch_before_the_close_is_redone_after_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / '2026-10-16'
            (folder / 'cn').mkdir(parents=True)
            progress = folder / 'cn' / 'progress.json'
            after = datetime(2026, 10, 16, 8, tzinfo=timezone.utc)                     # 16:00 Shanghai
            progress.write_text(json.dumps({'done': []}))
            self.assertFalse(scan.stale(folder, 'cn', after))                           # unfinished: resume
            progress.write_text(json.dumps({'finished_utc': '2026-10-16T04:45:00+00:00'}))  # 12:45 Shanghai
            self.assertTrue(scan.stale(folder, 'cn', after))
            self.assertFalse(scan.stale(folder, 'cn', datetime(2026, 10, 16, 7, tzinfo=timezone.utc)))
            progress.write_text(json.dumps({'finished_utc': '2026-10-16T07:40:00+00:00'}))  # 15:40 Shanghai
            self.assertFalse(scan.stale(folder, 'cn', after))

    def test_suggested_shares(self):
        self.assertEqual(scan.shares_for('hk', SCHEMES['hk'], 100000, 50., 45.), 400)          # 20000 / 50
        risk = scan.shares_for('cn', SCHEMES['cn'], 100000, 10., 9.)                            # min(2% / 1, 40%)
        self.assertEqual(risk, 2000)
        self.assertEqual(scan.shares_for('cn', SCHEMES['cn'], 100000, 10., 2.) % 100, 0)
        self.assertIsNone(scan.shares_for('us', SCHEMES['us'], None, 10., 9.))


if __name__ == '__main__':
    unittest.main()
