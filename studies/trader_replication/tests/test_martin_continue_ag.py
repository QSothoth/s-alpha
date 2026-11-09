import unittest

import numpy as np

from studies.trader_replication.martin_continue_ag import random_list_order


class RandomListOrder(unittest.TestCase):
    def test_changes_only_ranking_within_list_and_keeps_other_entries(self):
        core = ((1., -1.), 3, 1, 10., 9., 'n1')
        one = ((2., 1., -.8), 4, 1, 20., 19., 'list', None, None, None, .5)
        two = ((2., 1., -.4), 5, 1, 30., 29., 'list', None, None, None, .5)
        book = [[core, one, two]]
        row = random_list_order(book, np.random.default_rng(7))[0]
        self.assertEqual(row[0], core)
        for before, after in zip((one, two), row[1:]):
            self.assertEqual(before[1:], after[1:])
            self.assertEqual(before[0][:-1], after[0][:-1])
            self.assertNotEqual(before[0][-1], after[0][-1])
        self.assertEqual(book[0][1], one)
