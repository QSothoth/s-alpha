"""Expiry-bucket and ATM-pair selection for the execution capture (no network)."""
import unittest

from studies.us_0dte_picks.exec_capture import atm_pair, choose_expiries


class SelectionTests(unittest.TestCase):
    def test_buckets_pick_the_listed_expiry_closest_to_each_target(self):
        listed = ['2026-10-26', '2026-10-27', '2026-10-28', '2026-10-30', '2026-11-06', '2026-11-09',
                  '2026-11-20', '2026-12-11', '2027-01-15']
        self.assertEqual(choose_expiries(listed, '2026-10-26'),
                         {'0': '2026-10-26', '1-4': '2026-10-28', '5-30': '2026-11-09', '31-75': '2026-12-11'})
        # no same-day expiry and nothing inside 31-75 days: those buckets are simply absent
        self.assertEqual(choose_expiries(['2026-10-30', '2027-03-19'], '2026-10-27'), {'1-4': '2026-10-30'})

    def test_ties_go_to_the_nearer_expiry(self):
        self.assertEqual(choose_expiries(['2026-10-27', '2026-10-29'], '2026-10-26')['1-4'], '2026-10-27')

    def test_atm_pair_needs_both_sides_on_the_same_strike(self):
        def row(code, right):
            return {'code': code, 'option_type': right, 'strike_time': '2026-11-20'}
        chain = [row('US.SPY261120C600000', 'CALL'), row('US.SPY261120P600000', 'PUT'),
                 row('US.SPY261120C601000', 'CALL'),                       # nearer, but no PUT
                 row('US.SPY261120C595000', 'CALL'), row('US.SPY261120P595000', 'PUT'),
                 row('US.QQQ261120C600000', 'CALL')]                       # another underlying
        self.assertEqual(atm_pair(chain, 'US.SPY', '2026-11-20', 600.9),
                         {'CALL': 'US.SPY261120C600000', 'PUT': 'US.SPY261120P600000'})
        self.assertIsNone(atm_pair(chain[2:3], 'US.SPY', '2026-11-20', 601.0))


if __name__ == '__main__':
    unittest.main()
