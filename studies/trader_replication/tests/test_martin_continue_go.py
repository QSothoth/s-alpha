import unittest

from studies.trader_replication.martin_continue_go import momentum21, label_group


class TestOneMonthLeader(unittest.TestCase):
    def test_future_action_does_not_change_current_strength(self):
        days = [f'{i:03d}' for i in range(25)]
        index = {day: i for i, day in enumerate(days)}
        rows = [(day, [10., 10., 10., 10. + i]) for i, day in enumerate(days)]
        original = momentum21(days, index, rows, [], {days[21]})
        future = momentum21(days, index, rows, [(days[23], .5, 0.)], {days[21]})
        self.assertEqual(original, future)
        self.assertAlmostEqual(original[days[21]], 2.1)

    def test_missing_original_market_session_is_unknown(self):
        days = [f'{i:03d}' for i in range(23)]
        index = {day: i for i, day in enumerate(days)}
        rows = [(day, [10., 10., 10., 10.]) for day in days if day != days[1]]
        self.assertIsNone(momentum21(days, index, rows, [], {days[22]})[days[22]])

    def test_candidate_ranking_handles_ties_and_unknowns_before_results(self):
        rows = [{'code': 'B', 'momentum21': .5}, {'code': 'A', 'momentum21': .5},
                {'code': 'C', 'momentum21': .1}, {'code': 'D', 'momentum21': None}]
        self.assertEqual(label_group(rows), (3, 1))
        self.assertEqual({r['code']: r['leader'] for r in rows}, {'A': True, 'B': False, 'C': False, 'D': None})
