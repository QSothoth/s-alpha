import unittest

from studies.trader_replication.martin_continue_dc import STAGES, classify


class ShortFunnelTests(unittest.TestCase):
    def test_deepest_stage_must_come_from_one_day(self):
        days = [[True, True, False, False, False, False, False, False],
                [True, False, False, False, False, False, False, False]]
        self.assertEqual(classify(days), {'deepest': 'under_falling_e21', 'first_missing': 'z15_armed'})
        self.assertEqual(classify([[True] * len(STAGES)]), {'deepest': 'actual_entry', 'first_missing': None})
        self.assertEqual(classify([[False] * len(STAGES)]), {'deepest': 'none', 'first_missing': 'pool'})

    def test_rejects_non_cumulative_stage(self):
        with self.assertRaises(AssertionError):
            classify([[True, False, True, False, False, False, False, False]])


if __name__ == '__main__':
    unittest.main()
