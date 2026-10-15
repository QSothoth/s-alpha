"""Causal event checks with synthetic plumbing fixtures, never research returns."""
import unittest
from test_w28_confirmation import tape
from w29_strong import strong_events


def run(bars, raw, sign=1):
    f = dict(vwap=[100 - 100 * sign] * len(bars), ema9=[100 + sign] * len(bars),
             ema21=[100] * len(bars), vr=[2] * len(bars))
    return strong_events(bars, f, raw)


class StrongTests(unittest.TestCase):
    def test_continuous_is_one_event_and_symmetry(self):
        for sign in (1, -1):
            bars = tape(40, sign=sign)
            raw = {i: (sign, {'BOS'}) for i in range(40)}
            result = run(bars, raw, sign)
            self.assertEqual(result['W2'], [(1, sign)])
            self.assertEqual(result['W3'], [(2, sign)])
            self.assertEqual(result['E2'], [])

    def test_independent_episodes_and_cooldown(self):
        bars = tape(24)
        raw = {i: (1, {'BOS'}) for i in (0, 2, 4, 16, 18)}
        result = run(bars, raw)
        self.assertEqual(result['E2'], [(2, 1), (18, 1)])
        self.assertEqual(result['W2'], [(2, 1), (18, 1)])

    def test_structure_requires_distinct_minutes(self):
        bars = tape(4)
        raw = {0: (1, {'BOS', 'FVG'}), 2: (1, {'BOS'})}
        self.assertEqual(run(bars, raw)['M2'], [(2, 1)])

    def test_gaps_and_lunch_reset(self):
        for bars in (tape(1) + tape(1, start='2026-10-14 09:32:00'),
                     tape(1, start='2026-10-14 11:59:00') + tape(1, start='2026-10-14 13:00:00')):
            self.assertTrue(all(not rows for rows in run(bars, {0: (1, {'BOS'}), 1: (1, {'FVG'})}).values()))

    def test_prefix_and_future_signals(self):
        bars = tape(24)
        raw = {i: (1, {'BOS' if i % 2 else 'FVG'}) for i in (0, 2, 4, 16, 18, 20)}
        full = run(bars, raw)
        for cut in range(25):
            self.assertEqual(run(bars[:cut], raw), {k: [(i, s) for i, s in v if i < cut]
                                                  for k, v in full.items()})

    def test_strength_and_bias_reset(self):
        bars = tape(4)
        raw = {0: (1, {'BOS'}), 2: (1, {'BOS'})}
        f = dict(vwap=[0] * 4, ema9=[101] * 4, ema21=[100] * 4, vr=[2] * 4)
        self.assertEqual(strong_events(bars, f, raw)['S2'], [(2, 1)])
        f['vr'][2] = 1
        self.assertEqual(strong_events(bars, f, raw)['S2'], [])
        f['vwap'][1] = 200
        self.assertEqual(strong_events(bars, f, raw)['W2'], [])


if __name__ == '__main__':
    unittest.main()
