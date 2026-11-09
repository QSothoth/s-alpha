import unittest

import numpy as np

from studies.trader_replication.martin_continue_bq import activity_ranks, chunked_roll_mean, forward_scores, training_mask
from studies.trader_replication.ticket_t4 import ranks
from studies.trader_replication.watchlist import roll_mean


class ForwardTrainingTests(unittest.TestCase):
    def test_activity_ranks_matches_existing_rank_with_missing_data_and_ties(self):
        rng = np.random.default_rng(31)
        close = rng.uniform(5, 20, (70, 13))
        close[:, 1] = close[:, 0]
        close[13, 4] = np.nan
        A = dict(close=close, high=close * 1.1, low=close * .9,
                 turnover=np.round(close) * 1e6)
        pool = rng.random(close.shape) > .1
        np.testing.assert_array_equal(activity_ranks(A, pool), ranks(A, pool))


    def test_chunked_rolling_matches_existing_formula(self):
        rng = np.random.default_rng(18)
        for dtype in (np.float32, np.float64):
            x = rng.normal(size=(50, 301)).astype(dtype)
            x[4:7, 23] = np.nan
            np.testing.assert_array_equal(chunked_roll_mean(x, 20), roll_mean(x, 20))

    def test_label_on_fit_date_is_not_available(self):
        entries = np.array([9, 10, 11])
        labels = np.array([1., 0., np.nan])
        np.testing.assert_array_equal(training_mask(entries, labels, 130), [True, False, False])

    def test_later_labels_do_not_change_earlier_scores(self):
        days = np.array([f'2024-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}' for i in range(12 * 28)] +
                        [f'2025-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}' for i in range(12 * 28)])
        d = np.arange(len(days))
        x = np.column_stack((d % 5, d % 7)).astype(np.float32) / 7
        y = (d % 3 == 0).astype(np.float32)
        first, _ = forward_scores(x, d, y, days)
        changed = y.copy()
        changed[d >= 220] = 1 - changed[d >= 220]
        second, _ = forward_scores(x, d, changed, days)
        mask = (days >= '2025-01-01') & (days <= '2025-06-30')
        np.testing.assert_array_equal(first[mask], second[mask])


if __name__ == '__main__':
    unittest.main()
