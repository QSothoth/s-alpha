import unittest

import numpy as np

from studies.trader_replication.martin_continue_ce import first_touch
from studies.trader_replication.martin_continue_cf import prior_state


class PriorStateTests(unittest.TestCase):
    def test_only_completed_days_are_used_and_missing_resets_state(self):
        e9 = np.array([9, 11, 11, 11, 9, 11, 11, 11], float)
        e21 = np.full(e9.shape, 10.)
        low = np.array([9, 10, 10.5, 10, 9, 10, np.nan, 10])
        touch = first_touch(e9[:, None], e21[:, None], low[:, None])[:, 0]
        self.assertEqual(prior_state(e9, e21, low, touch, 2), {'state': 'waiting', 'touch_age': None})
        self.assertEqual(prior_state(e9, e21, low, touch, 4), {'state': 'touched', 'touch_age': 2})
        self.assertEqual(prior_state(e9, e21, low, touch, 7), {'state': 'unknown', 'touch_age': None})
        self.assertEqual(prior_state(e9, e21, low, touch, 5), {'state': 'not_above', 'touch_age': None})


if __name__ == '__main__':
    unittest.main()
