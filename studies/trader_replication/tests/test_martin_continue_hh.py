import unittest

import numpy as np

from studies.trader_replication.martin_continue_hh import latest_for_signal


class SignalCloseAlignmentTest(unittest.TestCase):
    def test_each_signal_uses_next_row_of_prior_close_state(self):
        state = np.array([[0], [1], [2], [3]], dtype=np.int32)
        aligned = latest_for_signal(state.copy(), -1)
        self.assertEqual(aligned[:, 0].tolist(), [1, 2, 3, -1])
        state[2, 0] = 99
        self.assertEqual(latest_for_signal(state, -1)[0, 0], 1)

    def test_missing_final_signal_cannot_borrow_future_row(self):
        membership = np.array([[False, True], [True, False]])
        self.assertEqual(latest_for_signal(membership, False).tolist(),
                         [[True, False], [False, False]])


if __name__ == '__main__':
    unittest.main()
