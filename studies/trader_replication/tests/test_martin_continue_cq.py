import unittest

from studies.trader_replication.martin_continue_cq import classify


class TraceCategoryTests(unittest.TestCase):
    def test_existing_position_is_distinguished_by_direction(self):
        self.assertEqual(classify([{'reason': 'open_pos', 'side': 1, 'held_side': 1}]), 'held_same_side')
        self.assertEqual(classify([{'reason': 'open_pos', 'side': 1, 'held_side': -1}]), 'held_opposite_side')

    def test_small_amount_and_unresolved_attempts_remain_distinct(self):
        self.assertEqual(classify([{'reason': 'open_pos', 'limits': ['gross_room']}]), 'amount_too_small:gross_room')
        self.assertEqual(classify([]), 'not_reached')
        self.assertEqual(classify([{'reason': 'a'}, {'reason': 'b'}]), 'multiple_attempts')


if __name__ == '__main__':
    unittest.main()
