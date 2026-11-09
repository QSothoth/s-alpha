import unittest

from studies.trader_replication.martin_continue_ds import volume_paths


class VolumeConventionTests(unittest.TestCase):
    def test_split_only_source_differs_from_all_actions(self):
        raw = {'2023-01-03': [100, 100, 100, 100, 100, 10000],
               '2023-01-04': [50, 50, 50, 50, 200, 10000],
               '2023-01-05': [49, 49, 49, 49, 200, 9800]}
        source = {'2023-01-03': [49, 49, 49, 49, 200, 10000],
                  '2023-01-04': [49, 49, 49, 49, 200, 10000],
                  '2023-01-05': [49, 49, 49, 49, 200, 9800]}
        result = volume_paths(raw, source, [('2023-01-04', .5, 0), ('2023-01-05', .98, 0)])['years']['2023']
        self.assertEqual(result['large']['bad'], 0)
        self.assertEqual(result['all']['bad'], 2)

    def test_zero_volume_is_invalid_and_cannot_be_anchor(self):
        bar = [10, 10, 10, 10, 100, 1000]
        zero = [10, 10, 10, 10, 0, 0]
        data = {'2023-01-03': bar, '2023-01-04': zero}
        result = volume_paths(data, data, [])['years']['2023']
        self.assertEqual(result['large']['invalid'], 1)
        self.assertEqual(result['large']['bad'], 1)


if __name__ == '__main__':
    unittest.main()
