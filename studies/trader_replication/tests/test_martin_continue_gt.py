import unittest
from copy import deepcopy

from studies.trader_replication.martin_continue_gt import behavioral_quantiles, flatten_fidelity, joint_pass


class TestBehavioralComparison(unittest.TestCase):
    def setUp(self):
        self.base = {'account': {'by_year': {'2024': 1., '2025': .4, '2026': .5},
                                 'maxdd': .3, 'win': .2, 'payoff': 8.},
                     'fidelity': {'strict': 5, 'strict26': 2, 'board': 5, 'peak': 5, 'peak2025': 2}}

    def test_joint_gate_requires_every_year_and_behavior(self):
        self.assertTrue(joint_pass(self.base, self.base))
        changed = deepcopy(self.base)
        changed['account']['by_year']['2025'] = .39
        self.assertFalse(joint_pass(changed, self.base))
        changed = deepcopy(self.base)
        changed['fidelity']['peak2025'] = 1
        self.assertFalse(joint_pass(changed, self.base))
        changed = deepcopy(self.base)
        changed['account']['payoff'] = None
        self.assertFalse(joint_pass(changed, self.base))

    def test_count_ties_and_sum_only_real_window_counts(self):
        profile = {'strict': 5, 'strict26': 2, 'board': 5, 'prepeak_ten_day':
                   {'2024': {'held': 2}, '2025': {'held': 2}, '2026': {'held': 1}}}
        self.assertEqual(flatten_fidelity(profile)['peak'], 5)
        result = behavioral_quantiles({'strict': 2}, [{'strict': 0}, {'strict': 2}, {'strict': 3}])
        self.assertEqual((result['strict']['greater'], result['strict']['equal'], result['strict']['less']), (1, 1, 1))
