import unittest

import numpy as np

from studies.trader_replication.martin_continue_ct import prior_age, simulate_candidate, stats


class ScannerEventTests(unittest.TestCase):
    def test_scan_age_is_known_at_previous_close(self):
        self.assertIsNone(prior_age(-1, 50))
        self.assertEqual(prior_age(49, 50), 0)
        self.assertEqual(prior_age(29, 50), 20)
        self.assertEqual(prior_age(28, 50), 21)

    def test_stop_day_never_uses_ambiguous_high_as_quick_win(self):
        o = np.array([10., 10.])
        h = np.array([10., 14.])
        l = np.array([10., 8.])
        c = np.array([10., 11.])
        ema = np.array([9., 9.])
        r = simulate_candidate(o, h, l, c, ema, 0, 10., 9., cost=0.)
        self.assertEqual(r['reason'], 'stop')
        self.assertFalse(r['quick'])
        self.assertAlmostEqual(r['ret'], -.1)

    def test_unknown_tail_and_prior_confirmed_quick_event_are_distinct(self):
        o = np.array([10., 10., 10.])
        h = np.array([10., 13.5, np.nan])
        l = np.array([10., 9.5, 9.5])
        c = np.array([10., 12., 10.])
        ema = np.array([9., 9., 9.])
        r = simulate_candidate(o, h, l, c, ema, 0, 10., 9., cost=0.)
        self.assertTrue(r['quick'])
        self.assertIsNone(r['ret'])
        self.assertEqual(r['reason'], 'invalid_bar')
        r = simulate_candidate(o[:1], h[:1], l[:1], c[:1], ema[:1], 0, 10., 9., cost=0.)
        self.assertIsNone(r['quick'])
        self.assertIsNone(r['ret'])

    def test_completed_120_days_charges_both_trade_costs(self):
        o = np.full(121, 10.)
        h = np.full(121, 10.1)
        l = np.full(121, 9.9)
        c = np.full(121, 10.)
        ema = np.full(121, 9.)
        r = simulate_candidate(o, h, l, c, ema, 0, 10., 9.)
        self.assertEqual(r['reason'], 'time')
        self.assertFalse(r['quick'])
        self.assertAlmostEqual(r['ret'], -.001)

    def test_same_day_comparison_does_not_include_unmatched_dates(self):
        rows = [dict(day='a', age=0, outcome={'quick': True, 'ret': .1, 'days': 1, 'reason': 'ema21'}),
                dict(day='a', age=None, outcome={'quick': False, 'ret': -.1, 'days': 1, 'reason': 'stop'}),
                dict(day='b', age=0, outcome={'quick': False, 'ret': -.1, 'days': 1, 'reason': 'stop'})]
        s = stats(rows, 'age')
        self.assertEqual(s['same_day']['days'], 1)
        self.assertEqual(s['same_day']['mean_quick_difference'], 1.)


if __name__ == '__main__':
    unittest.main()
