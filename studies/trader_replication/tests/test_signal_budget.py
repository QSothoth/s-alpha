import unittest

from studies.trader_replication.mainleg import signal_coverage_budget


class SignalBudgetTests(unittest.TestCase):
    def setUp(self):
        self.calendar = [f'2025-01-{i+1:02d}' for i in range(28)]
        self.leg = dict(key='A', code='A', first=8, peak=20, gain=1., top=20.)
        self.opens = {'A': [10.]*28}

    def measure(self, picks, K=3, legs=None, ranks=None, cooldown=10):
        return signal_coverage_budget(picks, ranks, legs or [self.leg],
                                      self.calendar, self.opens, K, cooldown)

    def test_width_uses_own_ranks_and_stable_ties(self):
        picks = {7: ['B', 'A', 'C', 'D']}
        ranks = {7: dict(A=1, B=1, C=0, D=3)}
        self.assertEqual(self.measure(picks, K=2, ranks=ranks)['picks'][7], ['C', 'B'])
        self.assertEqual(self.measure(picks, K=2, ranks=ranks)['total']['covered'], 0)
        self.assertEqual(self.measure(picks, ranks=ranks)['total']['covered'], 1)
        self.assertEqual(len(self.measure(picks, K=None)['picks'][7]), 4)

    def test_previous_ten_sessions_and_skips_do_not_renew(self):
        picks = {t: ['A', 'B', 'C', 'D'] for t in range(12)}
        out = self.measure(picks, K=1)
        self.assertEqual(out['picks'][0], ['A'])
        self.assertEqual(out['picks'][1], ['B'])
        self.assertEqual(out['picks'][10], [])
        self.assertEqual(out['picks'][11], ['A'])
        self.assertEqual(self.measure({0: ['A'], 11: ['A']}, K=1)['picks'][11], ['A'])

    def test_short_supply_and_empty_nights_are_not_filled(self):
        out = self.measure({6: ['A', 'A'], 7: [], 8: ['B']})
        self.assertEqual(out['picks'], {6: ['A'], 7: [], 8: ['B']})
        self.assertEqual(out['total']['mean_new_names'], 2/3)
        self.assertEqual(out['total']['unique_names'], 2)

    def test_larger_budget_can_cool_a_name_before_its_qualifying_window(self):
        picks = {0: ['B', 'A'], 4: ['A']}
        self.assertEqual(self.measure(picks, K=1)['total']['covered'], 1)
        self.assertEqual(self.measure(picks, K=2)['total']['covered'], 0)

    def test_first_minus_three_and_peak_minus_one_are_inclusive(self):
        for night, expected in ((3, 0), (4, 1), (18, 1), (19, 0)):
            with self.subTest(night=night):
                self.assertEqual(self.measure({night: ['A']})['total']['covered'], expected)

    def test_half_remaining_is_inclusive_and_later_add_cannot_reset_gain(self):
        self.opens['A'][8] = 20/1.5
        self.assertEqual(self.measure({7: ['A']})['total']['covered'], 1)
        self.opens['A'][8] += .001
        leg = dict(self.leg, entries=[dict(index=8, gain=1.), dict(index=9, gain=.2)])
        self.assertEqual(self.measure({7: ['A']}, legs=[leg])['total']['covered'], 0)

    def test_cross_year_hits_group_by_first_and_cooldown_carries_across_year(self):
        self.calendar = ['2024-12-27', '2024-12-30', '2024-12-31',
                         '2025-01-02', '2025-01-03', '2025-01-06', '2025-01-07']
        leg = dict(self.leg, first=3, peak=6)
        out = self.measure({2: ['A'], 3: ['A']}, legs=[leg])
        self.assertEqual(out['annual']['2025']['covered'], 1)
        self.assertEqual(out['annual']['2024']['precision_hits'], 1)
        self.assertEqual(out['picks'][3], [])
        self.assertEqual(out['per_leg'][0]['first_hit']['fill_day'], '2025-01-02')

    def test_leg_peaking_in_next_year_keeps_its_first_year_denominator(self):
        self.calendar = ['2024-12-27', '2024-12-30', '2024-12-31',
                         '2025-01-02', '2025-01-03', '2025-01-06', '2025-01-07']
        out = self.measure({3: ['A']}, legs=[dict(self.leg, first=2, peak=6)])
        self.assertEqual(out['annual']['2024']['covered'], 1)
        self.assertEqual(out['annual']['2025']['n'], 0)
        self.assertEqual(out['annual']['2025']['precision_hits'], 1)

    def test_overlap_precision_counts_one_nomination_and_missing_open_misses(self):
        out = self.measure({7: ['A', 'B']}, legs=[self.leg, dict(self.leg, key='A2')])
        self.assertEqual(out['total']['covered'], 2)
        self.assertEqual(out['total']['precision'], .5)
        self.opens['A'][8] = float('nan')
        self.assertEqual(self.measure({7: ['A']})['total']['covered'], 0)

    def test_unordered_input_and_invalid_budget_are_rejected(self):
        with self.assertRaises(ValueError):
            self.measure({7: {'A'}})
        with self.assertRaises(ValueError):
            self.measure({7: ['A']}, K=0)


if __name__ == '__main__':
    unittest.main()
