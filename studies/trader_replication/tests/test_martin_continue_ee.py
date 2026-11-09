import unittest
import numpy as np
from studies.trader_replication.martin_continue_ee import fast_events


class HistoricalFastEventTests(unittest.TestCase):
    def test_exact_move_and_split_use_only_actions_that_have_occurred(self):
        days = ['2024-01-02', '2024-01-03', '2024-01-04']
        values = [100., 105., 52.5]
        a = fast_events(days, values, [('2024-01-04', .5, 0.)], np.array([0, 1, 2]))
        b = fast_events(days, values, [('2024-01-04', .5, 0.), ('2025-01-01', .1, 0.)], np.array([0, 1, 2]))
        np.testing.assert_array_equal(a, [False, True, False])
        np.testing.assert_array_equal(a, b)

    def test_missing_market_session_does_not_create_event(self):
        result = fast_events(['2024-01-02', '2024-01-04'], [100., 200.], [], np.array([0, 2]))
        np.testing.assert_array_equal(result, [False, False])

    def test_affine_cash_action_uses_action_adjusted_previous_close(self):
        result = fast_events(['2024-01-02', '2024-01-03'], [100., 99.],
                             [('2024-01-03', 1., -1.)], np.array([0, 1]))
        np.testing.assert_array_equal(result, [False, False])


if __name__ == '__main__':
    unittest.main()
