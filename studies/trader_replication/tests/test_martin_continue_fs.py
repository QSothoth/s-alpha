import unittest
from types import SimpleNamespace
import numpy as np
from studies.trader_replication import martin_continue_fs as fs


class PriorCloseReplacementTests(unittest.TestCase):
    def test_eligibility_uses_prior_close_age_and_pending_add(self):
        positions = {0: SimpleNamespace(j=0, d0=0, side=1, fill=10.),
                     1: SimpleNamespace(j=1, d0=0, side=1, fill=10.),
                     2: SimpleNamespace(j=2, d0=4, side=1, fill=10.)}
        result = fs.choose_weak(positions, np.array([9.8, 10.1, 8.]), 5, np.array(['A', 'B', 'C']), {'A'})
        self.assertEqual((result['status'], result['weak_code'], result['eligible_count']), ('selected', 'B', 1))

    def test_missing_prior_close_makes_ranking_unknown_and_ties_use_code(self):
        positions = {0: SimpleNamespace(j=0, d0=0, side=1, fill=10.),
                     1: SimpleNamespace(j=1, d0=0, side=1, fill=10.)}
        codes = np.array(['Z', 'A'])
        self.assertEqual(fs.choose_weak(positions, np.array([np.nan, 9.9]), 5, codes, set())['status'],
                         'prior_close_unknown')
        result = fs.choose_weak(positions, np.array([9.9, 9.9]), 5, codes, set())
        self.assertEqual((result['weak_code'], result['eligible_count']), ('A', 2))


if __name__ == '__main__':
    unittest.main()
