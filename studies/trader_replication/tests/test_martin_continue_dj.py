import unittest

import numpy as np

from studies.trader_replication.martin_continue_dj import update_age


class MembershipAgeTest(unittest.TestCase):
    def test_five_sessions_then_exit_and_reenter(self):
        age = np.array([-1], dtype=np.int32)
        censored = np.array([False])
        previous = np.array([False])
        for i in range(6):
            current = np.array([True])
            group = update_age(current, previous, age, censored)
            self.assertEqual(int(group[0]), 0 if i < 5 else 1)
            previous = current
        current = np.array([False])
        self.assertEqual(int(update_age(current, previous, age, censored)[0]), -1)
        self.assertEqual(int(update_age(np.array([True]), current, age, censored)[0]), 0)

    def test_panel_start_member_is_unknown_for_first_five_sessions(self):
        age = np.array([0], dtype=np.int32)
        censored = np.array([True])
        previous = np.array([True])
        for i in range(1, 6):
            group = update_age(previous, previous, age, censored)
            self.assertEqual(int(group[0]), -1 if i < 5 else 1)


if __name__ == '__main__':
    unittest.main()
