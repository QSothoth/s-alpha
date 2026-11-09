import unittest
from studies.trader_replication.martin_continue_fu import path_outcome


class FollowStopTest(unittest.TestCase):
    def setUp(self):
        self.days = [f'd{i:02}' for i in range(22)]
        self.bars = {day: (100., 101., 99., 100.) for day in self.days}
        self.bars['d00'] = (100., 101., 89., 95.)

    def result(self, multiplier=3):
        return path_outcome(self.days, self.bars, 'd00', 90., multiplier)

    def test_next_day_target_and_stop_order(self):
        self.bars['d01'] = (100., 140., 85., 100.)
        self.assertEqual(self.result()[0], 'hit')
        self.bars['d01'] = (100., 140., 79., 100.)
        self.assertEqual(self.result(), ('ambiguous', 'same_day_both'))
        self.bars['d01'] = (79., 140., 78., 100.)
        self.assertEqual(self.result(), ('miss', 'gap_wide_stop'))

    def test_opening_target_precedes_low(self):
        self.bars['d01'] = (141., 142., 79., 100.)
        self.assertEqual(self.result(), ('hit', 'gap_target'))

    def test_day_zero_wide_stop_and_unknown(self):
        self.bars['d00'] = (100., 101., 79., 95.)
        self.assertEqual(self.result(), ('miss', 'entry_wide_stop'))
        self.bars['d00'] = (100., 101., 80., 95.)
        self.assertEqual(self.result(), ('unknown', 'wide_precision'))

    def test_censor_and_missing_bar(self):
        self.assertEqual(path_outcome(self.days[:10], self.bars, 'd00', 90., 3), ('unknown', 'unmatured'))
        del self.bars['d01']
        self.assertEqual(self.result(), ('unknown', 'missing_bar'))

    def test_day_zero_high_does_not_become_post_stop_hit(self):
        self.bars['d00'] = (100., 150., 89., 95.)
        self.assertEqual(self.result(), ('miss', 'horizon'))


if __name__ == '__main__':
    unittest.main()
