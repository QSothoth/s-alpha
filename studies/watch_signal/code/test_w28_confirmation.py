"""Synthetic timing checks only; study performance uses real market data."""
import unittest
from datetime import datetime, timedelta

from w28_confirmation import confirmations


def tape(n=12, start='2026-10-14 09:30:00', sign=1):
    opening = datetime.fromisoformat(start)
    return [((opening + timedelta(minutes=i)).isoformat(' '),
             100 + sign * i, 102 + sign * i, 98 + sign * i, 100 + sign * (i + 1), 1000)
            for i in range(n)]


def flags(bars, sign=1):
    return confirmations(bars, [100 - sign * 100] * len(bars),
                         [100 + sign] * len(bars), [100] * len(bars))


class ConfirmationTests(unittest.TestCase):
    def test_completion_and_direction(self):
        for sign in (1, -1):
            self.assertEqual(flags(tape(sign=sign), sign), [0] * 5 + [sign] * 7)

    def test_gaps_reset_and_do_not_make_partial_blocks(self):
        bars = tape(18)
        del bars[7]
        expected = [0] * 5 + [1] * 2 + [0] * 6 + [1] * 4
        self.assertEqual(flags(bars), expected)
        self.assertEqual(flags(tape(9)[1:]), [0] * 7 + [1])

    def test_lunch_and_day_reset(self):
        morning = tape(6)
        afternoon = tape(6, start='2026-10-14 13:00:00')
        tomorrow = tape(6, start='2026-10-15 09:30:00')
        self.assertEqual(flags(morning + afternoon + tomorrow), ([0] * 5 + [1]) * 3)
        self.assertEqual(flags(tape(9, start='2026-10-14 11:54:00')), [0] * 5 + [1, 0, 0, 0])

    def test_support_and_progress_required(self):
        bars = tape(6)
        self.assertEqual(confirmations(bars, [200] * 6, [101] * 6, [100] * 6), [0] * 6)
        self.assertEqual(confirmations(bars, [0] * 6, [100] * 6, [100] * 6), [0] * 6)
        bars[3:] = [(b[0], b[1] - 3, b[2] - 3, b[3] - 3, b[4] - 3, b[5]) for b in bars[3:]]
        self.assertEqual(flags(bars), [0] * 6)

    def test_prefix_and_last_completed_blocks(self):
        bars = tape(12)
        b = bars[8]
        bars[8] = (b[0], b[1], b[2], b[3], 99, b[5])
        result = flags(bars)
        self.assertEqual(result, [0] * 5 + [1] * 3 + [0] * 4)
        for cut in range(len(bars) + 1):
            self.assertEqual(flags(bars[:cut]), result[:cut])

    def test_against_timestamp_slice_reference(self):
        # An independent timestamp lookup checks every possible one-minute gap.
        for sign in (1, -1):
            original = tape(24, sign=sign)
            for missing in range(-1, len(original)):
                bars = [b for i, b in enumerate(original) if i != missing]
                by_time = {datetime.fromisoformat(b[0]): b for b in bars}
                expected = []
                for bar in bars:
                    now = datetime.fromisoformat(bar[0])
                    offset = int((now - datetime(2026, 10, 14, 9, 30)).total_seconds() / 60)
                    end = now - timedelta(minutes=(offset + 1) % 3)
                    start = end - timedelta(minutes=5)
                    times = [start + timedelta(minutes=k)
                             for k in range(int((now - start).total_seconds() / 60) + 1)]
                    if not all(t in by_time for t in times):
                        expected.append(0)
                        continue
                    blocks = [[by_time[start + timedelta(minutes=k + j)] for j in range(3)]
                              for k in (0, 3)]
                    supported = all(sign * (b[-1][4] - b[0][1]) > 0 for b in blocks)
                    progressing = sign * (blocks[1][-1][4] - blocks[0][-1][4]) > 0
                    expected.append(sign if supported and progressing else 0)
                self.assertEqual(flags(bars, sign), expected)


if __name__ == '__main__':
    unittest.main()
