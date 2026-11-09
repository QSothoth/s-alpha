import unittest

import numpy as np

from studies.trader_replication.martin_continue_cu import near_high, summarize


class NearHighTests(unittest.TestCase):
    def test_signal_uses_252_completed_sessions_and_ignores_today(self):
        c = np.full((260, 1), 90.)
        h = np.full((260, 1), 100.)
        self.assertIsNone(near_high(c, h, 251, 0))
        self.assertTrue(near_high(c, h, 252, 0))
        h[252:] = 1000.
        c[252:] = 1.
        self.assertTrue(near_high(c, h, 252, 0))
        h[2, 0] = 200.
        self.assertFalse(near_high(c, h, 252, 0))
        h[:252] = np.nan
        self.assertIsNone(near_high(c, h, 252, 0))

    def test_unknown_and_unmatched_days_do_not_enter_same_day_comparison(self):
        def row(day, near, quick):
            return {'day': day, 'near_high': near,
                    'outcome': {'quick': quick, 'ret': None, 'days': None, 'reason': 'end_unmatured'}}
        result = summarize([row('a', True, True), row('a', False, False), row('a', None, True), row('b', True, False)])
        self.assertEqual(result['unknown']['candidates'], 1)
        self.assertEqual(result['same_day']['days'], 1)
        self.assertEqual(result['same_day']['mean_quick_difference'], 1.)
        self.assertEqual(result['near']['final_known'], 0)


if __name__ == '__main__':
    unittest.main()
