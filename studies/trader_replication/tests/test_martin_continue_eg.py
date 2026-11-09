import unittest
from studies.trader_replication.martin_continue_eg import compare_panels


class PanelCutoffTests(unittest.TestCase):
    def test_upto_slices_after_future_split_adjustment(self):
        actual = compare_panels()
        self.assertEqual(actual['sliced_days'], ['2024-01-02'])
        self.assertEqual(actual['asof_days'], ['2024-01-02'])
        self.assertEqual(actual['sliced_close'], 50.)
        self.assertEqual(actual['asof_close'], 100.)


if __name__ == '__main__':
    unittest.main()
