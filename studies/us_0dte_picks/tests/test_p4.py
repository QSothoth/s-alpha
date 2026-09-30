"""Synthetic fixtures only; checks P4 filter definitions, never market data."""
import unittest

from studies.us_0dte_picks import p3, p4
from studies.us_0dte_picks.tests.test_p3 import bars


def record(**updates):
    base = {'rvol30': 2.5, 'color': 1, 'beyond_or5': 1, 'drive_z': .6, 'gap_z': .2, 'trend': 1, 'thrust': 0,
            'above_c1': 1, 'earnings': False, 'spy_drive_z': .3, 'rel': .02, 'sigma': .02, 'eff': .7,
            'vwap_sides': [1] * 6, 'or5': (101.0, 99.0), 'p10': 101.5, 'p1030': 102.0}
    base.update(updates)
    return base


class FilterTests(unittest.TestCase):
    def test_each_filter_needs_the_a1_base(self):
        for name in p4.FILTERS:
            self.assertEqual(p4.filter_signal(record(), name), (1, 2.5), name)
            self.assertIsNone(p4.filter_signal(record(rvol30=1.0), name), name)

    def test_filters_reject_their_own_failures(self):
        self.assertIsNone(p4.filter_signal(record(spy_drive_z=-.3), 'C1_MARKET_ALIGN'))
        self.assertIsNone(p4.filter_signal(record(spy_drive_z=None), 'C1_MARKET_ALIGN'))
        self.assertIsNone(p4.filter_signal(record(rel=.005), 'C2_REL_STRENGTH'))
        self.assertIsNone(p4.filter_signal(record(eff=.5), 'C3_EFFICIENCY'))
        self.assertIsNone(p4.filter_signal(record(vwap_sides=[1, 1, 1, 0, 1, 1]), 'C4_VWAP_HOLD'))
        self.assertIsNone(p4.filter_signal(record(p1030=101.2), 'C5_LATE_CONFIRM'))  # gave back ground since 10:00


class LateEntryTests(unittest.TestCase):
    def test_late_entry_scans_from_the_next_bar(self):
        path = bars({8: (110, 90, 100), 13: (101.2, 100.1, 101.1)})  # the 10:15 spike is before a 10:30 entry
        result = p4.first_touch_from(path, p4.LATE_INDEX, 100.0, .01, 1)
        self.assertEqual(result[:3], (1.0, True, False))
        self.assertEqual(result[4], 13)
        self.assertEqual(p3.first_touch(path, 100.0, .01, 1)[:3], (-.5, False, True))


if __name__ == '__main__':
    unittest.main()
