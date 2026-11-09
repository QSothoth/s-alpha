import unittest
import numpy as np
from studies.trader_replication import martin_continue_fj as fj


class FirstPassageTests(unittest.TestCase):
    def test_same_bar_stop_wins_unless_target_is_reached_at_open(self):
        o = np.array([10., 10.])
        h = np.array([10.1, 20.])
        l = np.array([9.8, 8.9])
        c = np.array([10., 10.])
        status, reason, hits = fj.first_passage(o, h, l, c, 0, 9.)
        self.assertEqual((status, reason, hits), ('filled', 'stop', (False, False)))
        o[1], h[1], c[1] = 16., 16., 10.
        status, reason, hits = fj.first_passage(o, h, l, c, 0, 9.)
        self.assertEqual((status, reason, hits), ('filled', 'stop', (True, True)))

    def test_censoring_preserves_a_known_3r_and_unknown_5r(self):
        o = np.array([10., 10.])
        h = np.array([10., 13.5])
        l = np.array([9.9, 9.9])
        c = np.array([10., 10.])
        self.assertEqual(fj.first_passage(o, h, l, c, 0, 9.), ('filled', 'end_unmatured', (True, None)))
        l[1] = np.nan
        self.assertEqual(fj.first_passage(o, h, l, c, 0, 9.), ('filled', 'invalid_bar', (None, None)))

    def test_cancel_and_precision_are_not_fake_fills(self):
        o = np.array([10.])
        self.assertEqual(fj.first_passage(o, o, o, o, 0, 10.1), ('cancel', 'open_below_stop', (False, False)))
        self.assertEqual(fj.first_passage(o, o, o, o, 0, 10. - 1e-8), ('unknown', 'precision_unknown', (None, None)))

    def test_conditional_summary_does_not_label_cancellations_unknown(self):
        rows = [{'selected': True, 'status': 'cancel', 'terminal': 'open_below_stop', 'adr_bin': 1,
                 'hit3': False, 'hit5': False}]
        result = fj.group_summary(rows, True)['top4']['hit3']
        self.assertEqual((result['known'], result['unknown'], result['excluded_not_filled']), (0, 0, 1))

    def test_match_only_compares_same_day_and_adr_group(self):
        rows = [{'day_index': 0, 'adr_bin': 0, 'selected': True, 'status': 'filled', 'hit3': True},
                {'day_index': 0, 'adr_bin': 0, 'selected': False, 'status': 'filled', 'hit3': False},
                {'day_index': 0, 'adr_bin': 1, 'selected': False, 'status': 'filled', 'hit3': True},
                {'day_index': 1, 'adr_bin': 0, 'selected': True, 'status': 'filled', 'hit3': False}]
        result = fj.matched(rows, [0, 1], 'hit3', True, np.random.default_rng(0))
        self.assertEqual((result['difference'], result['paired_days'], result['top4_weight']), (1.0, 1, 1))


if __name__ == '__main__':
    unittest.main()
