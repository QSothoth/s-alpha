import tempfile
import unittest
from pathlib import Path

from studies.opportunity_events.hk_southbound_dimensions import endpoints, official_count, summarize


class DimensionsTest(unittest.TestCase):
    def test_short_positions_respect_cutoff_and_missing_history(self):
        records = [{"timestamp_str": "2026-02-20", "aggregated_short": 9},
                   {"timestamp_str": "2026-02-13", "aggregated_short": 8},
                   {"timestamp_str": "2026-01-16", "aggregated_short": 10}]
        result = endpoints(records, "2026-02-15")
        self.assertEqual(result[0]["aggregated_short"], 8)
        self.assertEqual(result[4]["aggregated_short"], 10)
        self.assertIsNone(result[8])

    def test_official_short_counts_distinguish_zero_from_absence(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "2026-01-01.csv").write_text(
                "Date,Stock Code,Aggregated Reportable Short Positions (Shares)\n"
                "01/01/2026,1024,0\n")
            self.assertEqual(official_count(directory, "2026-01-01", "HK.01024"), 0)
            self.assertIsNone(official_count(directory, "2026-01-01", "HK.02513"))

    def test_turnover_does_not_use_future_observations_or_incomplete_window(self):
        event = {"code": "HK.02513", "name": "test", "signal": "2026-01-30",
                 "south": {"ratios": [5, 7], "shares": [100, 150]},
                 "o120": {"end_return": None}}
        volumes = [{"code": "HK.02513", "records": [
            {"timestamp_str": "2026-02-02", "turnover": 100, "short_sell_turnover": 90},
            {"timestamp_str": "2026-01-30", "turnover": 100, "short_sell_turnover": 10}]}]
        shorts = [{"code": "HK.02513", "records": []}]
        with tempfile.TemporaryDirectory() as directory:
            result = summarize([event], shorts, volumes, directory)[0]
        self.assertIsNone(result["short_turnover_20"])
        self.assertEqual(result["short_turnover_last_date"], "2026-01-30")
        self.assertTrue(all(v is None for v in result["short_change"].values()))


if __name__ == "__main__":
    unittest.main()
