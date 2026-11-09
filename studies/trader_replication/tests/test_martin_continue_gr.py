import unittest

from studies.trader_replication.martin_continue_gr import fast_counts, label_group


class TestRecentFastMoves(unittest.TestCase):
    def test_only_past_actions_are_used(self):
        days = [f'{i:03d}' for i in range(24)]
        index = {day: i for i, day in enumerate(days)}
        prices = [100.] * 22 + [110., 55.]
        rows = [(day, [p, p, p, p]) for day, p in zip(days, prices)]
        signal = {days[22]}
        expected = fast_counts(days, index, rows, [], signal)
        actual = fast_counts(days, index, rows, [(days[23], .5, 0.)], signal)
        self.assertEqual(actual, expected)
        self.assertEqual(actual[days[22]], 1)

    def test_missing_day_and_exact_boundary_are_unknown(self):
        days = [f'{i:03d}' for i in range(23)]
        index = {day: i for i, day in enumerate(days)}
        rows = [(day, [100., 100., 100., 100.]) for day in days if day != days[2]]
        self.assertIsNone(fast_counts(days, index, rows, [], {days[21]})[days[21]])
        rows = [(day, [100., 100., 100., 105. if i >= 21 else 100.]) for i, day in enumerate(days)]
        self.assertIsNone(fast_counts(days, index, rows, [], {days[21]})[days[21]])

    def test_tied_counts_are_never_split(self):
        rows = [{'count': n} for n in (0, 1, 1, 1, 2, 2, None)]
        self.assertEqual(label_group(rows), 1)
        self.assertEqual([r['fast'] for r in rows], [False, False, False, False, True, True, None])
