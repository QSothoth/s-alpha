import unittest

from studies.trader_replication.martin_continue_ch import fold_counts


class FoldAuditTests(unittest.TestCase):
    def test_training_outside_a_fold_includes_future_dates(self):
        dates = ['2024-03-01', '2025-02-01', '2025-10-01', '2026-08-01']
        folds = fold_counts(dates)
        self.assertEqual((folds[0]['train_before'], folds[0]['test_rows'], folds[0]['train_after']), (0, 1, 3))
        self.assertEqual((folds[1]['train_before'], folds[1]['test_rows'], folds[1]['train_after']), (1, 1, 2))
        self.assertEqual((folds[-1]['train_before'], folds[-1]['test_rows'], folds[-1]['train_after']), (3, 1, 0))


if __name__ == '__main__':
    unittest.main()
