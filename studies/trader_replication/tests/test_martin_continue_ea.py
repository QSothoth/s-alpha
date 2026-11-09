import unittest
import numpy as np
from studies.trader_replication.martin_continue_ea import LimitedDataset, raw_positions


class FakeDataset:
    id = 'fake'

    def stocks(self):
        return [{'code': 'US.A'}]

    def rule(self):
        return {'rule': 'fixed'}

    def actions(self):
        return {'US.A': [('2025-10-01', .5, 0)]}

    def rows(self):
        yield 'US.A', '2025-09-30', [10, 12, 8, 10, 100, 1000]
        yield 'US.A', '2025-10-01', [5, 6, 4, 5, 200, 1000]
        yield 'US.EXTRA', '2025-09-30', [2, 3, 1, 2, 10, 20]

    def digest(self):
        return 'source-digest'


class FullPoolTests(unittest.TestCase):
    def test_cut_dataset_limits_rows_before_panel_construction(self):
        cut = LimitedDataset(FakeDataset(), '2025-09-30')
        self.assertEqual([row[1] for row in cut.rows()], ['2025-09-30', '2025-09-30'])
        self.assertEqual(cut.actions(), FakeDataset().actions())
        self.assertNotEqual(cut.digest(), FakeDataset().digest())

    def test_raw_positions_ignore_codes_outside_fixed_universe(self):
        result = raw_positions(FakeDataset(), ['2025-09-30', '2025-10-01'], ['US.A'])
        np.testing.assert_array_equal(result[:, 0], [.5, .5])


if __name__ == '__main__':
    unittest.main()
