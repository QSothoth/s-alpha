"""Synthetic fixtures only; checks P3 definitions, never market data."""
import unittest

from studies.us_0dte_picks import p3


def bars(path, open_=100.0):
    """78 bars; path gives (high, low, close) overrides by index."""
    out, previous = [], open_
    for i, clock in enumerate(p3.GRID):
        h, low, c = path.get(i, (previous + .05, previous - .05, previous))
        out.append((clock, previous, h, low, c, 1000.0))
        previous = c
    return out


class FirstTouchTests(unittest.TestCase):
    def test_target_before_stop_and_same_bar_counts_as_stop(self):
        entry, s = 100.0, .01  # target 101, stop 99.5 for a long
        up = bars({8: (101.2, 100.1, 101.1)})
        self.assertEqual(p3.first_touch(up, entry, s, 1)[:3], (1.0, True, False))
        both = bars({8: (101.2, 99.4, 100.0)})
        self.assertEqual(p3.first_touch(both, entry, s, 1)[:3], (-.5, False, True))
        down = bars({9: (100.1, 98.9, 99.0)})  # short wins on the same path
        self.assertEqual(p3.first_touch(down, entry, s, -1)[:3], (1.0, True, False))

    def test_bars_before_entry_are_ignored_and_timeout_is_clipped(self):
        early = bars({2: (105, 95, 100)})  # 09:45 bar, before the 10:00 entry
        result = p3.first_touch(early, 100.0, .01, 1)
        self.assertFalse(result[1] or result[2])
        drift = bars({77: (100.4, 100.2, 100.3)})
        self.assertAlmostEqual(p3.first_touch(drift, 100.0, .01, 1)[0], .3)


class SignalTests(unittest.TestCase):
    base = {'rvol30': 2.5, 'color': 1, 'beyond_or5': 1, 'drive_z': .6, 'gap_z': .2, 'trend': 1,
            'thrust': 0, 'above_c1': 1, 'earnings': False}

    def test_orb_and_confluence_need_agreeing_evidence(self):
        self.assertEqual(p3.signal(dict(self.base), 'A1_ORB'), (1, 2.5))
        self.assertEqual(p3.signal(dict(self.base), 'A5_CONFLUENCE'), (1, 2.5))
        self.assertIsNone(p3.signal(dict(self.base, trend=-1), 'A5_CONFLUENCE'))
        self.assertIsNone(p3.signal(dict(self.base, beyond_or5=0), 'A1_ORB'))
        self.assertIsNone(p3.signal(dict(self.base, rvol30=1.5), 'A1_ORB'))

    def test_gap_go_requires_the_gap_to_hold(self):
        record = dict(self.base, gap_z=-2.0, drive_z=-.1)
        self.assertEqual(p3.signal(record, 'A3_GAP_GO'), (-1, 2.0))
        self.assertIsNone(p3.signal(dict(record, drive_z=.2), 'A3_GAP_GO'))

    def test_flow_candidates(self):
        record = dict(self.base, flow={'rel': .8, 'net': -.7, 'otm_rel': .3, 'otm_net': .9,
                                       'prior_rel': .1, 'prior_net': 1.0})
        self.assertEqual(p3.signal(record, 'B1_FLOW_NET'), (-1, .8))
        self.assertEqual(p3.signal(record, 'B2_FLOW_OTM_BUY'), (1, .3))
        self.assertIsNone(p3.signal(record, 'B3_FLOW_CONFIRM'))  # price drives up, flow says down
        self.assertIsNone(p3.signal(record, 'B5_FLOW_PRIOR_DAY'))
        self.assertIsNone(p3.signal(dict(self.base), 'B1_FLOW_NET'))

    def test_flow_sums_sentiment_weighted_turnover(self):
        events = {'2026-01-02': [('09:31:00', 'BULLISH', 100.0, 'BUY', 'CALL', 2, 3.0),
                                 ('09:45:00', 'BEARISH', 50.0, 'BUY', 'PUT', 30, 5.0),
                                 ('10:05:00', 'BULLISH', 999.0, 'BUY', 'CALL', 1, 1.0)]}
        self.assertEqual(p3.flow(events, '2026-01-02', '09:30:00', '10:00:00'), (100.0, 50.0))
        self.assertEqual(p3.flow(events, '2026-01-02', '09:30:00', '10:00:00', p3.near_otm_buy), (100.0, 0.0))


class OptionTests(unittest.TestCase):
    def test_atm_value_and_expiry_intrinsic(self):
        call = p3.bs_price(100, 100, .3, 1 / 252, 1)
        put = p3.bs_price(100, 100, .3, 1 / 252, -1)
        self.assertAlmostEqual(call, put, places=6)
        self.assertAlmostEqual(call, .4 * 100 * .3 / 252 ** .5, delta=.02)
        self.assertEqual(p3.bs_price(103, 100, .3, 0, 1), 3)
        self.assertGreater(p3.option_estimate(100, 101.5, 77, 30, 1), 0)


if __name__ == '__main__':
    unittest.main()
