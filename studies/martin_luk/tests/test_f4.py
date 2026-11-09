"""Observable F4 opportunity consumption, support and admission checks."""
from io import StringIO
import unittest

import numpy as np

from studies.martin_luk import f4_research as F


class F4Tests(unittest.TestCase):
    def step(self, state, day, **changes):
        values = dict(upgrade=False, survives=True, high=10., decline=False, action=False,
                      qualified=np.zeros((3, 1), bool), admissible=np.ones((3, 1), bool))
        values.update(changes)
        for key in ('upgrade', 'survives', 'high', 'decline', 'action'):
            values[key] = np.array([values[key]])
        return F.state_step(state, day, **values)[0][:, 0]

    def test_first_pullback_and_one_consumption(self):
        state = F.initial_state(1)
        self.assertFalse(self.step(state, 0, upgrade=True, decline=True, action=True).any())
        yes = np.ones((3, 1), bool)
        self.assertTrue(self.step(state, 1, high=9., decline=True, qualified=yes).sum() == 0)
        self.assertTrue(self.step(state, 2, high=9.5, action=True).all())
        self.assertFalse(self.step(state, 3, high=9.8, decline=True, action=True, qualified=yes).any())
        self.assertFalse(self.step(state, 4, high=11., decline=True, action=True, qualified=yes).any())
        self.assertTrue(self.step(state, 5, high=10., decline=True, action=True, qualified=yes).all())

    def test_reentry_in_leader_rank_cannot_reset_spent_pullback(self):
        state = F.initial_state(1)
        self.step(state, 0, upgrade=True)
        self.step(state, 1, decline=True, action=True)
        self.assertFalse(self.step(state, 2, upgrade=True, decline=True, action=True,
                                   qualified=np.ones((3, 1), bool)).any())

    def test_first_recovery_without_support_or_liquidity_still_consumes(self):
        for qualified, admitted in ((False, True), (True, False)):
            state = F.initial_state(1)
            self.step(state, 0, upgrade=True)
            self.assertFalse(self.step(state, 1, high=9., decline=True, action=True,
                qualified=np.full((3, 1), qualified), admissible=np.full((3, 1), admitted)).any())
            self.assertFalse(self.step(state, 2, high=9.5, decline=True, action=True,
                                       qualified=np.ones((3, 1), bool)).any())

    def test_breaking_trend_clears_pending_support(self):
        state = F.initial_state(1)
        self.step(state, 0, upgrade=True)
        self.step(state, 1, decline=True, qualified=np.ones((3, 1), bool))
        self.step(state, 2, survives=False)
        self.step(state, 3, upgrade=True)
        self.assertFalse(self.step(state, 4, decline=True, action=True).any())

    def test_same_support_price_cannot_count_twice(self):
        args = [np.array([10.]), np.array([10.5]), np.array([10.]), np.array([1.])]
        count = F.support_counts(*args, [np.array([10.]), np.array([10.]), np.array([10.3])])
        self.assertEqual(count.item(), 2)
        self.assertEqual(F.support_counts(*args, [np.array([9.4])]).item(), 0)
        self.assertEqual(F.support_counts(*args, [np.array([10.6])]).item(), 0)
        below = [args[0], np.array([9.9]), *args[2:]]
        self.assertEqual(F.support_counts(*below, [np.array([10.])]).item(), 0)

    def test_precision_is_unique_code_night_and_coverage_keeps_half_gain(self):
        days, codes = ['2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05'], ['X']
        p = dict(c=np.array([[10.], [14.], [16.], [20.]]), h=np.array([[11.], [15.], [18.], [21.]]))
        legs = [dict(code='X', key='a', first=0, first_date=days[0], peak=3, peak_date=days[3], top=20., gain=1.),
                dict(code='X', key='b', first=1, first_date=days[1], peak=3, peak_date=days[3], top=20., gain=1.)]
        mask = np.array([[True], [True], [False], [True]])
        result = F.mask_metrics(mask, days, codes, p, legs, [], StringIO(), 'test')['years']['2024']
        self.assertEqual(result['triggers'], 3)
        self.assertEqual(result['hits'], 2)
        self.assertEqual(result['early_hits'], 1)
        self.assertEqual(result['coverage'], 2)
        self.assertEqual(result['forward']['incomplete'], 3)
        self.assertIsNone(result['big_rate'])

    def test_list_gate_requires_lift_and_both_year_coverages(self):
        def result(p, c24=5, c25=11):
            return dict(years={'all': dict(precision=p), '2024': dict(coverage=c24),
                               '2025': dict(coverage=c25)})
        r = dict(F3_list=result(.01), V1=result(.03), V2=result(.1, c24=4), V3=result(.029))
        self.assertEqual(F.gate(r)['eligible'], ['V1'])


if __name__ == '__main__':
    unittest.main()
