import unittest
from studies.trader_replication.martin_continue_eb import summarize


class MembershipTraceTests(unittest.TestCase):
    def test_flags_membership_even_when_candidate_identity_is_unchanged(self):
        full = {'codes': ['US.A', 'US.B'], 'audit': {'2024-01-02': {
            'all': {'holding': [0], 'candidates': [[1, 'both', .95]]},
            'spaced': {'candidates': []}}}}
        cut = {'codes': full['codes'], 'audit': {'2024-01-02': {
            'all': {'holding': [0, 1], 'candidates': [[1, 'both', .95]]},
            'spaced': {'candidates': []}}}}
        result = summarize(full, cut)
        self.assertEqual(result[0]['differences'][0]['code'], 'US.B')
        self.assertEqual(result[0]['differences'][0]['full_candidate'], 'both')
        self.assertFalse(result[0]['differences'][0]['full_h3'])
        self.assertTrue(result[0]['differences'][0]['cut_h3'])


if __name__ == '__main__':
    unittest.main()
