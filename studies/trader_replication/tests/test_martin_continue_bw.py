import unittest

import numpy as np

from studies.trader_replication.martin_continue_bw import positions, risk_counts


class UniverseMechanismTests(unittest.TestCase):
    def test_risk_counts_ignore_unavailable_values(self):
        days = np.array(['2024-01-02', '2024-01-03', '2024-01-04'])
        out = risk_counts(days, np.array([1., 1.6, np.nan]), np.array([1., 1., 1.]))['2024']
        self.assertEqual((out['sessions'], out['valid_both'], out['changed'], out['v1_gt_v2']), (3, 2, 1, 1))

    def test_candidate_keys_reject_duplicates(self):
        D = {'days': np.array(['2025-01-02']), 'codes': np.array(['US.A'])}
        e = ((1,), 0, 1, 10., 9., 'n1')
        with self.assertRaises(ValueError):
            positions(D, [[e, e]])


if __name__ == '__main__':
    unittest.main()
