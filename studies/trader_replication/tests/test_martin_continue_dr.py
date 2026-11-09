import unittest

from studies.trader_replication.martin_continue_dr import adjusted_compare, raw_compare


class CachedDataComparisonTests(unittest.TestCase):
    def test_raw_comparison_counts_missing_and_field_changes(self):
        bar = [10, 11, 9, 10, 100, 1000]
        changed = [10, 11, 9, 10.1, 100, 1000]
        result = raw_compare({'2023-01-03': bar, '2023-01-04': bar},
                             {'2023-01-03': changed, '2023-01-05': bar})
        self.assertEqual(result['source_only'], 1)
        self.assertEqual(result['frozen_only'], 1)
        self.assertEqual(result['close_bad'], 1)
        self.assertEqual(result['open_bad'], 0)

    def test_adjustment_compares_paths_not_constant_scales(self):
        raw = {'2023-01-03': [10, 10, 10, 10, 100, 1000],
               '2023-01-04': [5, 5, 5, 5, 200, 1000]}
        qfq = {'2023-01-03': [10, 10, 10, 10, 150, 1000],
               '2023-01-04': [10, 10, 10, 10, 150, 1000]}
        matching = adjusted_compare(raw, qfq, [('2023-01-04', .5, 0)])
        self.assertEqual(matching['2023_close_bad'], 0)
        self.assertEqual(matching['2023_volume_bad'], 0)
        missing_action = adjusted_compare(raw, qfq, [])
        self.assertEqual(missing_action['2023_close_bad'], 1)
        self.assertEqual(missing_action['2023_volume_bad'], 1)

    def test_invalid_raw_close_cannot_create_adjustment(self):
        bad = {'2023-01-03': [10, 10, 10, float('nan'), 100, 1000]}
        self.assertEqual(adjusted_compare(bad, bad, [])['invalid_raw_close'], 1)


if __name__ == '__main__':
    unittest.main()
