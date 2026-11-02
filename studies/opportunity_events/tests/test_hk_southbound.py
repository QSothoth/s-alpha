import unittest
from datetime import date, timedelta

from studies.opportunity_events.hk_southbound import (accumulation_cadence, candidate_peaks,
                                                      outcomes, rebound_path, signal)


class SouthboundReviewTest(unittest.TestCase):
    def test_cadence_does_not_turn_missing_weeks_into_a_zero_change(self):
        bars = [[str(date(2024, 1, 1) + timedelta(days=i)), 1, 1, 1, 1, 1]
                for i in range(22)]
        holdings = {bars[i][0]: (v, 1, "rank") for i, v in [(0, 100), (6, 110),
                                                             (20, 120), (21, 130)]}
        result = accumulation_cadence(bars, holdings, [bars[0][0], bars[6][0], bars[-1][0]])
        self.assertEqual(result["weeks"], {"positive": 2, "flat": 0, "negative": 0, "missing": 2})
        self.assertEqual(result["observations"], 4)

    def test_signal_uses_two_monthly_increases_and_pullback_has_a_date(self):
        bars = [[str(date(2020, 1, 1) + timedelta(days=i)), 100, 100, 100, 100, 1]
                for i in range(80)]
        for i in range(1, 63):
            bars[i][2] = 100 - i * 0.5
        bars[63][2] = 50
        for row in bars[64:]:
            row[1:3] = [50, 50]
        bars[65][2] = 60
        bars[66][2] = 53
        shares = 6_000_000_000
        self.assertEqual(candidate_peaks(bars, shares)[0]["first_half"], bars[63][0])
        holdings = {row[0]: (100_000_000 + i * 1_000_000, 3 + i * 0.05)
                    for i, row in enumerate(bars)}
        found = signal(bars, holdings, bars[0][0])
        self.assertEqual(found["index"], 63)
        self.assertTrue(found["similar"])
        path = outcomes(bars, found["index"], horizon=4)
        self.assertAlmostEqual(path["first_pullback"]["peak_return"], 0.2)
        self.assertEqual(path["first_pullback"]["date"], bars[66][0])
        bounce = rebound_path(bars, found["index"], horizon=4)
        self.assertEqual(bounce["peak_date"], bars[65][0])
        self.assertAlmostEqual(bounce["rebound"], 0.2)
        self.assertEqual(bounce["pullback_date"], bars[66][0])
        del holdings[bars[31][0]]
        self.assertIsNone(signal(bars[:65], holdings, bars[0][0])["index"])

    def test_future_dividend_does_not_change_past_signal_or_return(self):
        bars = [[str(date(2020, 1, 1) + timedelta(days=i)), 100, 100, 100, 100, 1]
                for i in range(80)]
        for i in range(1, 63):
            bars[i][2] = 100 - i * 0.5
        bars[63][2] = 50
        for row in bars[64:]:
            row[1:3] = [50, 50]
        bars[65][2] = 60
        bars[66][2] = 53
        holdings = {row[0]: (100_000_000 + i * 1_000_000, 3 + i * 0.05)
                    for i, row in enumerate(bars)}
        action = [(bars[79][0], 1.0, -10.0)]
        for row in bars[:79]:
            row[1] -= 10
            row[2] -= 10
        found = signal(bars, holdings, bars[0][0], action)
        self.assertEqual(found["index"], 63)
        path = outcomes(bars, found["index"], horizon=4, actions=action)
        self.assertEqual(path["entry"], 50)
        self.assertAlmostEqual(path["first_pullback"]["peak_return"], 0.2)

    def test_future_dividend_cannot_create_a_past_50_percent_drop(self):
        bars = [[str(date(2020, 1, 1) + timedelta(days=i)), 100, 100, 100, 100, 1]
                for i in range(80)]
        for i in range(1, 63):
            bars[i][2] = 100 - i * 0.5
        bars[63][2] = 55
        for row in bars[64:]:
            row[1:3] = [50, 50]
        holdings = {row[0]: (100_000_000 + i * 1_000_000, 3 + i * 0.05)
                    for i, row in enumerate(bars)}
        actions = [(bars[79][0], 1.0, -10.0)]
        for row in bars[:79]:
            row[1] -= 10
            row[2] -= 10
        self.assertEqual(signal(bars, holdings, bars[0][0], actions)["index"], 64)

    def test_share_split_in_holding_window_is_unknown(self):
        bars = [[str(date(2020, 1, 1) + timedelta(days=i)), 100, 100, 100, 100, 1]
                for i in range(65)]
        for i in range(1, 63):
            bars[i][2] = 100 - i * 0.5
        bars[63][2] = 50
        holdings = {row[0]: (100_000_000 + i * 1_000_000, 3 + i * 0.05)
                    for i, row in enumerate(bars)}
        actions = [(bars[31][0], 0.5, 0.0)]
        found = signal(bars, holdings, bars[0][0], actions)
        self.assertIsNone(found["index"])
        self.assertGreater(found["missing"], 0)


if __name__ == "__main__":
    unittest.main()
